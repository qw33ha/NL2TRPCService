"""Black-box HTTP checks against the complete generated service process."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import yaml


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_behavior(root: Path, cases: list[dict]) -> dict:
    if not cases:
        return {"status": "not_requested", "cases": []}
    exe = root / ("evaluation-service.exe" if os.name == "nt" else "evaluation-service")
    process = None
    outcomes = []
    try:
        build = subprocess.run([shutil.which("go") or "go", "build", "-o", str(exe), "."], cwd=root,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        if build.returncode:
            raise RuntimeError(build.stderr)
        config_path = root / "trpc_go.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        port = free_port()
        services = config["server"]["service"]
        http = [service for service in services if str(service.get("protocol", "")).startswith("http")]
        if len(http) != 1:
            raise RuntimeError("Behavior tests require exactly one HTTP transport")
        http[0].update(ip="127.0.0.1", port=port)
        config.setdefault("global", {})["admin_port"] = free_port()
        for field in ("bin_path", "conf_path", "data_path"):
            config["server"][field] = str(root)
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        # Runtime receives no API or delivery credentials.
        env = {key: value for key, value in os.environ.items()
               if not any(word in key.upper() for word in ("TOKEN", "SECRET", "API_KEY", "PASSWORD"))}
        with (root / "runtime.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(exe), "-conf", str(config_path)], cwd=root, env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Generated server exited: " + (root / "runtime.log").read_text(encoding="utf-8")[-6000:])
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.3):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Generated server startup timed out")
                    time.sleep(.1)
            for case in cases:
                body = case.get("body")
                if "body_bytes" in case:
                    # Oversize is tested independently of malformed JSON: a valid
                    # JSON string of exactly the requested byte count.
                    if case["body_bytes"] < 2:
                        raise ValueError("body_bytes must be at least 2 for valid JSON")
                    data = b'"' + b"x" * (case["body_bytes"] - 2) + b'"'
                elif body is not None:
                    data = json.dumps(body).encode()
                elif "raw_body" in case:
                    data = case["raw_body"].encode()
                else:
                    data = None
                req = urllib.request.Request(f"http://127.0.0.1:{port}{case['path']}", data=data,
                                             method=case.get("method", "GET"), headers=case.get("headers", {}))
                try:
                    try:
                        response = urllib.request.urlopen(req, timeout=5)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        raw = response.read(2 * 1024 * 1024)
                        status = response.status
                        content_type = response.headers.get("Content-Type", "")
                    checks = {"status": status == case["status"]}
                    if case.get("json_content_type", True):
                        checks["content_type"] = "application/json" in content_type
                    if "json" in case:
                        try:
                            checks["body"] = json.loads(raw) == case["json"]
                        except ValueError:
                            checks["body"] = False
                    if case.get("json_error"):
                        try:
                            decoded = json.loads(raw)
                            checks["error_schema"] = isinstance(decoded, dict) and set(decoded) == {"error"} and isinstance(decoded["error"], str)
                        except ValueError:
                            checks["error_schema"] = False
                    outcomes.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                                     "actual_status": status, "response_excerpt": raw[:300].decode(errors="replace")})
                except Exception as exc:
                    outcomes.append({"id": case["id"], "passed": False, "error": str(exc)})
        return {"status": "passed" if all(item["passed"] for item in outcomes) else "failed", "cases": outcomes}
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "cases": [
            {"id": case["id"], "passed": False, "error": "Server could not start"} for case in cases]}
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
