from __future__ import annotations

from collections.abc import Callable
import time

from nl2service.agent.events import AgentTurn
from nl2service.agent.runtime import AgentSession


class GitHubActionsWorker:
    """Scheduler-friendly adapter that resumes external-wait interrupts."""

    def __init__(self, session: AgentSession, interval_seconds: float = 10.0) -> None:
        self.session = session
        self.interval_seconds = interval_seconds

    def tick(self, thread_id: str) -> AgentTurn:
        return self.session.resume_external(thread_id, {"type": "poll"})

    def run_until_terminal(
        self,
        thread_id: str,
        on_turn: Callable[[AgentTurn], None] | None = None,
        max_checks: int = 30,
    ) -> AgentTurn:
        turn = self.tick(thread_id)
        if on_turn:
            on_turn(turn)
        checks = 1
        while turn.waiting_for == "external_wait" and checks < max_checks:
            time.sleep(self.interval_seconds)
            turn = self.tick(thread_id)
            if on_turn:
                on_turn(turn)
            checks += 1
        return turn
