from unittest.mock import Mock

import pytest

from nl2service.tools.github_tool import GitHubAPIError, GitHubApiProvider


@pytest.mark.parametrize('owner,endpoint', [('qw33ha', '/user/repos'), ('team', '/orgs/team/repos')])
def test_repo_creation_uses_requested_owner_and_preserves_actual_error(owner, endpoint):
    provider = GitHubApiProvider(token='test-only')
    provider._request_json = Mock(side_effect=[
        GitHubAPIError('GitHub API request failed (404)'),
        {'login': 'qw33ha'},
        GitHubAPIError('GitHub API request failed (403): Resource not accessible by personal access token'),
    ])
    with pytest.raises(GitHubAPIError, match='403.*Resource not accessible'):
        provider.create_repo(owner, 'demo')
    assert provider._request_json.call_args.args[:2] == ('POST', endpoint)
    assert provider._request_json.call_count == 3
