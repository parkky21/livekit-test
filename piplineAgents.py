from dataclasses import dataclass
from typing import Optional
from livekit.agents import ChatContext
from livekit.agents import RunContext
from dotenv import load_dotenv
from google.genai import types
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm 
from livekit.plugins import (
    noise_cancellation,
    google,
    silero,
    openai,
    deepgram,
)
import os
from helpers.printer_logs import print_conversation_context
from helpers.prompts_text import technical, hr, senior_dev, coordinator
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

persona = { "girl":["heart","kore", "sarah"], "boy":["liam","puck","eric"]}

# ---------------------------------------------------------------------------
# Handoff Tool Functions — return a new Agent instance to switch to
# ---------------------------------------------------------------------------

async def transfer_to_technical(context: RunContext):
    """Transfer the conversation to Arjun (Technical Interviewer) for AI, ML, and coding questions."""
    return TechnicalAgent(
        chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
    )


async def transfer_to_hr(context: RunContext):
    """Transfer the conversation to Priya (HR Lead) for behavioral and culture-fit questions."""
    print("Transferring to HR Agent")
    chat = context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
    print_conversation_context(chat)
    return HRAgent(
        chat_ctx=chat
    )


async def transfer_to_senior_dev(context: RunContext):
    """Transfer the conversation to Vikram (Senior AI Engineer) for real-world MLOps and architecture discussions."""
    return SeniorDevAgent(chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        ))


# ---------------------------------------------------------------------------
# Agent Definitions — each has its own LLM (with a unique voice) + handoff tools
# ---------------------------------------------------------------------------

class TechnicalAgent(Agent):
    """Deep Learning, LLMs, and Python coding questions."""

    def __init__(self,chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=technical,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["boy"][1]
            ),
            tools=[
                llm.function_tool(transfer_to_hr),
                llm.function_tool(transfer_to_senior_dev),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        chat = self.chat_ctx
        self.session.generate_reply(
            instructions="Introduce yourself as Arjun, the Technical Interviewer. "
            "Keep it to 1–2 sentences, then ask your first AI/ML technical question."
        )


class HRAgent(Agent):
    """Behavioral, cultural fit, and AI ethics topics."""

    def __init__(self,chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=hr,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][0]
            ),
            tools=[
                llm.function_tool(transfer_to_technical),
                llm.function_tool(transfer_to_senior_dev),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as Priya, the HR Lead. "
            "Keep it to 1–2 sentences, then ask your first behavioral question."
        )


class SeniorDevAgent(Agent):
    """Real-world MLOps, architecture decisions, and scaling AI."""

    def __init__(self,chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=senior_dev,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["boy"][2]
            ),
            tools=[
                llm.function_tool(transfer_to_technical),
                llm.function_tool(transfer_to_hr),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as Vikram, the Senior AI Engineer. "
            "Keep it to 1–2 sentences, then ask about a past AI project or their experience deploying ML models to production."
        )


class CoordinatorAgent(Agent):
    """Welcomes the candidate and kicks off the AI Engineer panel."""

    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(
            instructions=coordinator,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["boy"][0]
            ),
            tools=[
                llm.function_tool(transfer_to_technical),
                llm.function_tool(transfer_to_hr),
                llm.function_tool(transfer_to_senior_dev),
            ],
            chat_ctx=chat_ctx
        )

# ---------------------------------------------------------------------------
# Server Setup
# ---------------------------------------------------------------------------

server = AgentServer()


def prewarm(proc: agents.JobProcess):
    print("Prewarming")
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm

@server.rtc_session()
async def interview_panel(ctx: agents.JobContext):
    vad_instance = ctx.proc.userdata.get("vad")

    session = AgentSession(
        llm=openai.LLM(
            api_key=OPENAI_API_KEY,
            model="gpt-4.1-mini",
        ),
        stt=deepgram.STT(
            model="nova-3",
            language="en-US",
            api_key=DEEPGRAM_API_KEY,
        ),
        vad=vad_instance,
    )

    await session.start(
        room=ctx.room,
        agent=CoordinatorAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await session.generate_reply(
        instructions="Welcome the candidate to their AI Engineer interview. Introduce yourself as Rahul, the coordinator. "
        "Explain that the panel has 3 interviewers: "
        "Arjun (AI/ML Fundamentals), Priya (HR & Ethics), and Vikram (Senior AI Engineer - Applied/Production). "
        "Ask if they're ready to begin. Keep it under 4 sentences."
    )


import logging

class SuppressDecodeErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # Suppress specifically the PyAV decoding errors
        if msg == "error decoding audio" or "avcodec_send_packet" in msg:
            return False
        return True

# Attach the filter to the livekit.agents logger to hide these specific decoding errors
logging.getLogger("livekit.agents").addFilter(SuppressDecodeErrorFilter())

if __name__ == "__main__":
    agents.cli.run_app(server)