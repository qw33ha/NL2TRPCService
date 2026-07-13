from typing import Protocol


class ActionsProvider(Protocol):
    def wait_for_run(self, owner: str, repo: str) -> dict: ...
