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

    def inspect_contract(self, spec: ServiceSpec) -> ProtoContract:
        return self._load_proto_contract(spec)

    def render_tree(self, spec: ServiceSpec) -> dict[str, str]:
        contract = self._load_proto_contract(spec)
        context = self._build_context(spec, contract)
        files = {
            "go.mod": self._render("trpc-go/go.mod.tpl", context),
            "main.go": self._render("trpc-go/main.go.tpl", context),
            "trpc_go.yaml": self._render("trpc-go/trpc_go.yaml.tpl", context),
            "Dockerfile": self._render("trpc-go/Dockerfile.tpl", context),
            "build.sh": self._render("trpc-go/build.sh.tpl", context),
            "devops_build.sh": self._render("trpc-go/devops_build.sh.tpl", context),
            "start.sh": self._render("trpc-go/start.sh.tpl", context),
            "handler/handler.go": self._render("trpc-go/handler/handler.go.tpl", context),
            f"proto/{context['proto_output_name']}": contract.contents,
            "scripts/generate_stub.sh": self._render("trpc-go/scripts/generate_stub.sh.tpl", context),
            "pb/README.md": self._render("trpc-go/pb/README.md.tpl", context),
            ".github/workflows/build-and-deploy.yaml": self._render("github-actions/build-and-deploy.yaml.j2", {"spec": spec}),
            "k8s/deployment.yaml": self._render("k8s/deployment.yaml.j2", {"spec": spec}),
            "k8s/service.yaml": self._render("k8s/service.yaml.j2", {"spec": spec}),
            "README.md": self._build_readme(spec, context),
        }
        if context["http_enabled"]:
            files["handler/http_handler.go"] = self._render("trpc-go/handler/http_handler.go.tpl", context)
        if context["db_enabled"]:
            files["handler/db_handler.go"] = self._render("trpc-go/handler/db_handler.go.tpl", context)
            if context["db_type"] == "redis":
                files["handler/redis_handler.go"] = self._render("trpc-go/handler/redis_handler.go.tpl", context)
        if context["kafka_consumer_enabled"]:
            files["handler/kafka_consumer.go"] = self._render("trpc-go/handler/kafka_consumer.go.tpl", context)
        if context["kafka_producer_enabled"]:
            files["handler/kafka_producer.go"] = self._render("trpc-go/handler/kafka_producer.go.tpl", context)
        if spec.exposure.type == "ingress":
            files["k8s/ingress.yaml"] = self._render("k8s/ingress.yaml.j2", {"spec": spec})
        if spec.exposure.type == "loadBalancer":
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

    def _build_context(self, spec: ServiceSpec, contract: ProtoContract) -> dict[str, Any]:
        service_name = self._slug(spec.service.name or spec.repo.name or contract.service_name or "service")
        owner = self._slug(spec.repo.owner or "team")
        repo_name = self._slug(spec.repo.name or service_name)
        module_path = (spec.service.module or f"github.com/{owner}/{repo_name}").strip()

        db_type = spec.database.type if spec.database.type in {"mysql", "redis"} else None
        db_enabled = bool(spec.database.enabled and db_type)
        kafka_enabled = bool(spec.kafka.enabled)
        rpc_methods: list[dict[str, str]] = []
        for index, method in enumerate(contract.methods):
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
        http_apis = [
            self._http_api_from_endpoint(endpoint, rpc_method)
            for endpoint, rpc_method in zip(spec.endpoints, rpc_methods)
        ]
        normalized_name = service_name.replace("-", "_")
        handler_type_name = f"{contract.service_name}Handler"
        service_prefix = f"trpc.{contract.package}"

        return {
            "module_path": module_path,
            "group": owner,
            "app": repo_name,
            "server": service_name,
            "server_bin": service_name,
            "proto_package": contract.package,
            "proto_output_name": contract.source_path.name,
            "proto_source_path": str(contract.source_path),
            "rpc_enabled": bool(contract.methods),
            "rpc_service_name": contract.service_name,
            "rpc_methods": rpc_methods,
            "handler_type_name": handler_type_name,
            "trpc_service_name": f"{service_prefix}.{contract.service_name}",
            "http_enabled": bool(http_apis),
            "http_apis": http_apis,
            "http_port": 8080,
            "trpc_port": 9000,
            "health_path": spec.exposure.health_path,
            "db_enabled": db_enabled,
            "db_type": db_type or "mysql",
            "db_tables": [normalized_name],
            "db_service_name": f"{service_prefix}.{db_type or 'mysql'}",
            "db_host": spec.database.host or "db.example.internal",
            "db_port": spec.database.port or (3306 if db_type == "mysql" else 6379),
            "db_name": spec.database.database or normalized_name,
            "db_user": normalized_name,
            "db_password_env": self._env_name(spec.database.secret_name or f"{service_name}_db_password"),
            "kafka_consumer_enabled": kafka_enabled,
            "kafka_producer_enabled": False,
            "kafka_service_name": f"{service_prefix}.kafka",
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
            f"- trpc service: `{context['trpc_service_name']}`",
            f"- handler type: `{context['handler_type_name']}`",
            "",
            "## Contract",
            f"- source proto: `{context['proto_source_path']}`",
            f"- copied proto: `proto/{context['proto_output_name']}`",
            "",
            "## Generated Assets",
            "- `scripts/generate_stub.sh`: runs `trpc create --rpconly` against the user-provided `.proto` to generate pb stubs into `pb/`",
            "- `handler/handler.go`: business implementation of the generated tRPC service interface",
            "- `handler/http_handler.go`: HTTP wrapper that reuses the same business handler when HTTP endpoints are requested",
            "",
            "## Exposure",
            f"- type: `{spec.exposure.type}`",
            f"- health path: `{spec.exposure.health_path}`",
        ]
        if spec.exposure.host:
            lines.append(f"- host: `{spec.exposure.host}`")
        lines.extend(
            [
                "",
                "## Notes",
                "- Formal tRPC generation in this project requires a user-provided `.proto` contract.",
                "- The generated Go code is aligned to the public `trpc-group/trpc-go` and `trpc-ecosystem/go-database` import space.",
                "- Build scripts generate pb stubs before `go build`, so the generated project uses the provided protocol as the source of truth.",
                "- HTTP endpoints, when requested, are implemented as a thin wrapper over the same handler rather than as the only business entrypoint.",
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

    def _slug(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_\-]+", "-", value.strip())
        normalized = normalized.strip("-_")
        return normalized or "service"

    def _env_name(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.upper())
        normalized = normalized.strip("_")
        return normalized or "SECRET_VALUE"
