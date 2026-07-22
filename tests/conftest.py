from __future__ import annotations

from pathlib import Path

import pytest

from nl2service.spec.models import ServiceSpec


@pytest.fixture
def http_spec() -> ServiceSpec:
    return ServiceSpec.model_validate(
        {
            "service": {
                "name": "regression-service",
                "module": "github.com/example/regression-service",
                "mode": "http",
            },
            "endpoints": [{"path": "/events", "method": "post"}],
            "repo": {"owner": "example", "name": "regression-service"},
            "deploy": {"enabled": False},
        }
    )


@pytest.fixture
def proto_file(tmp_path: Path) -> Path:
    path = tmp_path / "echo.proto"
    path.write_text(
        '''syntax = "proto3";
package trpc.example.echo;
service EchoService {
  rpc Echo(EchoRequest) returns (EchoResponse);
}
message EchoRequest { string message = 1; }
message EchoResponse { string message = 1; }
''',
        encoding="utf-8",
    )
    return path
