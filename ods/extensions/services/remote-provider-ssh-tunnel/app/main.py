"""Internal-only remote-provider SSH tunnel status service.

This scaffold is intentionally inert: it loads generated route state, reports
a redacted supervisor plan, and never starts ssh or opens provider tunnels.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from remote_provider.ssh_supervisor import (
    SSH_SUPERVISOR_PLAN_SCHEMA,
    ssh_secret_status,
    ssh_supervisor_plan,
)


HEALTH_SCHEMA = "ods.remote-provider-ssh-tunnel-health.v1"
ROUTE_STATE_SCHEMA = "ods.remote-routing-state.v1"
DEFAULT_ROUTE_PATH = Path("/state/remote-provider/routing-state.json")
DEFAULT_SECRET_DIR = Path("/state/remote-provider/secrets")
DEFAULT_STATUS_PORT = 18090

LOGGER = logging.getLogger("remote-provider-ssh-tunnel")


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default)))


def _status_port() -> int:
    raw = os.environ.get("ODS_REMOTE_PROVIDER_SSH_STATUS_PORT", str(DEFAULT_STATUS_PORT))
    try:
        port = int(raw)
    except ValueError:
        LOGGER.warning("invalid ODS_REMOTE_PROVIDER_SSH_STATUS_PORT=%r; using default", raw)
        return DEFAULT_STATUS_PORT
    if port < 1 or port > 65535:
        LOGGER.warning("out-of-range ODS_REMOTE_PROVIDER_SSH_STATUS_PORT=%r; using default", raw)
        return DEFAULT_STATUS_PORT
    return port


def _disabled_route() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": None,
        "transport": "direct",
        "provider": None,
        "ssh": None,
    }


def _error_plan(reason: str, *, status: str = "invalid") -> dict[str, Any]:
    return {
        "schema": SSH_SUPERVISOR_PLAN_SCHEMA,
        "status": status,
        "ready": False,
        "readyToStart": False,
        "reason": reason,
        "tunnelBaseUrl": None,
        "tunnels": [],
        "secrets": ssh_secret_status(_env_path("ODS_REMOTE_PROVIDER_SECRET_DIR", DEFAULT_SECRET_DIR)),
    }


def _route_from_state_doc(doc: Mapping[str, Any]) -> dict[str, Any]:
    if doc.get("schema") != ROUTE_STATE_SCHEMA:
        raise ValueError("unknown route-state schema")
    enabled = doc.get("enabled") is True
    provider = doc.get("provider")
    if enabled and not isinstance(provider, Mapping):
        raise ValueError("enabled route state is missing provider metadata")
    provider_dict = dict(provider) if isinstance(provider, Mapping) else {}
    ssh = doc.get("ssh")
    return {
        "enabled": enabled,
        "mode": doc.get("mode"),
        "transport": str(provider_dict.get("transport") or "direct") if enabled else "direct",
        "provider": provider_dict if enabled else None,
        "ssh": dict(ssh) if isinstance(ssh, Mapping) else None,
    }


def _load_route(route_path: Path) -> dict[str, Any]:
    try:
        raw = route_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _disabled_route()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("route state is not valid JSON") from exc
    if not isinstance(doc, Mapping):
        raise ValueError("route state must be a JSON object")
    return _route_from_state_doc(doc)


def _supervisor_plan() -> dict[str, Any]:
    route_path = _env_path("ODS_REMOTE_PROVIDER_ROUTE_PATH", DEFAULT_ROUTE_PATH)
    secret_dir = _env_path("ODS_REMOTE_PROVIDER_SECRET_DIR", DEFAULT_SECRET_DIR)
    try:
        route = _load_route(route_path)
    except (OSError, ValueError) as exc:
        LOGGER.info("remote route state unavailable: %s", exc)
        return _error_plan("route_state_unavailable")
    try:
        return ssh_supervisor_plan(route, secrets=ssh_secret_status(secret_dir))
    except (TypeError, ValueError) as exc:
        LOGGER.info("remote SSH supervisor plan unavailable: %s", exc)
        return _error_plan("ssh_plan_unavailable")


def health_payload() -> dict[str, Any]:
    plan = _supervisor_plan()
    return {
        "schema": HEALTH_SCHEMA,
        "ready": bool(plan.get("ready")),
        "status": plan.get("status"),
        "reason": plan.get("reason"),
        "plan": plan,
    }


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "ODSRemoteProviderSSHTunnel/1"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path != "/health":
            self._write_json({"error": "not_found"}, status=404)
            return
        self._write_json(health_payload())

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def _write_json(self, payload: Mapping[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main() -> int:
    logging.basicConfig(level=os.environ.get("ODS_LOG_LEVEL", "INFO"))
    server = ThreadingHTTPServer(("0.0.0.0", _status_port()), HealthHandler)
    LOGGER.info("remote-provider SSH tunnel status service listening on %s", server.server_address)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
