from pathlib import Path

import pytest
import yaml

from nl2service.build.verify import BuildVerificationResult
from nl2service.evaluation.cicd import SCENARIOS, run_scenario
from nl2service.evaluation.runner import load_tasks
from nl2service.render.renderer import ServiceRenderer
from nl2service.spec.models import ServiceSpec
from nl2service.tools.github_tool import WorkflowRunRef
from nl2service.workflow.nodes.delivery import GitHubActionsNodes


def seed():
    task = load_tasks(Path("nl2service/evaluation/tasks-v1.jsonl"))[0]
    spec = ServiceSpec.model_validate(task.spec)
    return ServiceRenderer().render_tree(spec), spec


class PassedVerifier:
    def verify(self, files):
        return BuildVerificationResult(success=True, synchronized_files=files)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
def test_real_delivery_graph_scenario(scenario):
    files, spec = seed()
    result = run_scenario(scenario, files, spec, verifier=PassedVerifier())
    assert result["passed"], result
    if scenario["id"] == "ci-wait-success":
        assert result["polls"] == 2
        assert result["checkpoint_restarts"] == 2


@pytest.mark.parametrize("sha", [None, "unrelated-commit"])
def test_monitor_rejects_wrong_run_identity(sha):
    class Provider:
        def get_workflow_run_for_commit(self, *args):
            return WorkflowRunRef("run", "completed", "success", sha)
    result = GitHubActionsNodes(Provider()).monitor({"github_delivery": {"owner": "owner", "repo": "repo", "commit_sha": "expected"}})
    assert result["status"] == "error"
    assert "commit SHA" in result["error"]


def test_missing_commit_is_not_recovered_from_an_unrelated_latest_run():
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError("Missing commit must fail before any API call")
    result = GitHubActionsNodes(Forbidden()).monitor({"github_delivery": {"owner": "owner", "repo": "repo"}})
    assert result["status"] == "error"


@pytest.mark.parametrize("conclusion", ["cancelled", "timed_out", "skipped", "neutral"])
def test_non_failure_conclusions_do_not_trigger_code_repair(conclusion):
    class Provider:
        def get_workflow_run_for_commit(self, *args):
            return WorkflowRunRef("run", "completed", conclusion, "sha")
    result = GitHubActionsNodes(Provider()).monitor({"github_delivery": {"owner": "owner", "repo": "repo", "commit_sha": "sha"}})
    assert result["status"] == "error"
    assert GitHubActionsNodes.route(result) == "end"


def test_generated_pipeline_has_ordered_build_publish_deploy_stages():
    files, spec = seed()
    workflow_path = ".github/workflows/build-and-deploy.yaml"
    jobs = yaml.load(files[workflow_path], Loader=yaml.BaseLoader)["jobs"]
    assert "deploy" not in jobs
    assert jobs["docker"]["needs"] == "build"
    assert any(step.get("run") == "go test ./..." for step in jobs["build"]["steps"])
    spec.deploy.enabled = True
    spec.deploy.platform = "generic"
    spec.deploy.namespace = "evaluation"
    files = ServiceRenderer().render_tree(spec)
    jobs = yaml.load(files[workflow_path], Loader=yaml.BaseLoader)["jobs"]
    assert jobs["deploy"]["needs"] == "docker"
    commands = "\n".join(step.get("run", "") for step in jobs["deploy"]["steps"])
    assert "kubectl rollout status" in commands
    assert "missing or empty" in commands


@pytest.mark.parametrize("diagnostic", ["permission denied on resource project", "Error from server (Forbidden)", "Unauthorized"])
def test_cloud_access_failure_is_not_sent_to_code_repair(diagnostic):
    from nl2service.tools.github_tool import WorkflowJobRef
    class Provider:
        def get_workflow_run_for_commit(self, *args):
            return WorkflowRunRef("run", "completed", "failure", "sha")
        def get_workflow_jobs(self, *args):
            return [WorkflowJobRef("job", "deploy", "completed", "failure")]
        def get_workflow_logs(self, *args):
            return diagnostic
    result = GitHubActionsNodes(Provider()).monitor({"github_delivery": {"owner": "owner", "repo": "repo", "commit_sha": "sha"}})
    assert result["active_failure"]["source"] == "deployment"
    assert "external access" in result["error"]
    assert GitHubActionsNodes.route(result) == "end"
