"""
interviewWorkflow.py
====================
Full interview as two sequential, timed phases via TaskGroup:

  Phase 1 — Panel Interview  (15 min)  Panelists ask the candidate.
  Phase 2 — Candidate Q&A    ( 5 min)  Candidate asks the panel.

Run:  uv run interviewWorkflow.py dev
"""

# ── Imports ──────────────────────────────────────────────────────────────────

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AgentTask,
    ChatContext,
    function_tool,
    room_io,
)
from livekit.agents.beta.workflows import TaskGroup
from livekit.plugins import deepgram, noise_cancellation, openai, silero

from panelQA import BehavioralAgent, CultureAgent, TechLeadAgent
from candidateQA import QABehavioralAgent, QACultureAgent, QATechLeadAgent
from utils.prompts_text import host_manager, qa_host_manager

# ── Config ───────────────────────────────────────────────────────────────────

load_dotenv()

OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")

VOICES = {"sarah": "sarah", "marcus": "liam", "sophia": "kore", "elena": "heart"}

PANEL_MINUTES = 15
QA_MINUTES    = 5


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class PanelResult:
    status: str   # "time_up" | "completed"

@dataclass
class QAResult:
    status: str   # "time_up" | "completed"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _copy_ctx(session) -> ChatContext:
    """Shortcut: copy session chat context, stripping tool-call noise."""
    return session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Task 1 · Panel Interview  (15 min)
# ═════════════════════════════════════════════════════════════════════════════

class PanelInterviewTask(AgentTask[PanelResult]):
    """Panelists ask the candidate questions. Auto-completes after 15 min."""

    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(instructions=host_manager, chat_ctx=chat_ctx)
        self._timer: Optional[asyncio.Task] = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def on_enter(self) -> None:
        self._timer = asyncio.create_task(self._countdown())
        self.session.generate_reply(
            instructions=(
                "Welcome the candidate to their AI Engineer interview. "
                "Introduce yourself as Sarah, the Hiring Manager and Host. "
                "Introduce the panel: Marcus (Tech Lead), Sophia (Behavioral), "
                "Elena (Culture/Soft Skills). Ask if they're ready. "
                "Keep it under 4 sentences."
            )
        )

    # ── Timer ────────────────────────────────────────────────────────────

    async def _countdown(self) -> None:
        try:
            total = PANEL_MINUTES * 60

            # ⏱ 2-min warning
            await asyncio.sleep(total - 120)
            if self.session:
                self.session._chat_ctx.add_message(
                    role="system",
                    content="[2 MIN LEFT] Wrap up. The Q&A round is next.",
                )

            # ⏱ 30-sec warning
            await asyncio.sleep(90)
            if self.session:
                self.session._chat_ctx.add_message(
                    role="system",
                    content="[TIME UP — 30s] Say your closing line NOW.",
                )
                self.session.generate_reply(
                    instructions=(
                        "Time is up for the panel round. Thank the candidate "
                        "briefly and let them know we're moving to Q&A."
                    )
                )

            await asyncio.sleep(30)
            self.complete(PanelResult(status="time_up"))
        except asyncio.CancelledError:
            pass

    # ── Handoff tools ────────────────────────────────────────────────────

    @function_tool()
    async def transfer_to_tech_lead(self) -> TechLeadAgent:
        """Hand off to Marcus for deep technical questions."""
        return TechLeadAgent(chat_ctx=_copy_ctx(self.session))

    @function_tool()
    async def transfer_to_behavioral(self) -> BehavioralAgent:
        """Hand off to Sophia for STAR-method behavioral questions."""
        return BehavioralAgent(chat_ctx=_copy_ctx(self.session))

    @function_tool()
    async def transfer_to_culture(self) -> CultureAgent:
        """Hand off to Elena for culture & soft-skills assessment."""
        return CultureAgent(chat_ctx=_copy_ctx(self.session))

    @function_tool()
    async def panel_round_complete(self) -> None:
        """End the panel round early (e.g. all panelists finished)."""
        if self._timer:
            self._timer.cancel()
        self.complete(PanelResult(status="completed"))


# ═════════════════════════════════════════════════════════════════════════════
# Task 2 · Candidate Q&A  (5 min)
# ═════════════════════════════════════════════════════════════════════════════

