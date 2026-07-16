from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil
import subprocess
import tempfile


@dataclass(slots=True)
class BuildVerificationResult:
    success: bool
    summary_lines: list[str] = field(default_factory=list)
    feedback: str = ""
    command: str | None = None
    exit_code: int | None = None
    synchronized_files: dict[str, str] = field(default_factory=dict)


class GoBuildVerifier:
    def verify(self, files: dict[str, str]) -> BuildVerificationResult:
        go_bin = shutil.which("go")
        if not go_bin:
            message = "Go toolchain not found in PATH; cannot run go vet/go build verification."
            return BuildVerificationResult(success=False, summary_lines=[message], feedback=message)

        proto_name = self._find_proto_file(files)
        trpc_bin = shutil.which("trpc") if proto_name else None
        if proto_name and not trpc_bin:
            message = "trpc command not found in PATH; cannot generate pb stubs before build verification."
            return BuildVerificationResult(success=False, summary_lines=[message], feedback=message)

        with tempfile.TemporaryDirectory(prefix="nl2service-build-") as tmp_dir:
            root = Path(tmp_dir)
            self._write_tree(files, root)
            commands: list[list[str]] = []
            if proto_name and trpc_bin:
                commands.append(
                    [
                        trpc_bin,
                        "create",
                        "-p",
                        f"proto/{proto_name}",
                        "-o",
                        "pb",
                        "--rpconly",
                        "--mock=false",
                        "--nogomod=true",
                        "-f",
                    ]
                )
            commands.extend(
                [
                    [go_bin, "mod", "tidy"],
                    [go_bin, "vet", "./..."],
                    [go_bin, "build", "./..."],
                ]
            )

            env = os.environ.copy()
            env.setdefault("GO111MODULE", "on")
            completed: list[tuple[list[str], subprocess.CompletedProcess[str]]] = []
            for command in commands:
                result = subprocess.run(
                    command,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                )
                completed.append((command, result))
                if result.returncode != 0:
                    return self._failure_result(
                        command,
                        result,
                        completed,
                        self._synchronize_module_files(files, root),
                    )

            synchronized_files = self._synchronize_module_files(files, root)

        summary_lines = [
            "Build verification succeeded.",
            "Commands passed: trpc create (if needed), go mod tidy, go vet ./..., go build ./...",
        ]
        return BuildVerificationResult(
            success=True,
            summary_lines=summary_lines,
            feedback="Build verification succeeded.",
            command="go build ./...",
            exit_code=0,
            synchronized_files=synchronized_files,
        )

    @staticmethod
    def _synchronize_module_files(files: dict[str, str], root: Path) -> dict[str, str]:
        synchronized = dict(files)
        for name in ("go.mod", "go.sum"):
            path = root / name
            if path.is_file():
                synchronized[name] = path.read_text(encoding="utf-8")
        return synchronized

    def _find_proto_file(self, files: dict[str, str]) -> str | None:
        for path in files:
            normalized = path.replace("\\", "/")
            if normalized.startswith("proto/") and normalized.endswith(".proto"):
                return Path(normalized).name
        return None

    def _write_tree(self, files: dict[str, str], out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for relative_path, content in files.items():
            destination = out_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

    def _failure_result(
        self,
        failed_command: list[str],
        failed_result: subprocess.CompletedProcess[str],
        completed: list[tuple[list[str], subprocess.CompletedProcess[str]]],
        synchronized_files: dict[str, str],
    ) -> BuildVerificationResult:
        command_text = " ".join(failed_command)
        summary_lines = [
            f"Build verification failed on: {command_text}",
        ]
        stderr_text = failed_result.stderr.strip()
        stdout_text = failed_result.stdout.strip()
        if stderr_text:
            summary_lines.append(stderr_text.splitlines()[-1])
        elif stdout_text:
            summary_lines.append(stdout_text.splitlines()[-1])

        blocks: list[str] = [
            "The generated Go project failed local verification.",
            "Fix the code so the following commands succeed in order:",
        ]
        for command, result in completed:
            blocks.append(f"COMMAND: {' '.join(command)}")
            if result.stdout.strip():
                blocks.append("STDOUT:")
                blocks.append(result.stdout.strip())
            if result.stderr.strip():
                blocks.append("STDERR:")
                blocks.append(result.stderr.strip())
            blocks.append(f"EXIT CODE: {result.returncode}")
        feedback = "\n".join(blocks)
        return BuildVerificationResult(
            success=False,
            summary_lines=summary_lines,
            feedback=feedback,
            command=command_text,
            exit_code=failed_result.returncode,
            synchronized_files=synchronized_files,
        )
