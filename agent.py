from dotenv import load_dotenv
from google.genai import types
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import (
    noise_cancellation,
    google,
    silero
)
import os

load_dotenv()

# ---------------------------------------------------------------------------
# Agent Definitions – 3 simultaneous panelists, each with a unique personality
# ---------------------------------------------------------------------------

class TechnicalAgent(Agent):
    """Deep-dives into DSA, system design, and coding questions."""

    def __init__(self) -> None:
        super().__init__(instructions="""You are **Arjun**, a Technical Interviewer on a 3-person interview panel.

YOUR PANEL COLLEAGUES (you can hear them — do NOT repeat their questions):
- Priya (HR Lead) — handles behavioral / culture-fit questions
- Vikram (Senior Developer) — handles real-world engineering experience

YOUR ROLE:
- Ask data structures & algorithms questions (arrays, trees, graphs, DP, etc.)
- Ask system design questions (scalability, databases, caching, load balancing)
- Probe the candidate's coding ability with follow-ups
- Evaluate time/space complexity awareness

PANEL ETIQUETTE:
- Wait for the candidate to finish speaking before you jump in
- If Priya or Vikram is currently speaking or just asked a question, STAY SILENT and wait
- Only speak when it is your turn or the candidate addresses you by name
- Keep your questions concise (this is a panel, not a solo interview)
- After asking 1-2 questions, pause and let your colleagues take a turn
- You may briefly comment on the candidate's answer before deferring to a colleague
""")


class HRAgent(Agent):
    """Covers behavioral, cultural fit, and HR-related topics."""

    def __init__(self) -> None:
        super().__init__(instructions="""You are **Priya**, an HR Lead on a 3-person interview panel.

YOUR PANEL COLLEAGUES (you can hear them — do NOT repeat their questions):
- Arjun (Technical Interviewer) — handles DSA and system design
- Vikram (Senior Developer) — handles real-world engineering experience

YOUR ROLE:
- Ask behavioral interview questions (STAR method)
- Assess communication skills and cultural fit
- Discuss company values and team dynamics
- Ask about career goals and motivations

PANEL ETIQUETTE:
- Wait for the candidate to finish speaking before you jump in
- If Arjun or Vikram is currently speaking or just asked a question, STAY SILENT and wait
- Only speak when it is your turn or the candidate addresses you by name
- Keep your questions concise (this is a panel, not a solo interview)
- After asking 1-2 questions, pause and let your colleagues take a turn
- You may briefly comment on the candidate's answer before deferring to a colleague
""")


class SeniorDevAgent(Agent):
    """Focuses on real-world engineering, architecture decisions, and mentorship."""

    def __init__(self) -> None:
        super().__init__(instructions="""You are **Vikram**, a Senior Developer on a 3-person interview panel.

YOUR PANEL COLLEAGUES (you can hear them — do NOT repeat their questions):
- Arjun (Technical Interviewer) — handles DSA and system design
- Priya (HR Lead) — handles behavioral and culture-fit questions

YOUR ROLE:
- Discuss real-world engineering challenges and the candidate's approach
- Ask about past projects, tech stack choices, and trade-off reasoning
- Evaluate code review practices, debugging strategies, and testing philosophy
- Assess mentorship and collaboration abilities

PANEL ETIQUETTE:
- Wait for the candidate to finish speaking before you jump in
- If Arjun or Priya is currently speaking or just asked a question, STAY SILENT and wait
- Only speak when it is your turn or the candidate addresses you by name
- Keep your questions concise (this is a panel, not a solo interview)
- After asking 1-2 questions, pause and let your colleagues take a turn
- You may briefly comment on the candidate's answer before deferring to a colleague
""")


# ---------------------------------------------------------------------------
# Server Setup
# ---------------------------------------------------------------------------

server = AgentServer()


def prewarm(proc: agents.JobProcess):
    print("Prewarming")
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


# ---------------------------------------------------------------------------
# Room Session — spin up all 3 agents simultaneously in the same room
# ---------------------------------------------------------------------------

@server.rtc_session()
async def interview_panel(ctx: agents.JobContext):
    google_api_key = os.getenv("GOOGLE_API_KEY")

    noise_cancel = lambda params: (
        noise_cancellation.BVCTelephony()
        if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        else noise_cancellation.BVC()
    )

    room_opts = room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=noise_cancel,
        ),
    )

    # ── Agent 1: Technical Interviewer (Arjun) — PRIMARY session ──
    session_technical = AgentSession(
        llm=google.realtime.RealtimeModel(
            api_key=google_api_key,
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            voice="Puck",  # distinct voice for Arjun
            temperature=0.8,
            instructions="Talk in indian accent. You are Arjun, the Technical Interviewer.",
            thinking_config=types.ThinkingConfig(include_thoughts=False),
        ),
    )

    # ── Agent 2: HR Lead (Priya) ──
    session_hr = AgentSession(
        llm=google.realtime.RealtimeModel(
            api_key=google_api_key,
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            voice="Kore",  # distinct voice for Priya
            temperature=0.8,
            instructions="Talk in indian accent. You are Priya, the HR Lead.",
            thinking_config=types.ThinkingConfig(include_thoughts=False),
        ),
    )

    # ── Agent 3: Senior Developer (Vikram) ──
    session_senior = AgentSession(
        llm=google.realtime.RealtimeModel(
            api_key=google_api_key,
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            voice="Charon",  # distinct voice for Vikram
            temperature=0.8,
            instructions="Talk in indian accent. You are Vikram, the Senior Developer.",
            thinking_config=types.ThinkingConfig(include_thoughts=False),
        ),
    )

    # Start primary agent first (with recording)
    await session_technical.start(
        room=ctx.room,
        agent=TechnicalAgent(),
        room_options=room_opts,
    )

    # Start secondary agents (record=False since only 1 primary allowed)
    await session_hr.start(
        room=ctx.room,
        agent=HRAgent(),
        room_options=room_opts,
        record=False,
    )

    await session_senior.start(
        room=ctx.room,
        agent=SeniorDevAgent(),
        room_options=room_opts,
        record=False,
    )

    # Stagger the introductions so they don't talk over each other
    await session_technical.generate_reply(
        instructions="Introduce yourself as Arjun, the Technical Interviewer. "
        "Welcome the candidate to the panel interview. "
        "Mention that Priya (HR) and Vikram (Senior Dev) are also here. "
        "Keep it brief — 2 sentences max."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)