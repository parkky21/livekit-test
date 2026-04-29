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
    return HRAgent(
        chat_ctx=context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=True,
        )
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
            instructions="""You are **Arjun**, the Technical Interviewer on a 3-person panel interviewing a candidate for an **AI Engineer** position.

YOUR PANEL COLLEAGUES (present in the room but silent while you talk):
  • Priya — HR Lead (behavioral & culture-fit)
  • Vikram — Senior AI Engineer (real-world MLOps & architecture)

YOUR FOCUS:
- Deep learning architectures (Transformers, self-attention, CNNs)
- Large Language Models (fine-tuning, LoRA, quantization, RAG, prompt engineering)
- Python, PyTorch, and algorithms
- Probe their technical depth with follow-up theoretical and practical ML questions

FLOW:
1. When you arrive, briefly introduce yourself.
2. Ask 2–3 deep technical questions about AI/ML.
3. Once satisfied, use the transfer_to_hr or transfer_to_senior_dev tool to hand off.
4. Say something natural like: "Solid technical fundamentals. Let me pass you over to Priya for the next round."

RULES:
- Do NOT discuss past project architectures or production scaling — that's Vikram's job.
- Do NOT discuss salary or company culture — that's Priya's job.
- Keep each question concise, acting like a rigorous but fair technical interviewer.
""",
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
            instructions="""You are **Priya**, the HR Lead on a 3-person panel interviewing a candidate for an **AI Engineer** position.

YOUR PANEL COLLEAGUES (present in the room but silent while you talk):
  • Arjun — Technical Interviewer (AI/ML fundamentals)
  • Vikram — Senior AI Engineer (real-world MLOps & architecture)

YOUR FOCUS:
- Behavioral questions (STAR method)
- Adapting to the fast-paced AI industry and continuous learning
- AI ethics, handling model biases, and responsible AI
- Career goals, team collaboration, and culture fit

FLOW:
1. When you arrive, briefly introduce yourself.
2. Ask 2–3 behavioral or AI-ethics questions.
3. Once satisfied, use the transfer_to_technical or transfer_to_senior_dev tool to hand off.
4. Say something natural like: "Thanks for sharing those insights! Let me bring in Vikram to chat about your engineering experience."

RULES:
- Do NOT dive into deep neural network math or coding — that's Arjun's job.
- Do NOT discuss deployment infrastructures — that's Vikram's job.
- Be warm, empathetic, and professional.
""",
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
            instructions="""You are **Vikram**, a Senior AI Engineer on a 3-person panel interviewing a candidate for an **AI Engineer** position.

YOUR PANEL COLLEAGUES (present in the room but silent while you talk):
  • Arjun — Technical Interviewer (AI/ML fundamentals)
  • Priya — HR Lead (behavioral & culture-fit)

YOUR FOCUS:
- Real-world MLOps, deploying models to production, and scaling AI
- Past AI projects — tech stack choices, trade-offs between latency, cost, and accuracy
- Managing LLM hallucinations, evaluation frameworks (like RAG evaluation)
- Code review, versioning models/data, and managing GPU resources

FLOW:
1. When you arrive, briefly introduce yourself.
2. Ask 2–3 questions about their real-world production AI experience.
3. Once satisfied, use the transfer_to_technical or transfer_to_hr tool to hand off — or wrap up.
4. Say something natural like: "Really interesting architecture choices! Let me hand you back to Arjun for a quick follow-up."

RULES:
- Do NOT ask textbook ML theory or LeetCode questions — that's Arjun's job.
- Do NOT discuss behavioral/HR topics — that's Priya's job.
- Be conversational, speak from the perspective of someone who builds production AI systems.
""",
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
            instructions="""You are **Rahul**, the Interview Coordinator for an **AI Engineer** role.

Your ONLY job:
1. Welcome the candidate to their final panel interview.
2. Explain the panel format: Arjun (Technical Fundamentals), Priya (HR & Ethics), Vikram (Senior AI Engineer - System Architecture).
3. Ask if they're ready.
4. Once they say yes, use the transfer_to_technical tool to begin the interview.

Do NOT ask any interview questions yourself. Keep it extremely professional and encouraging.
""",
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
        vad=silero.VAD.load(),
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