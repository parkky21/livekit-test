from dotenv import load_dotenv
from dataclasses import dataclass, field
from google.genai import types
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm, RunContext, function_tool
from livekit.plugins import noise_cancellation, google, silero
import os

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


# ---------------------------------------------------------------------------
# Shared Panel State — lives in ctx.userdata, all agents read and write to it
# ---------------------------------------------------------------------------

@dataclass
class PanelState:
    # Per-agent running observations e.g. {"arjun": ["Strong on transformers", ...]}
    notes: dict = field(default_factory=lambda: {"arjun": [], "priya": [], "vikram": []})

    # After a quick interjection, who should resume the floor
    return_to: str = ""

    # Who is currently holding the floor
    current_speaker: str = "coordinator"

    def add_note(self, agent_name: str, note: str):
        self.notes.setdefault(agent_name, []).append(note)

    def get_all_notes(self) -> str:
        lines = []
        for agent, observations in self.notes.items():
            if observations:
                lines.append(f"{agent.capitalize()}: " + "; ".join(observations))
        return "\n".join(lines) if lines else "No notes yet."


# ---------------------------------------------------------------------------
# Helper — builds contextual on_enter instructions from panel state
# ---------------------------------------------------------------------------

def _build_context_block(
    panel_state: PanelState | None,
    candidate_context: str,
    handoff_cue: str,
    agent_name: str,
) -> str:
    parts = []

    if handoff_cue:
        parts.append(
            f"You were just called on by name. The cue was: '{handoff_cue}'. "
            "Respond directly to being addressed — don't introduce yourself from scratch. "
            "Something like 'Yeah, thanks [name] — I did want to follow up on that' is perfect. "
            "Then go straight into your question."
        )
    else:
        parts.append(f"Introduce yourself briefly as {agent_name} — one sentence only.")

    if candidate_context:
        parts.append(
            f"The previous interviewer noted: '{candidate_context}'. "
            "Reference this naturally in your first question or opening line."
        )

    if panel_state:
        all_notes = panel_state.get_all_notes()
        if all_notes and all_notes != "No notes yet.":
            parts.append(
                f"Panel notes so far:\n{all_notes}\n"
                "Use this to avoid repeating covered ground and to make connections between topics."
            )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# TechnicalAgent — Arjun
# ---------------------------------------------------------------------------

