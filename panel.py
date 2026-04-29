from livekit.agents import AgentSession
from dataclasses import dataclass

@dataclass
class PanelSessionInfo:
    panelists_count: int | None = None
    panelist_names: list[str] | None = None
    total_time_allocated: int | None = None
    time_per_panelist: int | None = None