class CandidateQATask(AgentTask[QAResult]):
    """Candidate asks the panel questions. Auto-completes after 5 min."""

    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(instructions=qa_host_manager, chat_ctx=chat_ctx)
        self._timer: Optional[asyncio.Task] = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def on_enter(self) -> None:
        self._timer = asyncio.create_task(self._countdown())
        self.session.generate_reply(
            instructions=(
                "Open the floor for the candidate's questions. "
                "'That wraps up our questions — now it's your turn! "
                "The whole panel is here. Ask us anything.' "
                "Keep it under 3 sentences."
            )
        )

    # ── Timer ────────────────────────────────────────────────────────────

    async def _countdown(self) -> None:
        try:
            total = QA_MINUTES * 60

            # ⏱ 1-min warning
            await asyncio.sleep(total - 60)
            if self.session:
                self.session._chat_ctx.add_message(
                    role="system",
                    content="[1 MIN LEFT] Let them finish, then wrap up.",
                )

            # ⏱ 30-sec final
            await asyncio.sleep(30)
            if self.session:
                self.session._chat_ctx.add_message(
                    role="system",
                    content="[TIME UP] Close the interview now.",
                )
                self.session.generate_reply(
                    instructions=(
                        "Time is up. Thank the candidate warmly, share next "
                        "steps (hear back within a week), and say goodbye."
                    )
                )

            await asyncio.sleep(30)
            self.complete(QAResult(status="time_up"))
        except asyncio.CancelledError:
            pass

    # ── Handoff tools ────────────────────────────────────────────────────

    @function_tool()
    async def transfer_to_tech_lead(self) -> QATechLeadAgent:
        """Candidate asked a technical question — Marcus answers."""
        return QATechLeadAgent(chat_ctx=_copy_ctx(self.session))

    @function_tool()
    async def transfer_to_behavioral(self) -> QABehavioralAgent:
        """Candidate asked about team dynamics — Sophia answers."""
        return QABehavioralAgent(chat_ctx=_copy_ctx(self.session))

    @function_tool()
    async def transfer_to_culture(self) -> QACultureAgent:
        """Candidate asked about culture / values — Elena answers."""
        return QACultureAgent(chat_ctx=_copy_ctx(self.session))

    @function_tool()
    async def qa_round_complete(self) -> None:
        """End Q&A early (candidate has no more questions)."""
        if self._timer:
            self._timer.cancel()
        self.complete(QAResult(status="completed"))


# ═════════════════════════════════════════════════════════════════════════════
# Orchestrator — runs both tasks in sequence via TaskGroup
# ═════════════════════════════════════════════════════════════════════════════

class InterviewOrchestrator(Agent):
    """
    Master agent.  Runs:
      1. PanelInterviewTask  (15 min)
      2. CandidateQATask     ( 5 min)
    Then closes the session.
    """

    def __init__(self) -> None:
        super().__init__(
            instructions="You orchestrate the interview. The tasks handle all interaction.",
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=VOICES["sarah"],
            ),
        )

    async def on_enter(self) -> None:
        task_group = TaskGroup(chat_ctx=self.chat_ctx)

        task_group.add(
            lambda: PanelInterviewTask(),
            id="panel_interview",
            description="Panel round — panelists ask the candidate (15 min)",
        )
        task_group.add(
            lambda: CandidateQATask(),
            id="candidate_qa",
            description="Q&A round — candidate asks the panel (5 min)",
        )

        results = await task_group

        print(f"[WORKFLOW] Panel:  {results.task_results.get('panel_interview')}")
        print(f"[WORKFLOW] Q&A:    {results.task_results.get('candidate_qa')}")

        await self.session.generate_reply(
            instructions="Thank the candidate one final time and wish them well."
        )


# ═════════════════════════════════════════════════════════════════════════════
# Server
# ═════════════════════════════════════════════════════════════════════════════

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
        tts=openai.TTS(
            base_url="https://api.lemonfox.ai/v1",
            model="tts-1",
            api_key=LEMONFOX_API_KEY,
            voice=VOICES["sarah"],
        ),
        vad=ctx.proc.userdata.get("vad"),
    )

    await session.start(
        room=ctx.room,
        agent=InterviewOrchestrator(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda p: noise_cancellation.BVCTelephony()
                if p.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )


# ── Logging ──────────────────────────────────────────────────────────────────

class _SuppressDecodeErrors(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not (msg == "error decoding audio" or "avcodec_send_packet" in msg)


logging.getLogger("livekit.agents").addFilter(_SuppressDecodeErrors())

if __name__ == "__main__":
    agents.cli.run_app(server)
