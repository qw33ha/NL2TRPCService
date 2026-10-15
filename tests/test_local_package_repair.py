from nl2service.build.go_repair import DeterministicGoRepair
from nl2service.render.renderer import ServiceRenderer
import pytest


def test_misplaced_existing_package_is_relocated_without_synthesizing_code():
    files = {"go.mod": "module example.com/demo\n", "handler/main.go": "package handler\n",
             "handler/helpers.go": "package helpers\nfunc Value() int { return 1 }\n"}
    result = DeterministicGoRepair().apply(files, "cannot find module providing package example.com/demo/helpers:")
    assert result.changed and "handler/helpers.go" not in result.files
    assert result.files["helpers/helpers.go"] == files["handler/helpers.go"]
    external = DeterministicGoRepair().apply(files, "cannot find module providing package external.com/helpers:")
    assert not external.changed


def test_relocation_does_not_overwrite_or_move_embed_assets():
    files = {"go.mod": "module example.com/demo\n", "handler/main.go": "package handler\n",
             "handler/helpers.go": "package helpers\n", "helpers/helpers.go": "package helpers\n// existing\n"}
    message = "cannot find module providing package example.com/demo/helpers:"
    assert not DeterministicGoRepair().apply(files, message).changed
    del files["helpers/helpers.go"]
    files["handler/helpers.go"] += "//go:embed resource.txt\n"
    assert not DeterministicGoRepair().apply(files, message).changed


def test_generated_file_sync_keeps_user_changes(tmp_path):
    renderer = ServiceRenderer()
    previous = {"handler/helpers.go": "package helpers\n", "handler/edited.go": "old\n"}
    renderer.write_tree(previous, tmp_path)
    (tmp_path / "handler/edited.go").write_text("user change\n")
    renderer.write_tree({"helpers/helpers.go": previous["handler/helpers.go"]}, tmp_path, previous_files=previous)
    assert not (tmp_path / "handler/helpers.go").exists()
    assert (tmp_path / "handler/edited.go").read_text() == "user change\n"


def test_generated_relocation_refuses_unmanaged_target_collision(tmp_path):
    renderer = ServiceRenderer()
    previous = {"handler/helpers.go": "package helpers\n"}
    renderer.write_tree(previous, tmp_path)
    (tmp_path / "helpers").mkdir()
    target = tmp_path / "helpers/helpers.go"
    target.write_text("user-owned target\n")
    with pytest.raises(FileExistsError):
        renderer.write_tree({"helpers/helpers.go": previous["handler/helpers.go"]}, tmp_path, previous_files=previous)
    assert target.read_text() == "user-owned target\n"
    assert (tmp_path / "handler/helpers.go").exists()
