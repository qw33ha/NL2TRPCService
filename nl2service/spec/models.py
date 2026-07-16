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


class EndpointSpec(BaseModel):
    path: str
    method: str
    request_description: str | None = None
    response_description: str | None = None

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


class DatabaseConfig(BaseModel):
    enabled: bool = False
    type: Literal["postgres", "mysql"] | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    table: str | None = None
    secret_name: str | None = None


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
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    repo: RepoConfig = Field(default_factory=RepoConfig)
    deploy: DeployConfig = Field(default_factory=DeployConfig)
    exposure: ExposureConfig = Field(default_factory=ExposureConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
