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
    """Background task that fires generate_reply instructions at time thresholds."""
    try:
        total_minutes = time_limits.get(segment_name)
        if total_minutes is None:
            return

        total_seconds = total_minutes * 60
        start = _time.monotonic()

        alerts = []

        if total_seconds >= 120:
            alerts.append((
                120,
                "You have about 2 minutes left. "
                "Ask your LAST question now. Stay and listen to the candidate's answer.",
            ))

        if total_seconds >= 60:
            alerts.append((
                60,
                "Your time is almost up. Do NOT ask any more questions. "
                "Let the candidate finish what they're saying, "
                "then say a brief closing and transfer to the next panelist.",
            ))

        if total_seconds >= 30:
            alerts.append((
                30,
                "Your time is up. Stop talking. Say one short closing sentence "
                "and transfer to the next panelist. Nothing else.",
            ))

        valid_alerts = sorted(alerts, key=lambda x: x[0], reverse=True)

        for remaining_threshold, instruction in valid_alerts:
            elapsed = _time.monotonic() - start
            fire_at = total_seconds - remaining_threshold
            delay = fire_at - elapsed
            if delay > 0:
                await asyncio.sleep(delay)

            session = _get_session(agent)
            if session is None:
                print(f"[TIME ALERTS] Agent no longer active for '{segment_name}', stopping timer.")
                return

            print(f"[TIME ALERTS] [{segment_name}] {instruction}")
            session.generate_reply(instructions=instruction, allow_interruptions=True)

        # Grace period
        await asyncio.sleep(30)
        session = _get_session(agent)
        if session is not None:
            msg = "You have failed to transfer on time. Do NOT say anything else. Transfer NOW."
            print(f"[TIME ALERTS] [{segment_name}] GRACE PERIOD — forcing handoff")
            session.generate_reply(instructions=msg, allow_interruptions=True)

    except asyncio.CancelledError:
        print(f"[TIME ALERTS] Timer task for '{segment_name}' was cancelled.")
    except Exception as e:
        print(f"[TIME ALERTS] ERROR in timer for '{segment_name}': {e}")
        traceback.print_exc()
