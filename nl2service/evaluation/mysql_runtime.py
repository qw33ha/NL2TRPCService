"""Disposable loopback MySQL plus real tRPC request/response integration runtime."""
from __future__ import annotations
import json
import os
import secrets
import socket
import subprocess
import time
import uuid
from pathlib import Path

IMAGE = "mysql@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MySQLRuntime:
    def __enter__(self):
        self.name = "nl2service-mysql-" + uuid.uuid4().hex[:12]
        self.password = secrets.token_hex(20)
        env = {**os.environ, "MYSQL_ROOT_PASSWORD": self.password}
        try:
            subprocess.run(["docker", "run", "--rm", "-d", "--name", self.name, "-e", "MYSQL_ROOT_PASSWORD",
                            "-e", "MYSQL_ROOT_HOST=%", "-e", "MYSQL_DATABASE=nl2bench", "-p", "127.0.0.1::3306", IMAGE],
                           env=env, capture_output=True, check=True, timeout=90)
            deadline = time.monotonic()+120
            while True:
                try:
                    self.sql("SELECT 1;")
                    break
                except RuntimeError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Disposable MySQL readiness timed out.")
                    time.sleep(1)
            port = subprocess.run(["docker", "port", self.name, "3306"],capture_output=True,text=True,encoding="utf-8",check=True).stdout.strip().split(":")[-1]
            self.target = f"dsn://root:{self.password}@tcp(127.0.0.1:{port})/nl2bench?parseTime=true&timeout=5s"
            return self
        except Exception:
            self.__exit__(None,None,None)
            raise

    def sql(self, statement):
        env = {**os.environ, "MYSQL_PWD": self.password}
        result = subprocess.run(["docker", "exec", "-i", "-e", "MYSQL_PWD", self.name, "mysql", "-uroot", "--batch", "--skip-column-names", "nl2bench"],
                                input=statement,env=env,capture_output=True,text=True,encoding="utf-8",timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(self.password, "[redacted]")[-1500:])
        return result.stdout.strip()

    def __exit__(self,*args):
        subprocess.run(["docker", "stop", "-t", "5", self.name],capture_output=True,timeout=30)


class RPCService:
    def __init__(self, root: Path, database: MySQLRuntime):
        self.root, self.database = root, database
        self.port = free_port()
        self.exe = root / ("service.exe" if os.name == "nt" else "service")
        self.env = {key:value for key,value in os.environ.items() if not any(marker in key.upper() for marker in ("TOKEN","API_KEY","SECRET","PASSWORD"))}
        self.env.update(NL2SERVICE_RPC_PORT=str(self.port),NL2SERVICE_RPC_TARGET=f"ip://127.0.0.1:{self.port}",NL2SERVICE_MYSQL_TARGET=database.target)

    def __enter__(self):
        build = subprocess.run(["go", "build", "-o", str(self.exe), "."],cwd=self.root,capture_output=True,text=True,encoding="utf-8",timeout=180)
        if build.returncode:
            raise RuntimeError(build.stderr[-4000:])
        self.start()
        return self

    def start(self):
        self.log = (self.root / "rpc-runtime.log").open("w",encoding="utf-8")
        self.process = subprocess.Popen([str(self.exe), "-conf", "trpc_go.yaml"],cwd=self.root,env=self.env,stdout=self.log,stderr=self.log)
        deadline = time.monotonic()+20
        while True:
            if self.process.poll() is not None:
                self.stop()
                raise RuntimeError((self.root / "rpc-runtime.log").read_text()[-2000:].replace(self.database.password,"[redacted]"))
            try:
                with socket.create_connection(("127.0.0.1",self.port),timeout=.2):
                    return
            except OSError:
                if time.monotonic()>deadline:
                    self.stop()
                    raise RuntimeError("tRPC server startup timeout.")
                time.sleep(.1)

    def call(self, payload):
        env = {**self.env,"NL2SERVICE_RPC_REQUEST":json.dumps(payload)}
        result = subprocess.run([str(self.exe),"-conf","trpc_go.yaml"],cwd=self.root,env=env,capture_output=True,text=True,encoding="utf-8",timeout=15)
        if result.returncode:
            raise RuntimeError(result.stderr[-1500:].replace(self.database.password,"[redacted]"))
        return json.loads(result.stdout.strip().splitlines()[-1])

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.wait()
        self.log.close()
        path = self.root / "rpc-runtime.log"
        path.write_text(path.read_text(encoding="utf-8", errors="replace").replace(self.database.password,"[redacted]"),encoding="utf-8")

    def restart(self):
        self.stop();self.start()

    def __exit__(self,*args):
        self.stop()
