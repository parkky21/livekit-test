import asyncio
import time as _time
import traceback
from livekit.agents import Agent


def _get_session(agent: Agent):
    """Safely get the agent's session. Returns None if the agent has been swapped out."""
    try:
        return agent.session
    except RuntimeError:
        return None


async def _start_time_alerts(agent: Agent, segment_name: str, time_limits: dict):
    """Background task that injects time-awareness into the agent's chat context.

    Fires 3 alerts at specific remaining-time thresholds:
      - 2 min left  → "ask your last question" (silent ctx append)
      - 1 min left  → "stop asking, let user finish" (silent ctx append)
      - 30s left    → "time is up, close and transfer" (force reply)
    """
    try:
        total_minutes = time_limits.get(segment_name)
        if total_minutes is None:
            return  # host has no time limit

        total_seconds = total_minutes * 60
        start = _time.monotonic()

        # (remaining_seconds, message, force_reply)
        # force_reply=False → silent ctx append; True → generate_reply to force action
        alerts = []

        # 1. At 2 minutes left
        if total_seconds >= 120:
            alerts.append((
                120,
                "[2 MINUTES LEFT] You have 2 minutes remaining. "
                "Ask your LAST question now. Do NOT transfer yet — stay and listen to the candidate's answer.",
                False,
            ))

        # 2. At 1 minute left
        if total_seconds >= 60:
            alerts.append((
                60,
                "[1 MINUTE LEFT] Your questioning is OVER. "
                "Do NOT ask any more questions — not even a follow-up. "
                "Let the candidate finish their current answer, then say ONE short closing sentence "
                "and call the transfer function. Do NOT continue the conversation.",
                False,
            ))

        # 3. At last 30s — force reply with very explicit instructions
        if total_seconds >= 30:
            alerts.append((
                30,
                "[TIME IS UP — HARD STOP] Do NOT speak another question. "
                "Say ONLY: 'I think I've got a solid picture. [Next panelist name] — over to you.' "
                "Then IMMEDIATELY call the transfer function. Nothing else.",
                True,
            ))

        # Sort so highest-remaining triggers first
        valid_alerts = sorted(alerts, key=lambda x: x[0], reverse=True)

        for remaining_threshold, message, force_reply in valid_alerts:
            elapsed = _time.monotonic() - start
            fire_at = total_seconds - remaining_threshold
            delay = fire_at - elapsed
            if delay > 0:
                await asyncio.sleep(delay)

            # Agent may have already been swapped out — skip remaining alerts
            session = _get_session(agent)
            if session is None:
                print(f"[TIME ALERTS] Agent no longer active for '{segment_name}', stopping timer.")
                return

            # Append system message to chat context
            print(f"[TIME ALERTS] [{segment_name}] {message}")
            session.history.add_message(role="system", content=message)

            if force_reply:
                # Hard stop — make the agent speak and hand off immediately
                session.generate_reply(instructions=message)

        # Grace period: 30s after the last alert, force handoff if still here
        await asyncio.sleep(30)
        session = _get_session(agent)
        if session is not None:
            msg = (
                "⛔ FINAL WARNING. You have FAILED to transfer on time. "
                "Do NOT say anything else to the candidate. "
                "Call the transfer function NOW. This is not optional."
            )
            print(f"[TIME ALERTS] [{segment_name}] GRACE PERIOD — forcing handoff")
            session.history.add_message(role="system", content=msg)
            session.generate_reply(instructions=msg)

    except asyncio.CancelledError:
        print(f"[TIME ALERTS] Timer task for '{segment_name}' was cancelled.")
    except Exception as e:
        print(f"[TIME ALERTS] ERROR in timer for '{segment_name}': {e}")
        traceback.print_exc()