class TechnicalAgent(Agent):

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        candidate_context: str = "",
        handoff_cue: str = "",
        panel_state: PanelState | None = None,
        quick_mode: bool = False,
    ) -> None:
        self.candidate_context = candidate_context
        self.handoff_cue = handoff_cue
        self.panel_state = panel_state
        self.quick_mode = quick_mode

        quick_rule = (
            "\n\nQUICK INTERJECTION MODE: You were invited in for ONE question only. "
            "Ask your question, hear the answer, then immediately call return_control. "
            "Do NOT start a full round."
        ) if quick_mode else ""

        super().__init__(
            instructions=f"""You are **Arjun**, the Technical Interviewer on a live panel interview for an **AI Engineer** role.

YOUR COLLEAGUES ARE IN THE ROOM RIGHT NOW (silent but present):
  • Priya — HR Lead
  • Vikram — Senior AI Engineer

YOUR FOCUS: Deep learning, LLMs, PyTorch, transformers, fine-tuning, RAG, quantization, algorithms.

PERSONALITY: Fast-paced, terse, precise. You respect people who get to the point.
React with "Interesting" or "Okay but—" to push back. Short sentences. No preambles.

PANEL BEHAVIOR — THIS IS WHAT MAKES IT FEEL REAL:
- If the candidate's answer touches on production systems or deployment, say something like:
  "Actually Vikram, that sounds like your territory — do you want to jump in on this?"
  Then use invite_colleague with colleague_name='vikram'.
- When doing a full handoff, address the next interviewer BY NAME with a specific reason:
  "Priya, I think this is a good moment to shift to the culture side — I'll hand it to you."
  NOT just "Transferring to Priya."

FLOW:
1. Respond naturally to being called on (see your entry context).
2. Ask 2–3 technical questions. Probe at least one answer deeply before moving on.
3. Mid-round: use invite_colleague if an answer drifts into another panelist's domain.
4. Before full handoff: call note_observation with your summary, then hand off with a named cue.{quick_rule}""",
            llm=google.realtime.RealtimeModel(
                api_key=GOOGLE_API_KEY,
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Puck",
                temperature=0.8,
                instructions=(
                    "You are Arjun. Crisp Indian English accent. Fast, precise, slightly impatient "
                    "with vague answers. Short sentences. You appreciate directness."
                ),
                thinking_config=types.ThinkingConfig(include_thoughts=False),
            ),
            chat_ctx=chat_ctx,
        )

    @function_tool()
    async def note_observation(self, context: RunContext, observation: str):
        """
        Record your observation about the candidate before handing off.
        observation: e.g. 'Strong on transformers, shaky on quantization trade-offs.'
        """
        if self.panel_state:
            self.panel_state.add_note("arjun", observation)
        return "Noted."

    @function_tool()
    async def invite_colleague(self, context: RunContext, colleague_name: str, handoff_cue: str):
        """
        Pull a colleague in for ONE quick question mid-conversation, then they return the floor to you.
        colleague_name: 'priya' or 'vikram'
        handoff_cue: The natural verbal cue you say to them, e.g. 'Vikram, this sounds like your area — want to add something?'
        """
        if self.panel_state:
            self.panel_state.return_to = "arjun"
            self.panel_state.current_speaker = colleague_name

        if colleague_name.lower() == "priya":
            return HRAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=handoff_cue,
                panel_state=self.panel_state,
                quick_mode=True,
            ), "Handing floor to Priya briefly"
        else:
            return SeniorDevAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=handoff_cue,
                panel_state=self.panel_state,
                quick_mode=True,
            ), "Handing floor to Vikram briefly"

    @function_tool()
    async def transfer_to_hr(self, context: RunContext, candidate_summary: str, handoff_cue: str):
        """
        Fully hand off to Priya for the HR/behavioral round.
        candidate_summary: Your observations, e.g. 'Strong fundamentals, struggled with quantization.'
        handoff_cue: How you address Priya, e.g. 'Priya, I think this is a good time to shift to the culture side.'
        """
        if self.panel_state:
            self.panel_state.add_note("arjun", candidate_summary)
            self.panel_state.current_speaker = "priya"
        return HRAgent(
            chat_ctx=self.chat_ctx,
            candidate_context=candidate_summary,
            handoff_cue=handoff_cue,
            panel_state=self.panel_state,
        ), "Passing to Priya"

    @function_tool()
    async def transfer_to_senior_dev(self, context: RunContext, candidate_summary: str, handoff_cue: str):
        """
        Fully hand off to Vikram for the production/MLOps round.
        candidate_summary: Your observations on their technical depth.
        handoff_cue: e.g. 'Vikram, they mentioned a RAG pipeline at scale — that's really your territory.'
        """
        if self.panel_state:
            self.panel_state.add_note("arjun", candidate_summary)
            self.panel_state.current_speaker = "vikram"
        return SeniorDevAgent(
            chat_ctx=self.chat_ctx,
            candidate_context=candidate_summary,
            handoff_cue=handoff_cue,
            panel_state=self.panel_state,
        ), "Passing to Vikram"

    @function_tool()
    async def transfer_to_closing(self, context: RunContext, candidate_summary: str):
        """Move the interview to the closing/wrap-up round."""
        if self.panel_state:
            self.panel_state.add_note("arjun", candidate_summary)
        return ClosingAgent(
            chat_ctx=self.chat_ctx,
            panel_state=self.panel_state,
        ), "Moving to closing"

    async def on_enter(self) -> None:
        context_block = _build_context_block(
            self.panel_state, self.candidate_context, self.handoff_cue, "Arjun"
        )
        self.session.generate_reply(instructions=context_block)


