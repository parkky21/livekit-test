import asyncio
import time as _time
from dataclasses import dataclass
from typing import Optional
from livekit.agents import ChatContext
from livekit.agents import RunContext
from dotenv import load_dotenv
from google.genai import types
from livekit import agents, rtc
from dataclasses import dataclass
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm
from livekit.plugins import (
    noise_cancellation,
    google,
    silero,
    openai,
    deepgram,
)
import os
from utils.printer_logs import print_conversation_context
from utils.prompts_text import host_manager, tech_lead, behavioral, culture_fit
from utils.time_alerts import _start_time_alerts
from utils.chats_context import get_chat_context_without_instruction

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

persona = { "girl":["heart","kore", "sarah"], "boy":["liam","puck","eric"]}

time_limits = {"tech_lead": 3, "behavioral": 3, "culture": 3}  # minutes per agent

# ---------------------------------------------------------------------------
# Handoff Tool Functions — return a new Agent instance to switch to
# ---------------------------------------------------------------------------

async def transfer_to_host(context: RunContext):
    """Transfer the conversation to Sarah (Hiring Manager/Host) for welcoming or wrapping up."""
    print_conversation_context(context)
    return HostAgent(
        chat_ctx=get_chat_context_without_instruction(context)
    )

async def transfer_to_tech_lead(context: RunContext):
    """Transfer the conversation to Marcus (Tech Lead) for deep technical and architecture questions."""
    print_conversation_context(context)
    return TechLeadAgent(
        chat_ctx=get_chat_context_without_instruction(context)
    )


async def transfer_to_behavioral(context: RunContext):
    """Transfer the conversation to Sophia (Behavioral Interviewer) for STAR-method questions about past experiences."""
    print_conversation_context(context)
    return BehavioralAgent(
        chat_ctx=get_chat_context_without_instruction(context)
    )


async def transfer_to_culture(context: RunContext):
    """Transfer the conversation to Elena (Culture/Soft Skills) for conversational assessment of values and communication."""
    print_conversation_context(context)
    return CultureAgent(
        chat_ctx=get_chat_context_without_instruction(context)
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
            _start_time_alerts(self, "tech_lead", time_limits)
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
            _start_time_alerts(self, "behavioral", time_limits)
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
            _start_time_alerts(self, "culture", time_limits)
        )

# ---------------------------------------------------------------------------
# Server Setup
# ---------------------------------------------------------------------------

import logging

class SuppressDecodeErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if msg == "error decoding audio" or "avcodec_send_packet" in msg:
            return False
        return True

logging.getLogger("livekit.agents").addFilter(SuppressDecodeErrorFilter())

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
            parallel_tool_calls=False,
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


if __name__ == "__main__":
    agents.cli.run_app(server)