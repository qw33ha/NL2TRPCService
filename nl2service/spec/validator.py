from __future__ import annotations

from dataclasses import dataclass, field
import re

from nl2service.spec.models import ServiceSpec


@dataclass(slots=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"


@dataclass(slots=True)
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)


class ServiceSpecValidator:
    """Rule-based validation for required fields and unsafe settings."""

    def validate(self, spec: ServiceSpec, require_proto: bool = False) -> ValidationResult:
        result = ValidationResult()
        self._validate_service(spec, result, require_proto=require_proto)
        self._validate_endpoints(spec, result)
        self._validate_repo(spec, result)
        self._validate_deploy(spec, result)
        self._validate_exposure(spec, result)
        self._validate_kafka(spec, result)
        self._validate_database(spec, result)
        self._validate_policy(spec, result)
        return result

    def _validate_service(self, spec: ServiceSpec, result: ValidationResult, require_proto: bool = False) -> None:
        if not spec.service.name:
            result.issues.append(ValidationIssue("service.name", "Service name is required."))
        elif spec.deploy.enabled and not self._is_kubernetes_name(spec.service.name):
            result.issues.append(
                ValidationIssue(
                    "service.name",
                    "Service name must be a lowercase Kubernetes DNS label (for example, simple-service).",
                )
            )
        if not spec.service.module:
            result.issues.append(ValidationIssue("service.module", "Go module path is required."))
        if spec.service.runtime != "trpc-go":
            result.issues.append(ValidationIssue("service.runtime", "MVP currently supports only trpc-go runtime."))
        if not spec.service.enable_trpc and not spec.service.enable_http:
            result.issues.append(
                ValidationIssue(
                    "service.enable_trpc",
                    "At least one transport must be enabled: service.enable_trpc or service.enable_http.",
                )
            )
        if require_proto and spec.service.enable_trpc:
            if not spec.service.proto_file:
                result.issues.append(
                    ValidationIssue(
                        "service.proto_file",
                        "Formal tRPC generation requires a user-provided .proto contract file.",
                    )
                )
            elif not str(spec.service.proto_file).strip().endswith(".proto"):
                result.issues.append(
                    ValidationIssue(
                        "service.proto_file",
                        "The service.proto_file value must point to a .proto file.",
                    )
                )

    def _validate_endpoints(self, spec: ServiceSpec, result: ValidationResult) -> None:
        if not spec.endpoints:
            result.issues.append(ValidationIssue("endpoints", "At least one endpoint is required."))

    def _validate_repo(self, spec: ServiceSpec, result: ValidationResult) -> None:
        if not spec.repo.owner:
            result.issues.append(ValidationIssue("repo.owner", "GitHub owner is required."))
        if not spec.repo.name:
            result.issues.append(ValidationIssue("repo.name", "Repository name is required."))

    def _validate_deploy(self, spec: ServiceSpec, result: ValidationResult) -> None:
        if spec.deploy.enabled is None:
            result.issues.append(
                ValidationIssue("deploy.enabled", "Confirm whether an existing Kubernetes cluster is available.")
            )
            return
        if not spec.deploy.enabled:
            return
        if spec.deploy.platform is None:
            result.issues.append(
                ValidationIssue("deploy.platform", "Choose the Kubernetes platform before deployment rendering.")
            )
            return
        if not spec.deploy.namespace:
            result.issues.append(ValidationIssue("deploy.namespace", "Kubernetes namespace is required."))
        elif spec.deploy.namespace == "default":
            result.issues.append(
                ValidationIssue(
                    "deploy.namespace",
                    "Deployment to the shared default namespace is not allowed; use a dedicated namespace.",
                )
            )
        if spec.deploy.replicas < 1:
            result.issues.append(ValidationIssue("deploy.replicas", "Replicas must be at least 1."))
        if spec.deploy.platform == "gke":
            for field_name, value in {
                "deploy.gcp_project": spec.deploy.gcp_project,
                "deploy.cluster": spec.deploy.cluster,
                "deploy.location": spec.deploy.location,
            }.items():
                if not value:
                    result.issues.append(ValidationIssue(field_name, "GKE deployment configuration is incomplete."))
            if spec.deploy.gcp_project and not re.fullmatch(
                r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
                spec.deploy.gcp_project,
            ):
                result.issues.append(
                    ValidationIssue(
                        "deploy.gcp_project",
                        "Google Cloud project ID must be the literal lowercase ID, such as class-14848.",
                    )
                )
        elif not spec.deploy.kubeconfig_secret:
            result.issues.append(
                ValidationIssue("deploy.kubeconfig_secret", "The GitHub kubeconfig Secret name is required.")
            )

    def _validate_exposure(self, spec: ServiceSpec, result: ValidationResult) -> None:
        if not spec.deploy.enabled:
            return
        exposure = spec.exposure
        if exposure.type == "ingress" and not exposure.host:
            result.issues.append(ValidationIssue("exposure.host", "Ingress exposure requires a host."))
        if exposure.type == "ingress" and not exposure.ingress_class:
            result.issues.append(ValidationIssue("exposure.ingress_class", "Ingress exposure requires an ingress class."))
        if exposure.type == "loadBalancer" and not spec.policy.allow_load_balancer:
            result.issues.append(
                ValidationIssue("policy.allow_load_balancer", "LoadBalancer requires explicit policy approval.")
            )

    def _validate_kafka(self, spec: ServiceSpec, result: ValidationResult) -> None:
        kafka = spec.kafka
        if not kafka.enabled:
            return
        if not kafka.brokers:
            result.issues.append(ValidationIssue("kafka.brokers", "Kafka brokers are required when Kafka is enabled."))
        if not kafka.topic:
            result.issues.append(ValidationIssue("kafka.topic", "Kafka topic is required when Kafka is enabled."))
        if not kafka.group:
            result.issues.append(ValidationIssue("kafka.group", "Kafka consumer group is required when Kafka is enabled."))
        if not kafka.ca_file:
            result.issues.append(
                ValidationIssue("kafka.ca_file", "The TLS Kafka CA certificate file is required.")
            )
        if spec.deploy.enabled and not kafka.secret_name:
            result.issues.append(
                ValidationIssue("kafka.secret_name", "Kafka secret name is required when Kafka is enabled.")
            )
        elif spec.deploy.enabled and not self._is_kubernetes_name(kafka.secret_name):
            result.issues.append(
                ValidationIssue("kafka.secret_name", "Kafka Secret name must be a Kubernetes DNS label.")
            )

    def _validate_database(self, spec: ServiceSpec, result: ValidationResult) -> None:
        database = spec.database
        if not database.enabled:
            return
        missing_fields = {
            "database.type": database.type,
            "database.host": database.host,
            "database.port": database.port,
            "database.database": database.database,
        }
        if spec.deploy.enabled:
            missing_fields["database.secret_name"] = database.secret_name
        for field_name, value in missing_fields.items():
            if value in (None, "", []):
                result.issues.append(ValidationIssue(field_name, "Database configuration is incomplete."))
        if spec.deploy.enabled and database.secret_name and not self._is_kubernetes_name(database.secret_name):
            result.issues.append(
                ValidationIssue("database.secret_name", "Database Secret name must be a Kubernetes DNS label.")
            )

    @staticmethod
    def _is_kubernetes_name(value: str) -> bool:
        return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value)) and len(value) <= 253

    def _validate_policy(self, spec: ServiceSpec, result: ValidationResult) -> None:
        if spec.policy.store_plaintext_secrets:
            result.issues.append(
                ValidationIssue(
                    "policy.store_plaintext_secrets",
                    "Plaintext secret storage is forbidden.",
                )
            )

    def question_for_field(self, field_name: str) -> str | None:
        prompts = {
            "service.name": "What service name should we use? Kubernetes deployment names are normalized to lowercase kebab-case, for example simple-service.",
            "service.module": "What Go module path should we generate for this service?",
            "service.proto_file": "Please provide the path to the .proto file that defines the tRPC contract.",
            "service.enable_trpc": "Should this service expose tRPC, HTTP, or both? Set service.enable_trpc and service.enable_http accordingly.",
            "endpoints": "Which endpoints should the service expose? Describe each HTTP method and path.",
            "repo.owner": "Which GitHub owner or organization should host the repository?",
            "repo.name": "What repository name should we create?",
            "deploy.namespace": "Which Kubernetes namespace should we deploy into?",
            "deploy.enabled": "Do you already have a Kubernetes cluster available for deployment?",
            "deploy.platform": "Which Kubernetes platform are you deploying to: GKE or generic Kubernetes?",
            "deploy.kubeconfig_secret": "Which GitHub Actions Secret contains the Kubernetes kubeconfig?",
            "deploy.gcp_project": "What is the literal Google Cloud project ID? Enter the exact ID, for example class-14848.",
            "deploy.cluster": "What is the GKE cluster name?",
            "deploy.location": "Which region or zone contains the GKE cluster?",
            "policy.allow_load_balancer": "Do you approve creating a public LoadBalancer and its associated cloud cost?",
            "exposure.host": "Which external host should the ingress use?",
            "exposure.ingress_class": "Which ingress class should we target?",
            "kafka.brokers": "Which Kafka brokers should the service connect to?",
            "kafka.topic": "Which Kafka topic should the service use?",
            "kafka.group": "Which Kafka consumer group should the service run under?",
            "kafka.ca_file": "What project-relative path contains the Kafka CA certificate?",
            "kafka.secret_name": "Authenticated Kafka deployment requires a Kubernetes Secret for its credentials. What is its lowercase Secret name?",
            "database.type": "Which database type should we target: postgres or mysql?",
            "database.host": "Which database host should we connect to?",
            "database.port": "Which database port should we use?",
            "database.database": "What database name should the service use?",
            "database.secret_name": "Database deployment requires a Kubernetes Secret for its credentials. What is its lowercase Secret name?",
        }
        return prompts.get(field_name)
