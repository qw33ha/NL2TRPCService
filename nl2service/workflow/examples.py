from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nl2service.spec.models import ServiceSpec


@dataclass(frozen=True, slots=True)
class ExampleDefinition:
    name: str
    capability: str
    directory: str
    files: tuple[str, ...]


EXAMPLE_CATALOG = (
    ExampleDefinition(
        name="minimal-trpc-http-echo",
        capability="http",
        directory="minimal-trpc-http-echo",
        files=("main.go", "handler/http_handler.go", "handler/echo_handler.go", "trpc_go.yaml"),
    ),
    ExampleDefinition(
        name="minimal-trpc-mysql-user",
        capability="mysql",
        directory="minimal-trpc-mysql-user",
        files=("main.go", "handler/http_handler.go", "handler/db_handler.go", "trpc_go.yaml"),
    ),
    ExampleDefinition(
        name="minimal-trpc-kafka-event",
        capability="kafka",
        directory="minimal-trpc-kafka-event",
        files=(
            "main.go",
            "handler/http_handler.go",
            "handler/kafka_config.go",
            "handler/kafka_handler.go",
            "trpc_go.yaml",
            "Dockerfile",
        ),
    ),
)


@dataclass(slots=True)
class ExampleBundle:
    examples: list[str]
    files: dict[str, str]


class ExampleSelector:
    def __init__(self, examples_root: Path | None = None, max_characters: int = 80_000) -> None:
        self.examples_root = examples_root or Path(__file__).resolve().parents[2] / "examples"
        self.max_characters = max_characters

    def select(self, spec: ServiceSpec) -> ExampleBundle:
        capabilities = self._capabilities(spec)
        selected = [example for example in EXAMPLE_CATALOG if example.capability in capabilities]
        files: dict[str, str] = {}
        used = 0
        for example in selected:
            root = self.examples_root / example.directory
            for relative_path in example.files:
                source = root / relative_path
                if not source.is_file():
                    continue
                content = source.read_text(encoding="utf-8")
                if used + len(content) > self.max_characters:
                    break
                files[f"{example.name}/{relative_path}"] = content
                used += len(content)
        return ExampleBundle(examples=[example.name for example in selected], files=files)

    @staticmethod
    def _capabilities(spec: ServiceSpec) -> set[str]:
        capabilities: set[str] = set()
        if spec.service.enable_http or spec.service.enable_trpc:
            capabilities.add("http")
        if spec.database.enabled and spec.database.type == "mysql":
            capabilities.add("mysql")
        if spec.kafka.enabled:
            capabilities.add("kafka")
        return capabilities
