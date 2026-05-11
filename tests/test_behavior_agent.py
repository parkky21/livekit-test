import asyncio
import os
from typing import Optional
from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm, ChatContext, RunContext
from livekit.plugins import openai, deepgram, silero, noise_cancellation

from tests.test_time_alerts import start_test_time_alerts
from utils.chats_context import get_chat_context_without_instruction
import logging

load_dotenv()

LEMONFOX_API_KEY = os.getenv("LEMONFOX_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class SecondTestAgent(Agent):
    """The agent that receives the handoff."""
    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(
            instructions="You are the second test agent. Greet the user and confirm that the transfer was successful.",
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice="puck"
            ),
            tools=[],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as the Second Test Agent and acknowledge the successful transfer."
        )


async def transfer_to_second_agent(context: RunContext):
    """Transfer the conversation to the Second Test Agent."""
    return SecondTestAgent(
        chat_ctx=get_chat_context_without_instruction(context)
    )


class TestInstructionAgent(Agent):
    """An agent used purely to test instruction adherence and timing behavior."""

    def __init__(self, chat_ctx: Optional[ChatContext] = None) -> None:
        super().__init__(
            instructions=(
                "You are a strict test agent. Your primary directive is to follow system instructions "
                "about time remaining perfectly. When told to stop, you MUST stop the conversation "
                "and say goodbye without asking any further questions."
            ),
            tts=openai.TTS(
                base_url="https://api.lemonfox.ai/v1",
                model="tts-1",
                api_key=LEMONFOX_API_KEY,
                voice="sarah"
            ),
            tools=[llm.function_tool(transfer_to_second_agent)],
            chat_ctx=chat_ctx
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Introduce yourself as the Test Agent. Ask the user to talk about a topic of their choice for a couple of minutes."
        )
        # Start time-tracking alerts for this agent, testing a 2-minute total duration
        self._timer_task = asyncio.create_task(
            start_test_time_alerts(self, total_minutes=2)
        )


class SuppressDecodeErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if msg == "error decoding audio" or "avcodec_send_packet" in msg:
            return False
        return True

logging.getLogger("livekit.agents").addFilter(SuppressDecodeErrorFilter())

server = AgentServer()

def prewarm(proc: agents.JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm

@server.rtc_session()
async def test_agent_panel(ctx: agents.JobContext):
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
        agent=TestInstructionAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
