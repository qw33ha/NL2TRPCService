from __future__ import annotations

import json
from pathlib import Path

import pytest

from nl2service.build.go_repair import DeterministicGoRepair


FAILURE_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "failures.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FAILURE_CASES, ids=lambda case: case["name"])
def test_known_go_failure_is_repaired(case: dict[str, str]) -> None:
    result = DeterministicGoRepair().apply(
        {case["path"]: case["content"]},
        case["feedback"],
    )

    assert result.changed is True
    repaired = result.files[case["path"]]
    assert case["expected_contains"] in repaired
    assert case["expected_absent"] not in repaired


def test_unknown_failure_does_not_modify_files() -> None:
    files = {"main.go": "package main\nfunc main() {}\n"}

    result = DeterministicGoRepair().apply(files, "unknown compiler failure")

    assert result.changed is False
    assert result.files == files


def test_windows_vet_aliased_unused_import_is_removed_precisely():
    files={'service.go':'package main\nimport (\n trpcmysql "trpc.group/trpc-go/trpc-database/mysql"\n "encoding/json"\n)\nfunc main() {}\n'}
    result=DeterministicGoRepair().apply(files,'vet.exe: .\\service.go:3:2: "trpc.group/trpc-go/trpc-database/mysql" imported as trpcmysql and not used')
    assert result.changed
    assert 'trpcmysql "' not in result.files['service.go']
    assert '"encoding/json"' in result.files['service.go']