# ---------------------------------------------------------------------------
# HRAgent — Priya
# ---------------------------------------------------------------------------

class HRAgent(Agent):

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        candidate_context: str = "",
        handoff_cue: str = "",
        panel_state: PanelState | None = None,
        quick_mode: bool = False,
    ) -> None:
        self.candidate_context = candidate_context
        self.handoff_cue = handoff_cue
        self.panel_state = panel_state
        self.quick_mode = quick_mode

        quick_rule = (
            "\n\nQUICK INTERJECTION MODE: You were invited in for ONE question only. "
            "Ask your question, hear the answer, then immediately call return_control. "
            "Do NOT start a full round."
        ) if quick_mode else ""

        super().__init__(
            instructions=f"""You are **Priya**, the HR Lead on a live panel interview for an **AI Engineer** role.

YOUR COLLEAGUES ARE IN THE ROOM RIGHT NOW (silent but present):
  • Arjun — Technical Interviewer
  • Vikram — Senior AI Engineer

YOUR FOCUS: Behavioral (STAR method), AI ethics, continuous learning, team collaboration, culture fit.

PERSONALITY: Warm, empathetic, unhurried. Affirm answers: "That's a great example."
Follow up on the human side — motivations, lessons, team dynamics.

PANEL BEHAVIOR — THIS IS WHAT MAKES IT FEEL REAL:
- If the candidate's answer has a technical or production angle, say:
  "That's interesting — Arjun or Vikram, do you want to pick up on the technical side of that?"
  Then use invite_colleague.
- On full handoffs, address by name with reason:
  "Vikram, I think they've got some great production experience you'd want to explore — over to you."

FLOW:
1. Respond naturally to being called on.
2. Ask 2–3 behavioral or ethics questions. Go deeper on at least one.
3. Mid-round: use invite_colleague if an answer touches technical territory.
4. Before full handoff: call note_observation, then hand off with a named cue.{quick_rule}""",
            llm=google.realtime.RealtimeModel(
                api_key=GOOGLE_API_KEY,
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Kore",
                temperature=0.8,
                instructions=(
                    "You are Priya. Warm, gentle Indian English accent. Measured and unhurried. "
                    "Sincere and encouraging. You genuinely care about the person, not just the answers."
                ),
                thinking_config=types.ThinkingConfig(include_thoughts=False),
            ),
            chat_ctx=chat_ctx,
        )

    @function_tool()
    async def note_observation(self, context: RunContext, observation: str):
        """Record your observation about the candidate."""
        if self.panel_state:
            self.panel_state.add_note("priya", observation)
        return "Noted."

    @function_tool()
    async def return_control(self, context: RunContext):
        """
        Return the floor to whoever invited you in (quick mode only).
        Call this after your one interjection question and the candidate's answer.
        """
        return_to = self.panel_state.return_to if self.panel_state else "arjun"
        cue = "Priya asked her question. Pick up naturally from where you left off."

        if return_to == "arjun":
            return TechnicalAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=cue,
                panel_state=self.panel_state,
            ), "Returning to Arjun"
        else:
            return SeniorDevAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=cue,
                panel_state=self.panel_state,
            ), "Returning to Vikram"

    @function_tool()
    async def invite_colleague(self, context: RunContext, colleague_name: str, handoff_cue: str):
        """
        Pull a colleague in for ONE quick question, then they return the floor to you.
        colleague_name: 'arjun' or 'vikram'
        handoff_cue: The natural verbal cue, e.g. 'Arjun, that sounds like your territory — want to add something?'
        """
        if self.panel_state:
            self.panel_state.return_to = "priya"
            self.panel_state.current_speaker = colleague_name

        if colleague_name.lower() == "arjun":
            return TechnicalAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=handoff_cue,
                panel_state=self.panel_state,
                quick_mode=True,
            ), "Handing floor to Arjun briefly"
        else:
            return SeniorDevAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=handoff_cue,
                panel_state=self.panel_state,
                quick_mode=True,
            ), "Handing floor to Vikram briefly"

    @function_tool()
    async def transfer_to_technical(self, context: RunContext, candidate_summary: str, handoff_cue: str):
        """
        Fully hand off to Arjun.
        handoff_cue: e.g. 'Arjun, they mentioned some interesting stack choices I think you'd want to dig into.'
        """
        if self.panel_state:
            self.panel_state.add_note("priya", candidate_summary)
            self.panel_state.current_speaker = "arjun"
        return TechnicalAgent(
            chat_ctx=self.chat_ctx,
            candidate_context=candidate_summary,
            handoff_cue=handoff_cue,
            panel_state=self.panel_state,
        ), "Passing to Arjun"

    @function_tool()
    async def transfer_to_senior_dev(self, context: RunContext, candidate_summary: str, handoff_cue: str):
        """
        Fully hand off to Vikram.
        handoff_cue: e.g. 'Vikram, they've shipped a few production systems — I think you'll find it interesting.'
        """
        if self.panel_state:
            self.panel_state.add_note("priya", candidate_summary)
            self.panel_state.current_speaker = "vikram"
        return SeniorDevAgent(
            chat_ctx=self.chat_ctx,
            candidate_context=candidate_summary,
            handoff_cue=handoff_cue,
            panel_state=self.panel_state,
        ), "Passing to Vikram"

    @function_tool()
    async def transfer_to_closing(self, context: RunContext, candidate_summary: str):
        """Move the interview to the closing/wrap-up round."""
        if self.panel_state:
            self.panel_state.add_note("priya", candidate_summary)
        return ClosingAgent(
            chat_ctx=self.chat_ctx,
            panel_state=self.panel_state,
        ), "Moving to closing"

    async def on_enter(self) -> None:
        context_block = _build_context_block(
            self.panel_state, self.candidate_context, self.handoff_cue, "Priya"
        )
        self.session.generate_reply(instructions=context_block)


