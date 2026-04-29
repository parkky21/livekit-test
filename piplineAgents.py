import asyncio
import time as _time
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
from helpers.prompts_text import host_manager, tech_lead, behavioral, culture_fit
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

persona = { "girl":["heart","kore", "sarah"], "boy":["liam","puck","eric"]}

time_limits = {"tech_lead": 4, "behavioral": 2, "culture": 2}  # minutes per agent


# ---------------------------------------------------------------------------
# Time-Alert Helper — fires background warnings so agents wrap up on time
# ---------------------------------------------------------------------------

async def _start_time_alerts(agent: Agent, segment_name: str):
    """Spawn a background task that nudges the agent at key time thresholds.

    Thresholds (in minutes remaining):
      • 2 min left  → gentle nudge
      • 1 min left  → firm reminder
      • 0 min left  → hard stop, instructs handoff

    The task is stored on `agent._timer_task` so it can be cancelled in
    on_exit or when the agent is garbage-collected.
    """
    total_minutes = time_limits.get(segment_name)
    if total_minutes is None:
        return  # host has no time limit

    total_seconds = total_minutes * 60
    start = _time.monotonic()

    # Define thresholds as (remaining_seconds, instruction_message)
    thresholds = [
        (
            120,
            f"⏱️ TIME CHECK: You have about 2 minutes left in your {total_minutes}-minute segment. "
            f"Start wrapping up your current question — do NOT start a new primary question.",
        ),
        (
            60,
            f"⏱️ ONE MINUTE LEFT: You have ~1 minute remaining. Finish your current probe "
            f"and begin your handoff transition to the next panelist.",
        ),
        (
            0,
            f"⏱️ TIME'S UP: Your {total_minutes}-minute segment is over. "
            f"Immediately deliver your closing line and hand off to the next panelist NOW.",
        ),
    ]

    # Only keep thresholds that make sense for the segment length
    thresholds = [
        (remaining, msg)
        for remaining, msg in thresholds
        if remaining < total_seconds  # skip if threshold >= total time
    ] + [(0, thresholds[-1][1])]  # always keep the "time's up" alert

    # Deduplicate the 0-second entry if it was already there
    seen = set()
    unique_thresholds = []
    for remaining, msg in thresholds:
        if remaining not in seen:
            seen.add(remaining)
            unique_thresholds.append((remaining, msg))
    thresholds = sorted(unique_thresholds, key=lambda x: x[0], reverse=True)

    for remaining_threshold, message in thresholds:
        elapsed = _time.monotonic() - start
        fire_at = total_seconds - remaining_threshold
        delay = fire_at - elapsed
        if delay > 0:
            await asyncio.sleep(delay)

        # Agent may have already been swapped out
        if agent.session is None:
            return

        agent.session.generate_reply(instructions=message)

    # After the final alert, give a 30-second grace period then force handoff
    await asyncio.sleep(30)
    if agent.session is not None:
        agent.session.generate_reply(
            instructions="⛔ GRACE PERIOD OVER. You MUST hand off RIGHT NOW. "
            "Say your closing line and call the transfer function immediately."
        )

# ---------------------------------------------------------------------------
# Handoff Tool Functions — return a new Agent instance to switch to
# ---------------------------------------------------------------------------

async def transfer_to_host(context: RunContext):
    """Transfer the conversation to Sarah (Hiring Manager/Host) for welcoming or wrapping up."""
    return HostAgent(
        chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
    )

async def transfer_to_tech_lead(context: RunContext):
    """Transfer the conversation to Marcus (Tech Lead) for deep technical and architecture questions."""
    return TechLeadAgent(
        chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
    )


async def transfer_to_behavioral(context: RunContext):
    """Transfer the conversation to Sophia (Behavioral Interviewer) for STAR-method questions about past experiences."""
    return BehavioralAgent(
        chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
    )


async def transfer_to_culture(context: RunContext):
    """Transfer the conversation to Elena (Culture/Soft Skills) for conversational assessment of values and communication."""
    return CultureAgent(
        chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
    )


# ---------------------------------------------------------------------------
# Agent Definitions — each has its own LLM (with a unique voice) + handoff tools
# ---------------------------------------------------------------------------

class HostAgent(Agent):
    """The face of the interview. Manages opening, transitions, and closing."""

    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(
            instructions=host_manager,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][2]  # Sarah
            ),
            tools=[
                llm.function_tool(transfer_to_tech_lead),
                llm.function_tool(transfer_to_behavioral),
                llm.function_tool(transfer_to_culture),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        # Sarah (host) has no time limit — she manages the overall flow
        pass


class TechLeadAgent(Agent):
    """Deep technical, system design, and pressure testing."""

    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=tech_lead,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["boy"][0]  # Marcus
            ),
            tools=[
                llm.function_tool(transfer_to_host),
                llm.function_tool(transfer_to_behavioral),
                llm.function_tool(transfer_to_culture),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as Marcus, the Tech Lead. "
            )
        # Start time-tracking alerts for this segment
        self._timer_task = asyncio.create_task(
            _start_time_alerts(self, "tech_lead")
        )


class BehavioralAgent(Agent):
    """STAR method specialist looking for patterns in past experiences."""

    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=behavioral,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][1]  # Sophia
            ),
            tools=[
                llm.function_tool(transfer_to_host),
                llm.function_tool(transfer_to_tech_lead),
                llm.function_tool(transfer_to_culture),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as Sophia, the Behavioral Interviewer. "
        )
        # Start time-tracking alerts for this segment
        self._timer_task = asyncio.create_task(
            _start_time_alerts(self, "behavioral")
        )


class CultureAgent(Agent):
    """Assessment of communication, values, and self-awareness."""

    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=culture_fit,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][0]  # Elena
            ),
            tools=[
                llm.function_tool(transfer_to_host),
                llm.function_tool(transfer_to_tech_lead),
                llm.function_tool(transfer_to_behavioral),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as Elena, covering Culture and Soft Skills. "
        )
        # Start time-tracking alerts for this segmnt
        self._timer_task = asyncio.create_task(
            _start_time_alerts(self, "culture")
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
        agent=HostAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await session.generate_reply(
        instructions="Welcome the candidate to their AI Engineer interview. Introduce yourself as Sarah, the Hiring Manager and Host. "
        "Explain that the panel has 4 interviewers: "
        "Yourself (Host), Marcus (Tech Lead), Sophia (Behavioral), and Elena (Culture/Soft Skills). "
        "Invite them to briefly introduce themselves, then explain you'll pass them to Marcus to start. "
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