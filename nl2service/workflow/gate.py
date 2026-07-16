from __future__ import annotations

from dataclasses import dataclass

from nl2service.spec.models import ServiceSpec


@dataclass(slots=True)
class GateSummary:
    actions: list[str]
    warnings: list[str]
    confirmations: list[str]

    def to_lines(self) -> list[str]:
        return self.actions + self.warnings + self.confirmations


class GateSummaryBuilder:
    def build(self, spec: ServiceSpec) -> GateSummary:
        actions = [
            f"Create repository {spec.repo.owner}/{spec.repo.name}",
            "Commit generated application and workflow",
        ]
        if spec.deploy.enabled:
            actions.extend([
                "Commit Kubernetes manifests",
                f"Deploy to namespace {spec.deploy.namespace} with {spec.deploy.replicas} replica(s)",
                f"Expose service via {spec.exposure.type}",
            ])
        else:
            actions.append("Build and publish the container image; skip Kubernetes deployment")
        warnings = [
            "Agent will not create databases, Kafka clusters, or Kubernetes clusters",
            "Agent will not store plaintext credentials in spec or generated files",
        ]
        if spec.kafka.enabled:
            warnings.append(f"Kafka dependency: topic={spec.kafka.topic}, secret={spec.kafka.secret_name}")
        if spec.database.enabled:
            warnings.append(f"Database dependency: type={spec.database.type}, secret={spec.database.secret_name}")
        if spec.exposure.type == "loadBalancer":
            warnings.append("LoadBalancer incurs extra cost and requires explicit confirmation")
        confirmations = [
            "Confirm GitHub repository creation",
            "Confirm workflow execution and container publish",
        ]
        if spec.deploy.enabled:
            confirmations.append("Confirm Kubernetes deployment and rollout verification")
        return GateSummary(actions=actions, warnings=warnings, confirmations=confirmations)
