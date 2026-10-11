import pytest

from nl2service.evaluation.remote_ci import WORKFLOW, WORKFLOW_PATH, guard_workflows, validate_target


@pytest.mark.parametrize("branch", ["main", "feature/test", "evaluation/cicd-../main", "evaluation/cicd-test main"])
def test_remote_ci_refuses_unisolated_branch(branch):
    with pytest.raises(ValueError):
        validate_target("qw33ha/simpleService", branch)


@pytest.mark.parametrize("repository", ["https://github.com/owner/repo", "owner/repo?other", "owner/..", "owner"])
def test_remote_ci_refuses_ambiguous_repository(repository):
    with pytest.raises(ValueError):
        validate_target(repository, "evaluation/cicd-test")


def test_remote_ci_rejects_modified_or_extra_workflows():
    validate_target("qw33ha/simpleService", "evaluation/cicd-test")
    guard_workflows({WORKFLOW_PATH: WORKFLOW})
    with pytest.raises(ValueError):
        guard_workflows({WORKFLOW_PATH: WORKFLOW + "\n# change"})
    with pytest.raises(ValueError):
        guard_workflows({WORKFLOW_PATH: WORKFLOW, ".github/workflows/deploy.yaml": "deploy"})
