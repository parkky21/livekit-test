import asyncio
import time as _time
from dataclasses import dataclass
from typing import Optional
from livekit.agents import ChatContext
from livekit.agents import RunContext
from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm, AgentTask
from livekit.plugins import (
    noise_cancellation,
    silero,
    openai,
    deepgram,
)
import os
from utils.printer_logs import print_conversation_context
from utils.prompts_text import qa_host_manager, qa_tech_lead, qa_behavioral, qa_culture_fit

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

persona = {"girl": ["heart", "kore", "sarah"], "boy": ["liam", "puck", "eric"]}

# ---------------------------------------------------------------------------
# Handoff Tool Functions — each agent can transfer to every other agent
# ---------------------------------------------------------------------------

async def qa_transfer_to_host(context: RunContext):
    """Transfer to Sarah (Host) — for general questions, role overview, process, or to prompt the next question."""
    print_conversation_context(context)
    return QAHostAgent(
        chat_ctx=context.session._chat_ctx.copy(
            exclude_function_call=True,
            exclude_instructions=False,
        )
    )


async def qa_transfer_to_tech_lead(context: RunContext):
    """Transfer to Marcus (Tech Lead) — the candidate asked a technical question about architecture, tech stack, engineering practices, deployments, or code review."""
    print_conversation_context(context)
    return QATechLeadAgent(
        chat_ctx=context.session._chat_ctx.copy(
            exclude_function_call=True,
            exclude_instructions=False,
        )
    )


async def qa_transfer_to_behavioral(context: RunContext):
    """Transfer to Sophia (Behavioral) — the candidate asked about team dynamics, collaboration, mentorship, conflict resolution, or how people work together."""
    print_conversation_context(context)
    return QABehavioralAgent(
        chat_ctx=context.session._chat_ctx.copy(
            exclude_function_call=True,
            exclude_instructions=False,
        )
    )


async def qa_transfer_to_culture(context: RunContext):
    """Transfer to Elena (Culture/Soft Skills) — the candidate asked about company culture, values, work-life balance, diversity, remote work, or the workplace vibe."""
    print_conversation_context(context)
    return QACultureAgent(
        chat_ctx=context.session._chat_ctx.copy(
            exclude_function_call=True,
            exclude_instructions=False,
        )
    )


# ---------------------------------------------------------------------------
# Q&A Agent Definitions — candidate asks, panelists answer
# ---------------------------------------------------------------------------

class QAHostAgent(Agent):
    """Sarah — facilitates the Q&A round, answers general questions, routes topic-specific ones."""

    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(
            instructions=qa_host_manager,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][2]  # Sarah
            ),
            tools=[
                llm.function_tool(qa_transfer_to_tech_lead),
                llm.function_tool(qa_transfer_to_behavioral),
                llm.function_tool(qa_transfer_to_culture),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        # Host doesn't re-introduce — she just prompts the next question
        pass


class QATechLeadAgent(Agent):
    """Marcus — answers technical questions from the candidate."""

    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=qa_tech_lead,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["boy"][0]  # Marcus
            ),
            tools=[
                llm.function_tool(qa_transfer_to_host),
                llm.function_tool(qa_transfer_to_behavioral),
                llm.function_tool(qa_transfer_to_culture),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        # Marcus just answers — no introduction needed in Q&A mode
        self.session.generate_reply()


class QABehavioralAgent(Agent):
    """Sophia — answers questions about team dynamics and collaboration."""

    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=qa_behavioral,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][1]  # Sophia
            ),
            tools=[
                llm.function_tool(qa_transfer_to_host),
                llm.function_tool(qa_transfer_to_tech_lead),
                llm.function_tool(qa_transfer_to_culture),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        # Sophia just answers — no introduction needed in Q&A mode
        self.session.generate_reply()


class QACultureAgent(Agent):
    """Elena — answers questions about culture, values, and the human side."""

    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=qa_culture_fit,
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice=persona["girl"][0]  # Elena
            ),
            tools=[
                llm.function_tool(qa_transfer_to_host),
                llm.function_tool(qa_transfer_to_tech_lead),
                llm.function_tool(qa_transfer_to_behavioral),
            ],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        # Elena just answers — no introduction needed in Q&A mode
        self.session.generate_reply()


# ---------------------------------------------------------------------------
# Server Setup
# ---------------------------------------------------------------------------

server = AgentServer()


def prewarm(proc: agents.JobProcess):
    print("Prewarming")
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm


@server.rtc_session()
async def after_interview_qa(ctx: agents.JobContext):
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
        agent=QAHostAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await session.generate_reply(
        instructions="The interview is over. Now it's the candidate's turn. "
        "Say something warm like: 'Alright, that wraps up our questions! "
        "Now I want to make sure we leave plenty of time for yours. "
        "You've got the whole panel here — Marcus, Sophia, Elena, and myself. "
        "Ask us anything you'd like to know about the role, the team, or the company.' "
        "Keep it under 3 sentences. Sound genuinely inviting."
    )


import logging

class SuppressDecodeErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if msg == "error decoding audio" or "avcodec_send_packet" in msg:
            return False
        return True

logging.getLogger("livekit.agents").addFilter(SuppressDecodeErrorFilter())

if __name__ == "__main__":
    agents.cli.run_app(server)
