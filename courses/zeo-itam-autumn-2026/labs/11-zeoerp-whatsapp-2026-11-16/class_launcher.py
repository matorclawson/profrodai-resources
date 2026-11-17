"""Bounded Mantle startup check with an explicit license source and no model turn.

This is the class launch entrypoint's startup-only mode. It does not activate a
provider, ERP binding or channel. Model-enabled class serving remains a separate
approval. The existing installed SDK and environment are never changed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def child(state):
    # A process-local audit guard: no SDK patch and no outbound network fallback.
    events = []

    def audit(event, args):
        if event == "socket.connect":
            sock, address = args
            if sock.family != socket.AF_UNIX:
                events.append({"event": event, "allowed": False})
                write_json(state / "network-audit.json", events)
                raise PermissionError("startup_check_outbound_network_forbidden")
        elif event == "socket.getaddrinfo":
            host = args[0]
            if host not in {None, "127.0.0.1", "localhost", "::1"}:
                events.append({"event": event, "allowed": False})
                write_json(state / "network-audit.json", events)
                raise PermissionError("startup_check_external_dns_forbidden")
        elif event == "socket.bind":
            sock, address = args
            if sock.family in {socket.AF_INET, socket.AF_INET6}:
                if address[0] != "127.0.0.1":
                    raise PermissionError("startup_check_nonloopback_bind_forbidden")
                events.append({"event": event, "allowed": True, "host": "127.0.0.1"})

    sys.addaudithook(audit)
    from importlib.metadata import version
    from rasa.utils.licensing import validate_license_from_env

    if version("rasa-pro") != "3.21.0.dev5":
        raise RuntimeError("installed_runtime_pin_changed")
    validate_license_from_env()  # Bundled public-key JWT checks; no remote check.
    write_json(state / "LICENSE-ACCEPTED.json", {"variable": "RASA_LICENSE", "accepted": True,
                                               "check": "installed validate_license_from_env"})
    from rasa.mantle.model_archive.snapshot import package_model_archive
    from rasa.core.config.configuration import Configuration
    from rasa.core.config.available_endpoints import AvailableEndpoints
    from rasa.core.run import configure_app, load_agent_on_start, close_resources
    from rasa.mantle.processor import MantleMessageProcessor
    from sanic.response import json as response_json

    project = state / "project"
    os.chdir(project)
    packaged = package_model_archive(str(project / "agent.yml"), str(state / "models"),
                                     fixed_model_name="itam-startup", validate=True)
    if packaged.code:
        raise RuntimeError("startup_project_validation_failed")
    Configuration.initialise_empty_endpoints()
    Configuration.initialise_sub_agents(None)
    endpoints = AvailableEndpoints.from_dict({})
    app = configure_app(input_channels=[], enable_api=True, endpoints=endpoints)
    observations = {"conversation_requests": 0, "status_requests": 0}

    @app.middleware("request")
    async def only_status(request):
        if request.method != "GET" or request.path != "/status":
            observations["conversation_requests"] += 1
            return response_json({"error": "startup_check_only"}, status=403)
        observations["status_requests"] += 1

    async def load(running_app, loop):
        # Use the installed server's actual model-loading function and processor.
        await load_agent_on_start(str(packaged.model), endpoints, None, None, running_app, loop)
        if not isinstance(running_app.ctx.agent.processor, MantleMessageProcessor):
            raise RuntimeError("not_native_mantle_processor")

    async def started(running_app, loop):
        write_json(state / "READY.json", {"port": listener.getsockname()[1],
            "host": "127.0.0.1", "processor": type(running_app.ctx.agent.processor).__name__,
            "license_accepted": True, "started_epoch": time.time()})

        async def stop_watch():
            deadline = time.monotonic() + 75
            while not (state / "STOP").exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            running_app.stop()
        running_app.add_task(stop_watch())

    app.register_listener(load, "before_server_start")
    app.register_listener(started, "after_server_start")
    app.register_listener(close_resources, "after_server_stop")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(64)
    try:
        app.run(sock=listener, single_process=True, access_log=False, auto_reload=False)
    finally:
        listener.close()
        write_json(state / "network-audit.json", events)
        write_json(state / "CHILD-TERMINAL.json", {**observations,
            "listener_closed": listener.fileno() == -1, "ended_epoch": time.time()})


def parent():
    from dotenv import dotenv_values
    from pydantic import BaseModel, ConfigDict, SecretStr

    class StartupSettings(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        license_env_file: Path
        state_dir: Path
        startup_only: bool

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--license-env-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--startup-only", action="store_true", required=True)
    settings = StartupSettings.model_validate(vars(parser.parse_args()))
    state = settings.state_dir.resolve()
    state.mkdir(mode=0o700, parents=False, exist_ok=False)
    license_value = dotenv_values(settings.license_env_file, interpolate=False).get("RASA_LICENSE")
    if not license_value:
        write_json(state / "RESULT.json", {"verdict": "NOT_STARTED", "reason": "RASA_LICENSE_missing"})
        return 2
    license_config = SecretStr(license_value)
    del license_value
    environment = {name: os.environ[name] for name in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
                   if name in os.environ}
    environment.update(RASA_LICENSE=license_config.get_secret_value(),
        RASA_TELEMETRY_ENABLED="false", RASA_AWS_MARKETPLACE_ENABLED="false",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1",
        ITAM_STARTUP_DUMMY_KEY="startup-only-not-a-credential")
    project = state / "project"
    project.mkdir()
    (project / "agent.yml").write_text("agent:\n  id: itam-license-startup-check\n  language: en\n  persona: Startup-only class configuration. No conversation is enabled.\n")
    (project / "integrations.yml").write_text(
        "llm:\n  model_group: startup-only\nmodel_groups:\n  - id: startup-only\n"
        "    models:\n      - provider: openai\n        model: gpt-4o-mini\n"
        "        api_key: ${ITAM_STARTUP_DUMMY_KEY}\n"
        "        api_base: http://127.0.0.1:9/v1\nchannels: {}\n")
    report = {"verdict": "FAILED_NOT_QUALIFIED", "attempts": 1,
        "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "license_variable": "RASA_LICENSE", "license_source": "explicit_dotenv",
        "startup_only": True, "model_turns": 0, "provider_calls": 0,
        "started_epoch": time.time()}
    process = None
    ready = None
    interrupted = False

    def stop_signal(*_):
        nonlocal interrupted
        interrupted = True
        (state / "STOP").touch()
    signal.signal(signal.SIGINT, stop_signal)
    signal.signal(signal.SIGTERM, stop_signal)
    try:
        with (state / "server.stdout").open("xb") as stdout, (state / "server.stderr").open("xb") as stderr:
            process = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                "--child", str(state)], env=environment, cwd=project, stdout=stdout, stderr=stderr,
                start_new_session=True)
            deadline = time.monotonic() + 90
            while not (state / "READY.json").exists():
                if process.poll() is not None:
                    raise RuntimeError("server_exited_before_ready")
                if interrupted or time.monotonic() >= deadline:
                    raise TimeoutError("startup_deadline")
                time.sleep(0.1)
            ready = json.loads((state / "READY.json").read_text())
            connection = http.client.HTTPConnection("127.0.0.1", ready["port"], timeout=5)
            try:
                connection.request("GET", "/status")
                response = connection.getresponse()
                status = response.status
                payload = json.loads(response.read())
            finally:
                connection.close()
            if status != 200 or not payload.get("model_id"):
                raise RuntimeError("native_status_not_ready")
            report.update(license_accepted=ready["license_accepted"], processor=ready["processor"],
                          status_http=status, model_loaded=True, model_id_present=True)
            (state / "STOP").touch()
            process.wait(timeout=20)
            terminal = json.loads((state / "CHILD-TERMINAL.json").read_text())
            audit = json.loads((state / "network-audit.json").read_text())
            probe = socket.socket()
            probe.settimeout(2)
            try:
                closed_code = probe.connect_ex(("127.0.0.1", ready["port"]))
            finally:
                probe.close()
            if process.returncode or terminal["conversation_requests"] or not closed_code or any(not e["allowed"] for e in audit):
                raise RuntimeError("startup_or_closure_control_failed")
            report.update(verdict="PASS_LICENSE_VALIDATED_MANTLE_STARTUP_ONLY",
                server_exit=process.returncode, listener_closed=True, close_connect_ex=closed_code,
                conversation_requests=terminal["conversation_requests"], status_requests=terminal["status_requests"],
                outbound_network_attempts=0, port=ready["port"])
    except BaseException as error:
        report["error_type"] = type(error).__name__
        # Fixed error labels only, never arbitrary SDK errors, credentials or locals.
        if type(error) in {RuntimeError, TimeoutError}:
            report["failed_control"] = str(error)
    finally:
        (state / "STOP").touch()
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        report["server_exit"] = process.returncode if process is not None else None
        report["ended_epoch"] = time.time()
        write_json(state / "RESULT.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["verdict"] == "PASS_LICENSE_VALIDATED_MANTLE_STARTUP_ONLY" else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
    else:
        raise SystemExit(parent())
