import asyncio
import logging
import os

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, room_io
from livekit.plugins import deepgram, noise_cancellation, openai, silero

# Panel agents (Phase 1) — each has its own voice, tools, and per-agent timer
from panelQA import HostAgent, TechLeadAgent, BehavioralAgent, CultureAgent

# Q&A agents (Phase 2) — candidate asks, panelists answer
from candidateQA import QAHostAgent, QATechLeadAgent, QABehavioralAgent, QACultureAgent

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")

VOICES = {"sarah": "sarah", "marcus": "liam", "sophia": "kore", "elena": "heart"}

PANEL_MINUTES = 15
QA_MINUTES = 5

def _make_tts(voice_key: str) -> openai.TTS:
    """Create a LemonFox TTS instance for the given persona."""
    return openai.TTS(
        base_url="https://api.lemonfox.ai/v1",
        model="tts-1",
        api_key=LEMONFOX_API_KEY,
        voice=VOICES[voice_key],
    )

async def _master_timer(session: AgentSession) -> None:
    """Background task that enforces the two-phase time structure.

    Phase 1 (Panel):  PANEL_MINUTES
      - 2 min warning → system message
      - 30s left      → force wrap-up + transition to Q&A
    Phase 2 (Q&A):    QA_MINUTES
      - 1 min warning → system message
      - 30s left      → force closing
    """
    try:
        total_panel = PANEL_MINUTES * 60

        # ── Panel: 2 min warning ─────────────────────────────────────────
        await asyncio.sleep(total_panel - 120)
        print("[MASTER TIMER] Panel: 2 minutes left")
        session.history.add_message(
            role="system",
            content=(
                "[PANEL: 2 MIN LEFT] The panel round has 2 minutes remaining. "
                "Current agent: wrap up your question and prepare for transition."
            ),
        )

        # ── Panel: 30s left → force wrap-up ──────────────────────────────
        await asyncio.sleep(90)
        print("[MASTER TIMER] Panel: 30 seconds — forcing wrap-up")
        session.history.add_message(
            role="system",
            content="[PANEL: TIME UP] Say your closing line NOW and hand back to Sarah.",
        )
        session.generate_reply(
            instructions=(
                "Time is up for the panel round. Thank the candidate briefly "
                "and let them know we're moving to the Q&A round."
            )
        )

        # ── Panel → Q&A transition ───────────────────────────────────────
        await asyncio.sleep(30)
        print("[MASTER TIMER] Forcing transition to Q&A phase")
        session.update_agent(
            QAHostAgent(
                chat_ctx=session.history.copy(
                    exclude_function_call=True,
                    exclude_instructions=True,
                )
            )
        )

        # ── Q&A: 1 min warning ───────────────────────────────────────────
        total_qa = QA_MINUTES * 60
        await asyncio.sleep(total_qa - 60)
        print("[MASTER TIMER] Q&A: 1 minute left")
        session.history.add_message(
            role="system",
            content="[Q&A: 1 MIN LEFT] Let the candidate finish, then wrap up.",
        )

        # ── Q&A: 30s left → force closing ────────────────────────────────
        await asyncio.sleep(30)
        print("[MASTER TIMER] Q&A: 30 seconds — forcing close")
        session.history.add_message(
            role="system",
            content="[Q&A: TIME UP] Close the interview now.",
        )
        session.generate_reply(
            instructions=(
                "Time is up. Thank the candidate warmly, share next "
                "steps (hear back within a week), and say goodbye."
            )
        )

        await asyncio.sleep(30)
        print("[MASTER TIMER] Interview complete")

    except asyncio.CancelledError:
        print("[MASTER TIMER] Timer cancelled")


server = AgentServer()


def prewarm(proc: agents.JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def full_interview(ctx: agents.JobContext):
    session = AgentSession(
        llm=openai.LLM(
            api_key=OPENAI_API_KEY,
            model="gpt-4.1-mini",
            parallel_tool_calls=False,
        ),
        stt=deepgram.STT(
            model="nova-3",
            language="en-US",
            api_key=DEEPGRAM_API_KEY,
        ),
        tts=_make_tts("sarah"),  # default TTS
        vad=ctx.proc.userdata.get("vad"),
    )

    # Start with the panel HostAgent (Sarah) from panelQA.py
    await session.start(
        room=ctx.room,
        agent=HostAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda p: noise_cancellation.BVCTelephony()
                if p.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    # Initial welcome (HostAgent.on_enter is a pass, so we trigger it here)
    await session.generate_reply(
        instructions=(
            "Welcome the candidate to their AI Engineer interview. "
            "Introduce yourself as Sarah, the Hiring Manager and Host. "
            "Introduce the panel: Marcus (Tech Lead), Sophia (Behavioral), "
            "Elena (Culture/Soft Skills). Ask if they're ready. "
            "Keep it under 4 sentences."
        )
    )

    # Start the master timer to enforce phase boundaries
    asyncio.create_task(_master_timer(session))


class _SuppressDecodeErrors(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not (msg == "error decoding audio" or "avcodec_send_packet" in msg)

logging.getLogger("livekit.agents").addFilter(_SuppressDecodeErrors())

if __name__ == "__main__":
    agents.cli.run_app(server)
