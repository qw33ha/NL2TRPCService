from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from nl2service.spec.defaults import (
    DEFAULT_EXPOSURE_TYPE,
    DEFAULT_HEALTH_PATH,
    DEFAULT_KUBECONFIG_SECRET,
    DEFAULT_REPLICAS,
    DEFAULT_RUNTIME,
    DEFAULT_SERVICE_MODE,
)


class ServiceConfig(BaseModel):
    name: str | None = None
    runtime: str = DEFAULT_RUNTIME
    mode: Literal["http", "rpc", "hybrid"] = DEFAULT_SERVICE_MODE
    enable_trpc: bool | None = None
    enable_http: bool | None = None
    module: str | None = None
    proto_file: str | None = None

    @model_validator(mode="after")
    def normalize_transports(self) -> "ServiceConfig":
        trpc_enabled = self.enable_trpc
        http_enabled = self.enable_http

        if trpc_enabled is None and http_enabled is None:
            if self.mode == "http":
                trpc_enabled = False
                http_enabled = True
            elif self.mode == "hybrid":
                trpc_enabled = True
                http_enabled = True
            else:
                trpc_enabled = True
                http_enabled = False
        else:
            trpc_enabled = bool(trpc_enabled) if trpc_enabled is not None else False
            http_enabled = bool(http_enabled) if http_enabled is not None else False

        if not trpc_enabled and not http_enabled:
            raise ValueError("At least one transport must be enabled: service.enable_trpc or service.enable_http.")

        self.enable_trpc = trpc_enabled
        self.enable_http = http_enabled
        if trpc_enabled and http_enabled:
            self.mode = "hybrid"
        elif http_enabled:
            self.mode = "http"
        else:
            self.mode = "rpc"
        return self


class InputFieldSpec(BaseModel):
    name: str = Field(description="JSON input field name explicitly stated by the user.")
    type: Literal["integer", "number", "string", "boolean", "object", "array"]
    required: bool | None = None
    minimum: float | None = None
    maximum: float | None = None
    description: str | None = None


class BusinessRuleSpec(BaseModel):
    name: str
    expression: str = Field(description="User-specified formula or rule; descriptive text, never executed as Python.")
    operations: list[Literal["add", "subtract", "multiply", "divide", "floor", "conditional", "other"]] = Field(default_factory=list)
    condition: str | None = None


class EndpointSpec(BaseModel):
    path: str
    method: str
    request_description: str | None = None
    response_description: str | None = None
    input_fields: list[InputFieldSpec] = Field(default_factory=list)
    business_rules: list[BusinessRuleSpec] = Field(default_factory=list)
    response_fields: list[str] = Field(default_factory=list)
    success_status: int | None = Field(default=None, ge=100, le=599)
    malformed_json_status: int | None = Field(default=None, ge=100, le=599)
    validation_error_status: int | None = Field(default=None, ge=100, le=599)
    error_field: str | None = None
    allow_unknown_fields: bool | None = None

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return value.upper()


class KafkaConfig(BaseModel):
    enabled: bool = False
    brokers: list[str] = Field(default_factory=list)
    topic: str | None = None
    group: str | None = None
    secret_name: str | None = None
    ca_file: str | None = None
    tls: bool | None = None


class RedisConfig(BaseModel):
    enabled: bool = False
    address: str | None = None
    key_prefix: str | None = None


class DatabaseColumnSpec(BaseModel):
    name: str
    sql_type: Literal["BIGINT", "INT", "VARCHAR(128)", "VARCHAR(255)", "TEXT"]
    primary_key: bool = False
    unique: bool = False
    nullable: bool = False


class DatabaseTableSpec(BaseModel):
    name: str
    columns: list[DatabaseColumnSpec] = Field(default_factory=list)


class DatabaseConfig(BaseModel):
    enabled: bool = False
    type: Literal["postgres", "mysql"] | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    table: str | None = None
    secret_name: str | None = None
    tables: list[DatabaseTableSpec] = Field(default_factory=list)
    transaction_requirements: list[str] = Field(default_factory=list)


class RepoConfig(BaseModel):
    owner: str | None = None
    name: str | None = None


class DeployConfig(BaseModel):
    enabled: bool | None = None
    platform: Literal["generic", "gke"] | None = None
    gcp_project: str | None = None
    cluster: str | None = None
    location: str | None = None
    namespace: str | None = None
    replicas: int = DEFAULT_REPLICAS
    kubeconfig_secret: str = DEFAULT_KUBECONFIG_SECRET


class ExposureConfig(BaseModel):
    type: Literal["clusterIP", "ingress", "loadBalancer"] = DEFAULT_EXPOSURE_TYPE
    host: str | None = None
    ingress_class: str | None = None
    health_path: str = DEFAULT_HEALTH_PATH


class PolicyConfig(BaseModel):
    allow_load_balancer: bool = False
    store_plaintext_secrets: bool = False
    require_gate: bool = True


class ServiceSpec(BaseModel):
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    endpoints: list[EndpointSpec] = Field(default_factory=list)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    repo: RepoConfig = Field(default_factory=RepoConfig)
    deploy: DeployConfig = Field(default_factory=DeployConfig)
    exposure: ExposureConfig = Field(default_factory=ExposureConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
