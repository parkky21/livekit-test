import asyncio
import time as _time
import traceback
from livekit.agents import Agent


def _get_session(agent: Agent):
    """Safely get the agent's session."""
    try:
        return agent.session
    except RuntimeError:
        return None


async def start_test_time_alerts(agent: Agent, total_minutes: int):
    """Background task for testing agent behavior with time-awareness instructions.
    
    Fires alerts at:
      - 1 minute left
      - 30 seconds left (force stop)
    """
    try:
        total_seconds = total_minutes * 60
        start = _time.monotonic()

        alerts = []

        if total_seconds >= 60:
            alerts.append((
                60,
                "[1 MINUTE LEFT] You have exactly 1 minute left. "
                "Inform the user that time is running out and they should wrap up their thoughts.",
                False,
            ))

        if total_seconds >= 30:
            alerts.append((
                30,
                "[30 SECONDS LEFT - STOP CONVERSATION] The time is up. "
                "Say a brief, polite goodbye and call the transfer function to transfer the conversation to the Second Test Agent immediately. "
                "Do NOT ask any further questions or allow the conversation to continue.",
                True,
            ))

        valid_alerts = sorted(alerts, key=lambda x: x[0], reverse=True)

        for remaining_threshold, message, force_reply in valid_alerts:
            elapsed = _time.monotonic() - start
            fire_at = total_seconds - remaining_threshold
            delay = fire_at - elapsed
            if delay > 0:
                await asyncio.sleep(delay)

            session = _get_session(agent)
            if session is None:
                print(f"[TEST TIME ALERTS] Agent no longer active, stopping timer.")
                return

            print(f"[TEST TIME ALERTS] {message}")
            session.history.add_message(role="system", content=message)

            if force_reply:
                session.generate_reply(instructions=message)

    except asyncio.CancelledError:
        print("[TEST TIME ALERTS] Timer task was cancelled.")
    except Exception as e:
        print(f"[TEST TIME ALERTS] ERROR in timer: {e}")
        traceback.print_exc()
