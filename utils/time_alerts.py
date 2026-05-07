import asyncio
import time as _time
import traceback
from livekit.agents import Agent

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
                "[1 MINUTE LEFT] Do NOT ask any more questions. "
                "Let the candidate finish their current answer. Do NOT transfer yet.",
                False,
            ))

        # 3. At last 30s
        if total_seconds >= 30:
            alerts.append((
                30,
                "[TIME IS UP] Your time is up. "
                "Speak your closing line now and transfer to the next agent.",
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
            if agent.session is None:
                print(f"[TIME ALERTS] Agent session is None for '{segment_name}', stopping timer.")
                return

            # Append system message to chat context
            print(f"[TIME ALERTS] [{segment_name}] {message}")
            agent.session.history.add_message(role="system", content=message)

            if force_reply:
                # Hard stop — make the agent speak and hand off immediately
                agent.session.generate_reply(instructions=message)

        # Grace period: 30s after the last alert, force handoff if still here
        await asyncio.sleep(30)
        if agent.session is not None:
            msg = (
                "⛔ GRACE PERIOD OVER. You MUST hand off RIGHT NOW. "
                "Say your closing line and call the transfer function immediately."
            )
            print(f"[TIME ALERTS] [{segment_name}] GRACE PERIOD — forcing handoff")
            agent.session.history.add_message(role="system", content=msg)
            agent.session.generate_reply(instructions=msg)

    except asyncio.CancelledError:
        print(f"[TIME ALERTS] Timer task for '{segment_name}' was cancelled.")
    except Exception as e:
        print(f"[TIME ALERTS] ERROR in timer for '{segment_name}': {e}")
        traceback.print_exc()
