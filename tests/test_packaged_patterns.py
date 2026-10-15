"""Check the actual packaged retrieval helpers without a standalone example project."""
from pathlib import Path
import shutil
import subprocess

import pytest

from nl2service.workflow.retrieval import HybridExampleSelector


def test_constraint_patterns_do_not_depend_on_examples_directory(tmp_path):
    selector = HybridExampleSelector(mode='bm25', examples_root=tmp_path)
    chunks = selector.corpus()
    assert len(chunks) == 3
    assert all(chunk.constraint_tags and chunk.content for chunk in chunks)


@pytest.mark.parametrize('command', [('test', './...'), ('vet', './...'), ('build', './...')])
def test_retrieval_go_helpers(command, tmp_path):
    go = shutil.which('go')
    if not go:
        pytest.skip('Go is required for executable helper checks')
    root = Path(__file__).parents[1]
    for source in (root/'nl2service/knowledge/patterns').glob('*.go'):
        shutil.copyfile(source, tmp_path/source.name)
    shutil.copyfile(root/'tests/fixtures/retrieval_patterns_test.go', tmp_path/'patterns_test.go')
    (tmp_path/'go.mod').write_text('module example.com/retrieval-patterns\n\ngo 1.22\n')
    result = subprocess.run([go, *command], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
