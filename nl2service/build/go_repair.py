from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import PurePosixPath


_UNUSED_IMPORT = re.compile(
    r'(?:vet:\s+)?\.?/?(?P<file>[^:\n]+\.go):\d+:\d+:\s+"(?P<import>[^"]+)" imported(?: as [A-Za-z_]\w*)? and not used'
)


@dataclass(slots=True)
class GoRepairResult:
    files: dict[str, str]
    changed: bool
    notes: list[str]


class DeterministicGoRepair:
    """Apply safe, mechanical fixes identified precisely by the Go toolchain."""

    def apply(self, files: dict[str, str], feedback: str) -> GoRepairResult:
        repaired = dict(files)
        notes: list[str] = []

        module_match = re.search(r"(?m)^\s*module\s+(\S+)", repaired.get("go.mod", ""))
        if module_match:
            module = module_match.group(1)
            for missing in set(re.findall(r"cannot find module providing package ([^\s:]+)", feedback)):
                if not missing.startswith(module + "/"):
                    continue
                relative = missing[len(module)+1:]
                parts = relative.split("/")
                if any(part in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
                    continue
                package = parts[-1]
                # Move only a misplaced package from a directory that already
                # contains a different package. Never synthesize missing code.
                declarations = {}
                for path, content in repaired.items():
                    if path.endswith(".go"):
                        cleaned = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/", "", content)
                        declaration = re.search(r"(?m)^\s*package\s+(\w+)\b", cleaned)
                        if declaration:
                            declarations[path] = declaration.group(1)
                moves = []
                for path, declared in declarations.items():
                    parent = PurePosixPath(path).parent
                    if declared != package or str(parent) == relative or "go:embed" in repaired[path]:
                        continue
                    if not any(PurePosixPath(other).parent == parent and value != package for other, value in declarations.items()):
                        continue
                    target = str(PurePosixPath(relative) / PurePosixPath(path).name)
                    moves.append((path, target))
                targets = [target for _, target in moves]
                if not moves or len(set(targets)) != len(targets) or any(target in repaired for target in targets):
                    continue
                for path, target in moves:
                    repaired[target] = repaired.pop(path)
                    notes.append(f"Relocated existing package {package} from {path} to {target} to satisfy local import {missing}.")

        if "not enough arguments in call to s.Close" in feedback and "want (chan struct{})" in feedback:
            for path, content in list(repaired.items()):
                if not path.endswith(".go") or "s.Close()" not in content:
                    continue
                updated = content.replace(
                    "if err := s.Close(); err != nil {",
                    "done := make(chan struct{})\n\tif err := s.Close(done); err != nil {",
                    1,
                )
                if updated != content:
                    repaired[path] = updated
                    notes.append(f"Passed the required completion channel to tRPC-Go Server.Close in {path}.")

        if "repository name must be lowercase" in feedback:
            for path, content in list(repaired.items()):
                if "github.repository" not in content or "docker build" not in content:
                    continue
                updated = re.sub(
                    r'(?m)^    env:\n      IMAGE: ghcr\.io/\$\{\{ github\.repository \}\}:\$\{\{ github\.sha \}\}\n',
                    "",
                    content,
                    count=1,
                )
                checkout = "      - uses: actions/checkout@v6\n"
                image_step = (
                    "      - name: Set lowercase container image\n"
                    '        run: echo "IMAGE=ghcr.io/${GITHUB_REPOSITORY,,}:$GITHUB_SHA" >> "$GITHUB_ENV"\n'
                )
                if updated != content and image_step not in updated:
                    docker_index = updated.find("\n  docker:\n")
                    if docker_index < 0:
                        continue
                    prefix, docker_section = updated[:docker_index], updated[docker_index:]
                    docker_section = docker_section.replace(checkout, checkout + image_step, 1)
                    updated = prefix + docker_section
                    repaired[path] = updated
                    notes.append(f"Normalized the GHCR image name to lowercase in {path}.")

        if "undefined: handler.RegisterKafkaConsumers" in feedback:
            for path, content in list(repaired.items()):
                if not path.endswith(".go") or "handler.RegisterKafkaConsumers(" not in content:
                    continue
                repaired[path] = content.replace(
                    "handler.RegisterKafkaConsumers(s)",
                    "trpckafka.RegisterKafkaConsumerService(s, handler.NewKafkaConsumer())",
                )
                notes.append(
                    f"Restored tRPC-Go Kafka consumer registration in {path}."
                )

        for match in _UNUSED_IMPORT.finditer(feedback):
            path = match.group("file").strip().replace("\\", "/").lstrip("./")
            import_path = match.group("import")
            actual_path = self._resolve_path(repaired, path)
            if actual_path is None:
                continue

            updated, count = re.subn(
                rf'(?m)^\s*(?:[._A-Za-z][\w.]*)?\s*"{re.escape(import_path)}"\s*\n',
                "",
                repaired[actual_path],
                count=1,
            )
            if count:
                repaired[actual_path] = updated
                notes.append(f'Removed unused import "{import_path}" from {actual_path}.')

        return GoRepairResult(files=repaired, changed=bool(notes), notes=notes)

    @staticmethod
    def _resolve_path(files: dict[str, str], reported_path: str) -> str | None:
        if reported_path in files:
            return reported_path
        matches = [path for path in files if path.replace("\\", "/").endswith(f"/{reported_path}")]
        return matches[0] if len(matches) == 1 else None
