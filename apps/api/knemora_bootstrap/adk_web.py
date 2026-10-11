"""Launch the existing Knemora agent in Google ADK's local developer UI."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from knemora_bootstrap.configuration import AppPaths, runtime_environment

ADK_WEB_HOST = "127.0.0.1"
ADK_WEB_URL_HOST = "localhost"
ADK_WEB_PORTS = range(8080, 8091)
ADK_APP_NAME = "knowledge_agent"


def _url_port(value: str) -> int | None:
    try:
        parsed = urlparse(value)
        return parsed.port or ({"http": 80, "https": 443}.get(parsed.scheme))
    except ValueError:
        return None


def _configured_service_ports(paths: AppPaths, env: dict[str, str]) -> dict[int, set[str]]:
    """Read ports reserved by configured Knemora services without exposing secrets."""

    reserved: dict[int, set[str]] = {}

    def add(port: int | None, service: str) -> None:
        if port is not None and 0 < port < 65_536:
            reserved.setdefault(port, set()).add(service)

    for key, service in (
        ("KNEMORA_API_PORT", "FastAPI"),
        ("KNEMORA_LLM_PORT", "llama.cpp"),
    ):
        raw = env.get(key)
        try:
            add(int(raw) if raw else None, service)
        except ValueError:
            continue
    add(_url_port(env.get("KNEMORA_WEB_ORIGIN", "")), "frontend")
    add(_url_port(env.get("KNEMORA_LLM_BASE_URL", "")), "llama.cpp")

    return reserved


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((ADK_WEB_HOST, port))
        except OSError:
            return False
    return True


def _read_json(url: str | urllib.request.Request, *, timeout: float = 1.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        if not 200 <= int(response.status) < 300:
            return None
        return json.load(response)


def _is_knemora_adk_web(port: int) -> bool:
    try:
        payload = _read_json(f"http://{ADK_WEB_HOST}:{port}/list-apps")
    except (OSError, TimeoutError, ValueError, urllib.error.URLError):
        return False
    if isinstance(payload, list):
        return ADK_APP_NAME in payload
    if isinstance(payload, dict):
        apps = payload.get("apps")
        return isinstance(apps, list) and any(
            item == ADK_APP_NAME or (isinstance(item, dict) and item.get("name") == ADK_APP_NAME)
            for item in apps
        )
    return False


def _select_port(paths: AppPaths, env: dict[str, str]) -> tuple[int | None, bool]:
    reserved = _configured_service_ports(paths, env)
    for port in ADK_WEB_PORTS:
        if not _port_is_available(port):
            if _is_knemora_adk_web(port):
                return port, True
            continue
        if port in reserved:
            services = ", ".join(sorted(reserved[port]))
            print(f"ADK Web: skipping configured port {port} ({services}).")
            continue
        return port, False
    return None, False


def _check_agent_import(api_directory: Path, python: Path, env: dict[str, str]) -> None:
    check = subprocess.run(
        [
            str(python),
            "-c",
            (
                "from knowledge_agent import app, root_agent; "
                "assert app.name == 'knowledge_agent'; "
                "assert root_agent.name == 'knowledge_agent'"
            ),
        ],
        cwd=api_directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if check.returncode:
        raise RuntimeError(
            "The existing knowledge_agent could not be imported with apps/api/.venv. "
            "Run ./knemora setup, then retry. See the local terminal or API logs for details."
        )


def _check_model_server(env: dict[str, str]) -> None:
    base_url = env.get("KNEMORA_LLM_BASE_URL", "http://localhost:8080").rstrip("/")
    request = urllib.request.Request(f"{base_url}/health")
    api_key = env.get("KNEMORA_LLM_API_KEY")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        payload = _read_json(request, timeout=2.0)
    except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError(
            "The configured local model server is unavailable. Start Knemora first with "
            "./knemora start (or ./knemora start-with-presets), then retry ADK Web."
        ) from exc
    status = payload.get("status") if isinstance(payload, dict) else None
    if status not in {None, "ok", "ready"}:
        raise RuntimeError(
            "The configured local model server is not ready. Check ./knemora status and "
            "./knemora logs before launching ADK Web."
        )


def launch_adk_web(paths: AppPaths, *, web_search_enabled: bool = False) -> int:
    """Run official ADK Web in the foreground with Knemora's existing agent."""

    api_directory = paths.repository / "apps" / "api"
    adk = api_directory / ".venv" / "bin" / "adk"
    python = api_directory / ".venv" / "bin" / "python"
    agent_directory = api_directory / ADK_APP_NAME
    if not adk.is_file() or not python.is_file():
        raise RuntimeError(
            "Google ADK is missing from apps/api/.venv. Run ./knemora setup to install the "
            "repository's locked Python dependencies."
        )
    if not agent_directory.is_dir():
        raise RuntimeError(f"The existing ADK agent directory is missing: {agent_directory}")

    env = runtime_environment(paths, web_search_enabled=web_search_enabled)
    port, already_running = _select_port(paths, env)
    if port is None:
        raise RuntimeError(
            "No ADK Web port is available in localhost:8080-8090. Stop one of your own "
            "development listeners or configure the conflicting service on another port."
        )
    url = f"http://{ADK_WEB_URL_HOST}:{port}"
    if already_running:
        print(f"Knemora ADK Web is already running: {url}")
        print("Use that server instead; no duplicate was started.")
        return 0

    _check_agent_import(api_directory, python, env)
    _check_model_server(env)
    print(f"Knemora ADK Web: {url}")
    print(
        "Development server only. Use its own chat to populate Events and Trace; requests "
        "from the normal Knemora UI do not automatically appear there."
    )
    print(
        "Public web search is "
        f"{'enabled' if web_search_enabled else 'disabled'} for this playground process."
    )
    print("Press Ctrl+C to stop ADK Web.", flush=True)
    command = [
        str(adk),
        "web",
        "--host",
        ADK_WEB_HOST,
        "--port",
        str(port),
        "--no-reload",
        "--session_service_uri",
        "memory://",
        str(agent_directory),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=api_directory,
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except KeyboardInterrupt:
        print("\nKnemora ADK Web stopped.")
        return 130
    if result.returncode:
        raise RuntimeError(f"ADK Web exited with status {result.returncode}. The URL was {url}.")
    return 0
