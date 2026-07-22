from __future__ import annotations

from pathlib import Path

from nl2service.render.renderer import ServiceRenderer
from nl2service.spec.models import ServiceSpec


def _deployment_spec(mode: str, proto_file: Path | None = None) -> ServiceSpec:
    return ServiceSpec.model_validate(
        {
            "service": {
                "name": "regression-service",
                "module": "github.com/example/regression-service",
                "mode": mode,
                "proto_file": str(proto_file) if proto_file else None,
            },
            "endpoints": [{"path": "/events", "method": "POST"}],
            "database": {
                "enabled": True,
                "type": "mysql",
                "host": "db.example.internal",
                "port": 3306,
                "database": "events",
                "secret_name": "database-credentials",
            },
            "repo": {"owner": "example", "name": "regression-service"},
            "deploy": {
                "enabled": True,
                "platform": "gke",
                "gcp_project": "example-project",
                "cluster": "example-cluster",
                "location": "us-central1",
                "namespace": "regression",
            },
            "exposure": {"type": "loadBalancer"},
            "policy": {"allow_load_balancer": True},
        }
    )


def test_http_render_uses_health_probe_and_secret_references() -> None:
    files = ServiceRenderer().render_tree(_deployment_spec("http"))
    deployment = files["k8s/deployment.yaml"]

    assert "name: http" in deployment
    assert "containerPort: 8080" in deployment
    assert "path: /is_healthy" in deployment
    assert "secretKeyRef:" in deployment
    assert "name: database-credentials" in deployment
    assert "MYSQL_PASSWORD" in deployment
    assert "password:" not in deployment


def test_hybrid_service_exposes_http_and_trpc_ports(proto_file: Path) -> None:
    files = ServiceRenderer().render_tree(_deployment_spec("hybrid", proto_file))
    deployment = files["k8s/deployment.yaml"]
    service = files["k8s/service.yaml"]

    assert "containerPort: 8080" in deployment
    assert "containerPort: 9000" in deployment
    assert "name: http" in service
    assert "targetPort: 8080" in service
    assert "name: trpc" in service
    assert "targetPort: 9000" in service
