from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from nl2service.spec.models import EndpointSpec, ServiceSpec


class ProtoContractError(ValueError):
    pass


@dataclass(slots=True)
class ProtoMethod:
    name: str
    request_message: str
    response_message: str


@dataclass(slots=True)
class ProtoContract:
    source_path: Path
    contents: str
    package: str
    service_name: str
    methods: list[ProtoMethod]


class ServiceRenderer:
    def __init__(self) -> None:
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(default_for_string=False, disabled_extensions=("yaml", "go", "md", "tpl", "proto")),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["go_ident"] = self._go_identifier

    def inspect_contract(self, spec: ServiceSpec) -> ProtoContract:
        return self._load_proto_contract(spec)

    def render_tree(self, spec: ServiceSpec) -> dict[str, str]:
        trpc_enabled = bool(spec.service.enable_trpc)
        http_enabled = bool(spec.service.enable_http)
        contract = self._load_proto_contract(spec) if trpc_enabled else None
        context = self._build_context(spec, contract)
        files = {
            "go.mod": self._render("trpc-go/go.mod.tpl", context),
            "main.go": self._render("trpc-go/main.go.tpl", context),
            "trpc_go.yaml": self._render("trpc-go/trpc_go.yaml.tpl", context),
            "Dockerfile": self._render("trpc-go/Dockerfile.tpl", context),
            "build.sh": self._render("trpc-go/build.sh.tpl", context),
            "devops_build.sh": self._render("trpc-go/devops_build.sh.tpl", context),
            ".github/workflows/build-and-deploy.yaml": self._render("github-actions/build-and-deploy.yaml.j2", {"spec": spec}),
            "README.md": self._build_readme(spec, context),
        }
        if spec.deploy.enabled:
            files["k8s/deployment.yaml"] = self._render("k8s/deployment.yaml.j2", {"spec": spec})
            files["k8s/service.yaml"] = self._render("k8s/service.yaml.j2", {"spec": spec})
        if trpc_enabled and contract is not None:
            files["handler/handler.go"] = self._render("trpc-go/handler/handler.go.tpl", context)
            files[f"proto/{context['proto_output_name']}"] = contract.contents
            files["scripts/generate_stub.sh"] = self._render("trpc-go/scripts/generate_stub.sh.tpl", context)
            files["pb/README.md"] = self._render("trpc-go/pb/README.md.tpl", context)
        if http_enabled:
            files["handler/http_handler.go"] = self._render("trpc-go/handler/http_handler.go.tpl", context)
        if context["db_enabled"]:
            db_template = (
                "trpc-go/handler/postgres_handler.go.tpl"
                if context["db_type"] == "postgres"
                else "trpc-go/handler/db_handler.go.tpl"
            )
            files["handler/db_handler.go"] = self._render(db_template, context)
        if context["kafka_consumer_enabled"]:
            files["handler/kafka_consumer.go"] = self._render("trpc-go/handler/kafka_consumer.go.tpl", context)
        if context["kafka_producer_enabled"]:
            files["handler/kafka_producer.go"] = self._render("trpc-go/handler/kafka_producer.go.tpl", context)
        if context["kafka_enabled"]:
            files["handler/kafka_config.go"] = self._render("trpc-go/handler/kafka_config.go.tpl", context)
            files[".env.example"] = self._render("trpc-go/env.example.tpl", context)
            files[".gitignore"] = self._render("trpc-go/gitignore.tpl", context)
            ca_path = Path(str(spec.kafka.ca_file or ""))
            if not ca_path.is_absolute():
                ca_path = Path.cwd() / ca_path
            if not ca_path.is_file():
                bundled_ca = Path(__file__).parents[2] / "examples/minimal-trpc-kafka-event/ca.pem"
                ca_path = bundled_ca if bundled_ca.is_file() else ca_path
            if ca_path.is_file():
                files["ca.pem"] = ca_path.read_text(encoding="utf-8")
        if spec.deploy.enabled and spec.exposure.type == "ingress":
            files["k8s/ingress.yaml"] = self._render("k8s/ingress.yaml.j2", {"spec": spec})
        if spec.deploy.enabled and spec.exposure.type == "loadBalancer":
            files["k8s/service-lb.yaml"] = self._render("k8s/service-lb.yaml.j2", {"spec": spec})
        return files

    def write_tree(self, files: dict[str, str], out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for relative_path, content in files.items():
            destination = out_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

    def _render(self, template_name: str, context: dict[str, Any]) -> str:
        template = self.env.get_template(template_name)
        return template.render(**context)

    @staticmethod
    def _go_identifier(value: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", value)
        identifier = "".join(word[:1].upper() + word[1:] for word in words) or "Record"
        if identifier[0].isdigit():
            identifier = f"Record{identifier}"
        return identifier

    def _build_context(self, spec: ServiceSpec, contract: ProtoContract | None) -> dict[str, Any]:
        trpc_enabled = bool(spec.service.enable_trpc)
        http_enabled = bool(spec.service.enable_http)
        native_http_enabled = http_enabled and not trpc_enabled
        hybrid_http_enabled = http_enabled and trpc_enabled

        service_name = self._slug(spec.service.name or spec.repo.name or (contract.service_name if contract else None) or "service")
        owner = self._slug(spec.repo.owner or "team")
        repo_name = self._slug(spec.repo.name or service_name)
        module_path = (spec.service.module or f"github.com/{owner}/{repo_name}").strip()

        db_type = spec.database.type if spec.database.type in {"mysql", "postgres"} else None
        db_enabled = bool(spec.database.enabled and db_type)
        kafka_enabled = bool(spec.kafka.enabled)
        rpc_methods: list[dict[str, str]] = []
        for index, method in enumerate(contract.methods if contract else []):
            endpoint = spec.endpoints[index] if index < len(spec.endpoints) else None
            rpc_methods.append(
                {
                    "name": method.name,
                    "request_message": method.request_message,
                    "response_message": method.response_message,
                    "request_description": (endpoint.request_description if endpoint else None) or "Request payload defined by the provided .proto contract.",
                    "response_description": (endpoint.response_description if endpoint else None) or "Response payload defined by the provided .proto contract.",
                }
            )

        if native_http_enabled:
            http_apis = [self._native_http_api(endpoint, index) for index, endpoint in enumerate(spec.endpoints)]
        elif hybrid_http_enabled:
            http_apis = [
                self._http_api_from_endpoint(endpoint, rpc_method)
                for endpoint, rpc_method in zip(spec.endpoints, rpc_methods)
            ]
        else:
            http_apis = []

        normalized_name = service_name.replace("-", "_")
        handler_type_name = f"{contract.service_name}Handler" if contract else "HTTPHandler"
        service_prefix = f"trpc.{contract.package}" if contract else f"trpc.{owner}.{repo_name}"
        trpc_service_name = f"{service_prefix}.{contract.service_name}" if contract else f"{service_prefix}.service"
        http_service_name = f"{service_prefix}.http"
        primary_service_name = trpc_service_name if trpc_enabled else http_service_name

        return {
            "module_path": module_path,
            "group": owner,
            "app": repo_name,
            "server": service_name,
            "server_bin": service_name,
            "service_mode": spec.service.mode,
            "enable_trpc": trpc_enabled,
            "enable_http": http_enabled,
            "proto_package": contract.package if contract else None,
            "proto_output_name": contract.source_path.name if contract else None,
            "proto_source_path": str(contract.source_path) if contract else None,
            "rpc_enabled": bool(trpc_enabled and contract and contract.methods),
            "rpc_service_name": contract.service_name if contract else None,
            "rpc_methods": rpc_methods,
            "handler_type_name": handler_type_name,
            "trpc_service_name": trpc_service_name,
            "http_service_name": http_service_name,
            "primary_service_name": primary_service_name,
            "native_http_enabled": native_http_enabled,
            "http_enabled": bool(http_apis),
            "http_apis": http_apis,
            "http_port": 8080,
            "trpc_port": 9000,
            "health_path": spec.exposure.health_path,
            "db_enabled": db_enabled,
            "db_type": db_type or "mysql",
            "db_tables": [normalized_name],
            "db_service_name": (
                f"trpc.postgres.{owner}.{repo_name}"
                if db_type == "postgres"
                else f"{service_prefix}.mysql"
            ),
            "db_host": spec.database.host or "db.example.internal",
            "db_port": spec.database.port or (5432 if db_type == "postgres" else 3306),
            "db_name": spec.database.database or normalized_name,
            "db_user": normalized_name,
            "db_password_env": self._env_name(spec.database.secret_name or f"{service_name}_db_password"),
            "kafka_enabled": kafka_enabled,
            "kafka_consumer_enabled": kafka_enabled,
            "kafka_producer_enabled": kafka_enabled,
            "kafka_consumer_service_name": "trpc.kafka.consumer.service",
            "kafka_producer_service_name": "trpc.kafka.producer.service",
            "kafka_consumer_address": "kafka-consumer-config",
            "kafka_producer_address": "kafka-producer-config",
            "kafka_consumer_topic": spec.kafka.topic or f"{service_name}.topic",
            "kafka_consumer_group": spec.kafka.group or f"{service_name}-group",
            "kafka_producer_topic": spec.kafka.topic or f"{service_name}.topic",
            "kafka_producer_brokers": ",".join(spec.kafka.brokers) if spec.kafka.brokers else "localhost:9092",
        }

    def _build_readme(self, spec: ServiceSpec, context: dict[str, Any]) -> str:
        lines = [
            f"# {spec.service.name or context['server']}",
            "",
            "Generated by NL2Service using a public tRPC-Go scaffold plus a post-render LLM refinement stage.",
            "",
            "## Service Coordinates",
            f"- module: `{context['module_path']}`",
            f"- tRPC enabled: `{context['enable_trpc']}`",
            f"- HTTP enabled: `{context['enable_http']}`",
            f"- tRPC service: `{context['trpc_service_name']}`",
            f"- handler type: `{context['handler_type_name']}`",
            f"- service mode: `{spec.service.mode}`",
            "",
            "## Generated Assets",
            "",
            "## Exposure",
            f"- type: `{spec.exposure.type}`",
            f"- health path: `{spec.exposure.health_path}`",
        ]
        if context["rpc_enabled"]:
            lines[11:11] = [
                "## Contract",
                f"- source proto: `{context['proto_source_path']}`",
                f"- copied proto: `proto/{context['proto_output_name']}`",
                "",
            ]
            lines.append("- `handler/handler.go`: business implementation of the generated tRPC service interface")
        if context["native_http_enabled"]:
            lines.append("- `handler/http_handler.go`: native public tRPC-Go HTTP handlers; no protobuf bridge is required")
        elif context["http_enabled"]:
            lines.append("- `handler/http_handler.go`: HTTP bridge handlers backed by the generated tRPC service interface")
        if spec.exposure.host:
            lines.append(f"- host: `{spec.exposure.host}`")
        if context["kafka_enabled"]:
            lines.extend(
                [
                    "",
                    "## Kafka",
                    f"- topic: `{context['kafka_consumer_topic']}`",
                    f"- consumer group: `{context['kafka_consumer_group']}`",
                    "- copy `.env.example` to `.env` and inject the Kafka username and password at runtime",
                    "- save the provider CA certificate as `ca.pem` beside the Dockerfile before building",
                    "- Kafka configuration is registered under opaque addresses so credentials are not printed in startup logs",
                ]
            )
        lines.extend(
            [
                "",
                "## Notes",
                "- Pure tRPC mode requires `service.enable_trpc=true` and a user-provided `.proto` contract.",
                "- Pure HTTP mode sets `service.enable_http=true` and does not require a `.proto` contract.",
                "- Combined mode enables both transports and uses the `.proto` contract as the tRPC source of truth.",
                "- The generated Go code is aligned to the public `trpc-group/trpc-go` and `trpc-ecosystem/go-database` import space.",
                "- Build scripts generate pb stubs before `go build` when tRPC is enabled.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _load_proto_contract(self, spec: ServiceSpec) -> ProtoContract:
        proto_file = (spec.service.proto_file or "").strip()
        if not proto_file:
            raise ProtoContractError("service.proto_file is required for formal tRPC generation")
        source_path = Path(proto_file).expanduser()
        if not source_path.is_absolute():
            source_path = Path.cwd() / source_path
        if not source_path.exists():
            raise ProtoContractError(f"proto file not found: {source_path}")
        if source_path.suffix != ".proto":
            raise ProtoContractError(f"expected a .proto file, got: {source_path.name}")
        contents = source_path.read_text(encoding="utf-8")

        package_match = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", contents, re.MULTILINE)
        if not package_match:
            raise ProtoContractError("proto file must declare a package")
        package_name = package_match.group(1)

        service_match = re.search(r"service\s+(\w+)\s*\{(?P<body>[\s\S]*?)\}", contents, re.MULTILINE)
        if not service_match:
            raise ProtoContractError("proto file must contain at least one service definition")
        service_name = service_match.group(1)
        service_body = service_match.group("body")
        methods = [
            ProtoMethod(name=name, request_message=req, response_message=resp)
            for name, req, resp in re.findall(r"rpc\s+(\w+)\s*\(\s*(\w+)\s*\)\s+returns\s*\(\s*(\w+)\s*\)", service_body)
        ]
        if not methods:
            raise ProtoContractError("proto service must contain at least one rpc method")

        return ProtoContract(
            source_path=source_path,
            contents=contents,
            package=package_name,
            service_name=service_name,
            methods=methods,
        )

    def _http_api_from_endpoint(self, endpoint: EndpointSpec, rpc_method: dict[str, str]) -> dict[str, str]:
        return {
            "path": endpoint.path,
            "method": endpoint.method,
            "request_description": endpoint.request_description or "",
            "response_description": endpoint.response_description or "",
            "handler_name": rpc_method["name"],
            "rpc_name": rpc_method["name"],
            "request_message": rpc_method["request_message"],
            "response_message": rpc_method["response_message"],
        }

    def _native_http_api(self, endpoint: EndpointSpec, index: int) -> dict[str, str]:
        words = re.findall(r"[A-Za-z0-9]+", endpoint.path)
        path_name = "".join(word[:1].upper() + word[1:] for word in words)
        return {
            "path": endpoint.path,
            "method": endpoint.method,
            "request_description": endpoint.request_description or "JSON request body",
            "response_description": endpoint.response_description or "JSON response body",
            "handler_name": path_name or f"Endpoint{index + 1}",
        }

    def _slug(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_\-]+", "-", value.strip())
        normalized = normalized.strip("-_")
        return normalized or "service"

    def _env_name(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.upper())
        normalized = normalized.strip("_")
        return normalized or "SECRET_VALUE"