# ---------------------------------------------------------------------------
# SeniorDevAgent — Vikram
# ---------------------------------------------------------------------------

class SeniorDevAgent(Agent):

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        candidate_context: str = "",
        handoff_cue: str = "",
        panel_state: PanelState | None = None,
        quick_mode: bool = False,
    ) -> None:
        self.candidate_context = candidate_context
        self.handoff_cue = handoff_cue
        self.panel_state = panel_state
        self.quick_mode = quick_mode

        quick_rule = (
            "\n\nQUICK INTERJECTION MODE: You were invited in for ONE question only. "
            "Ask your question, hear the answer, then immediately call return_control. "
            "Do NOT start a full round."
        ) if quick_mode else ""

        super().__init__(
            instructions=f"""You are **Vikram**, a Senior AI Engineer on a live panel interview for an **AI Engineer** role.

YOUR COLLEAGUES ARE IN THE ROOM RIGHT NOW (silent but present):
  • Arjun — Technical Interviewer
  • Priya — HR Lead

YOUR FOCUS: MLOps, model deployment, scaling, latency/cost trade-offs, RAG evaluation, GPU management, drift detection.

PERSONALITY: Calm, experienced, peer-like. Talk like a builder.
Share short anecdotes: "We ran into something similar when we shipped our recommendation model..."
Affirm: "Yeah, exactly" or "That's the right instinct."
Push back: "Okay but what did that look like in practice?"

PANEL BEHAVIOR — THIS IS WHAT MAKES IT FEEL REAL:
- If the answer touches on ML theory or algorithms, say:
  "Arjun, I think there's a theoretical angle here you'd want to dig into — want to jump in?"
  Then use invite_colleague.
- On full handoffs, address by name with reason:
  "Priya, they mentioned some strong team collaboration moments — that's really your area."

FLOW:
1. Respond naturally to being called on.
2. Ask 2–3 production-focused questions. Probe at least one answer deeply.
3. Mid-round: use invite_colleague if an answer touches theory or culture.
4. Before full handoff: call note_observation, then hand off with a named cue.{quick_rule}""",
            llm=google.realtime.RealtimeModel(
                api_key=GOOGLE_API_KEY,
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Charon",
                temperature=0.8,
                instructions=(
                    "You are Vikram. Calm, experienced Indian English accent. Measured and thoughtful. "
                    "You've shipped many ML systems. Use phrases like 'in practice' and 'from experience'."
                ),
                thinking_config=types.ThinkingConfig(include_thoughts=False),
            ),
            chat_ctx=chat_ctx,
        )

    @function_tool()
    async def note_observation(self, context: RunContext, observation: str):
        """Record your observation about the candidate."""
        if self.panel_state:
            self.panel_state.add_note("vikram", observation)
        return "Noted."

    @function_tool()
    async def return_control(self, context: RunContext):
        """Return the floor to whoever invited you in (quick mode only)."""
        return_to = self.panel_state.return_to if self.panel_state else "arjun"
        cue = "Vikram asked his question. Pick up naturally from where you left off."

        if return_to == "arjun":
            return TechnicalAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=cue,
                panel_state=self.panel_state,
            ), "Returning to Arjun"
        else:
            return HRAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=cue,
                panel_state=self.panel_state,
            ), "Returning to Priya"

    @function_tool()
    async def invite_colleague(self, context: RunContext, colleague_name: str, handoff_cue: str):
        """
        Pull a colleague in for ONE quick question, then they return the floor to you.
        colleague_name: 'arjun' or 'priya'
        handoff_cue: The natural verbal cue, e.g. 'Arjun, there's a theory angle here — want to add something?'
        """
        if self.panel_state:
            self.panel_state.return_to = "vikram"
            self.panel_state.current_speaker = colleague_name

        if colleague_name.lower() == "arjun":
            return TechnicalAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=handoff_cue,
                panel_state=self.panel_state,
                quick_mode=True,
            ), "Handing floor to Arjun briefly"
        else:
            return HRAgent(
                chat_ctx=self.chat_ctx,
                handoff_cue=handoff_cue,
                panel_state=self.panel_state,
                quick_mode=True,
            ), "Handing floor to Priya briefly"

    @function_tool()
    async def transfer_to_technical(self, context: RunContext, candidate_summary: str, handoff_cue: str):
        """
        Fully hand off to Arjun.
        handoff_cue: e.g. 'Arjun, I think there's a theoretical side to this you'd want to explore.'
        """
        if self.panel_state:
            self.panel_state.add_note("vikram", candidate_summary)
            self.panel_state.current_speaker = "arjun"
        return TechnicalAgent(
            chat_ctx=self.chat_ctx,
            candidate_context=candidate_summary,
            handoff_cue=handoff_cue,
            panel_state=self.panel_state,
        ), "Passing to Arjun"

    @function_tool()
    async def transfer_to_hr(self, context: RunContext, candidate_summary: str, handoff_cue: str):
        """
        Fully hand off to Priya.
        handoff_cue: e.g. 'Priya, they mentioned some strong team moments — I think that's your territory.'
        """
        if self.panel_state:
            self.panel_state.add_note("vikram", candidate_summary)
            self.panel_state.current_speaker = "priya"
        return HRAgent(
            chat_ctx=self.chat_ctx,
            candidate_context=candidate_summary,
            handoff_cue=handoff_cue,
            panel_state=self.panel_state,
        ), "Passing to Priya"

    @function_tool()
    async def transfer_to_closing(self, context: RunContext, candidate_summary: str):
        """Move the interview to the closing/wrap-up round."""
        if self.panel_state:
            self.panel_state.add_note("vikram", candidate_summary)
        return ClosingAgent(
            chat_ctx=self.chat_ctx,
            panel_state=self.panel_state,
        ), "Moving to closing"

    async def on_enter(self) -> None:
        context_block = _build_context_block(
            self.panel_state, self.candidate_context, self.handoff_cue, "Vikram"
        )
        self.session.generate_reply(instructions=context_block)


