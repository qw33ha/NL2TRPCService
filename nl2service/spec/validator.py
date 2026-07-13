from __future__ import annotations

from dataclasses import dataclass, field

from nl2service.spec.models import ServiceSpec


@dataclass(slots=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"


@dataclass(slots=True)
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


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

    def clarification_questions(self, spec: ServiceSpec, require_proto: bool = False) -> list[str]:
        result = self.validate(spec, require_proto=require_proto)
        questions: list[str] = []
        for issue in result.issues:
            if issue.severity != "error":
                continue
            question = self.question_for_field(issue.field)
            if question:
                questions.append(question)
        return questions

    def _validate_service(self, spec: ServiceSpec, result: ValidationResult, require_proto: bool = False) -> None:
        if not spec.service.name:
            result.issues.append(ValidationIssue("service.name", "Service name is required."))
        if not spec.service.module:
            result.issues.append(ValidationIssue("service.module", "Go module path is required."))
        if spec.service.runtime != "trpc-go":
            result.issues.append(ValidationIssue("service.runtime", "MVP currently supports only trpc-go runtime."))
        if require_proto:
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
        if not spec.deploy.namespace:
            result.issues.append(ValidationIssue("deploy.namespace", "Kubernetes namespace is required."))
        if spec.deploy.replicas < 1:
            result.issues.append(ValidationIssue("deploy.replicas", "Replicas must be at least 1."))

    def _validate_exposure(self, spec: ServiceSpec, result: ValidationResult) -> None:
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
        if not kafka.secret_name:
            result.issues.append(
                ValidationIssue("kafka.secret_name", "Kafka secret name is required when Kafka is enabled.")
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
            "database.secret_name": database.secret_name,
        }
        for field_name, value in missing_fields.items():
            if value in (None, "", []):
                result.issues.append(ValidationIssue(field_name, "Database configuration is incomplete."))

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
            "service.name": "What service name should we use?",
            "service.module": "What Go module path should we generate for this service?",
            "service.proto_file": "Please provide the path to the .proto file that defines the tRPC contract.",
            "repo.owner": "Which GitHub owner or organization should host the repository?",
            "repo.name": "What repository name should we create?",
            "deploy.namespace": "Which Kubernetes namespace should we deploy into?",
            "exposure.host": "Which external host should the ingress use?",
            "exposure.ingress_class": "Which ingress class should we target?",
            "kafka.brokers": "Which Kafka brokers should the service connect to?",
            "kafka.topic": "Which Kafka topic should the service use?",
            "kafka.group": "Which Kafka consumer group should the service run under?",
            "kafka.secret_name": "Which Kubernetes Secret contains the Kafka credentials?",
            "database.type": "Which database type should we target: postgres, mysql, or redis?",
            "database.host": "Which database host should we connect to?",
            "database.port": "Which database port should we use?",
            "database.database": "What database name should the service use?",
            "database.secret_name": "Which Kubernetes Secret contains the database credentials?",
        }
        return prompts.get(field_name)
