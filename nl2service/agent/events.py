from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EventKind = Literal[
    "message",
    "question",
    "approval",
    "progress",
    "external_wait",
    "completed",
    "error",
]


@dataclass(slots=True)
class AgentEvent:
    kind: EventKind
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentTurn:
    thread_id: str
    events: list[AgentEvent]
    status: str
    waiting_for: str | None = None