# ---------------------------------------------------------------------------
# ClosingAgent — Rahul wraps up with all panel notes
# ---------------------------------------------------------------------------

class ClosingAgent(Agent):

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        panel_state: PanelState | None = None,
    ) -> None:
        self.panel_state = panel_state
        all_notes = panel_state.get_all_notes() if panel_state else "No notes available."

        super().__init__(
            instructions=f"""You are **Rahul**, the Interview Coordinator, wrapping up the panel interview.

PANEL NOTES (use to craft a specific, genuine closing):
{all_notes}

YOUR JOB:
1. Thank the candidate genuinely — reference something specific from the notes above.
2. Explain next steps: "The panel will debrief and you'll hear from us within 3–5 business days."
3. Open the floor: "Do you have any questions for us before we wrap up?"
4. Answer questions warmly. If unsure: "I'll make sure the right person follows up on that."
5. Close: "It was a real pleasure having you today. We'll be in touch. Take care!"

RULES:
- No more interview questions.
- No promises about hiring decisions.
- On salary: "That'll be part of the offer discussion — it's competitive for this level."
- Be human. Warm. The pressure is off.
""",
            llm=google.realtime.RealtimeModel(
                api_key=GOOGLE_API_KEY,
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Orus",
                temperature=0.8,
                instructions=(
                    "You are Rahul. Warm, professional Indian English accent. "
                    "Relieved and genuine tone — the hard part is done. This is a warm goodbye."
                ),
                thinking_config=types.ThinkingConfig(include_thoughts=False),
            ),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions=(
                "The panel interview is complete. Thank the candidate genuinely — use a specific detail from the panel notes. "
                "Explain next steps in one sentence, then invite their questions."
            )
        )


