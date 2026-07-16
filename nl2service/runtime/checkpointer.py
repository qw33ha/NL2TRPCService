from __future__ import annotations

from pathlib import Path
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


class SQLiteCheckpointRuntime:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".nl2service" / "agent.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        serializer = JsonPlusSerializer(
            allowed_msgpack_modules=[("nl2service.spec.models", "ServiceSpec")]
        )
        self.checkpointer = SqliteSaver(self.connection, serde=serializer)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteCheckpointRuntime":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