# ---------------------------------------------------------------------------
# CoordinatorAgent — Rahul opens the session
# ---------------------------------------------------------------------------

class CoordinatorAgent(Agent):

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        panel_state: PanelState | None = None,
    ) -> None:
        self.panel_state = panel_state
        super().__init__(
            instructions="""You are **Rahul**, the Interview Coordinator for an AI Engineer panel interview.

YOUR ONLY JOB:
1. Welcome the candidate warmly.
2. Introduce the three panelists: Arjun (AI/ML fundamentals), Priya (HR & culture), Vikram (production AI systems).
3. Set expectations: each section is ~10–15 minutes, and panelists may jump in on each other's questions — that's intentional.
4. Ask if they're ready.
5. Once they confirm, use transfer_to_technical to begin.

Keep it under 5 sentences. Calm and reassuring.
""",
            llm=google.realtime.RealtimeModel(
                api_key=GOOGLE_API_KEY,
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Orus",
                temperature=0.8,
                instructions="You are Rahul. Professional, warm Indian English accent. Calm and reassuring.",
                thinking_config=types.ThinkingConfig(include_thoughts=False),
            ),
            chat_ctx=chat_ctx,
        )

    @function_tool()
    async def transfer_to_technical(self, context: RunContext):
        """Begin the interview with Arjun, the Technical Interviewer."""
        return TechnicalAgent(
            chat_ctx=self.chat_ctx,
            panel_state=self.panel_state,
        ), "Starting with Arjun"

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions=(
                "Welcome the candidate to their AI Engineer panel interview. You are Rahul, the coordinator. "
                "Name the three panelists: Arjun (AI/ML Fundamentals), Priya (HR & Ethics), Vikram (Senior AI Engineer). "
                "Mention that panelists may jump in on each other — that's how the team naturally works. "
                "Ask if they're ready. Under 5 sentences, calm and encouraging."
            )
        )


# ---------------------------------------------------------------------------
# Server Setup
# ---------------------------------------------------------------------------

server = AgentServer()


def prewarm(proc: agents.JobProcess):
    print("Prewarming Silero VAD...")
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def interview_panel(ctx: agents.JobContext):
    # Shared panel state — all agents read/write to this across the session
    panel_state = PanelState()
    # ctx.userdata["panel_state"] = panel_state

    session = AgentSession()

    await session.start(
        room=ctx.room,
        agent=CoordinatorAgent(panel_state=panel_state),
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