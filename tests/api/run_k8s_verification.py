#!/usr/bin/env python3
"""Fail-closed Kubernetes API verification and Gateway loopback proxy."""

from __future__ import annotations

import argparse
import http.client
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ARTIFACT_DIR = Path("/artifacts/api")
PUBLIC_ORIGIN = "http://nohiki.localhost"
PROXY_GATEWAY_UPSTREAM = "http://nohiki-gateway.nohiki.svc.cluster.local:80"
PROXY_ALLOWED_HOSTS = frozenset({"nohiki.localhost", "s3.nohiki.localhost"})
PROXY_LISTEN_HOST = "127.0.0.1"
PROXY_LISTEN_PORT = 80
SESSION_IDENTITIES = (
    ("e2e-session-user@example.com", "SessionUserP@ss123!"),
    ("e2e-playwright@example.com", "PlaywrightP@ss123!"),
)


def _delete_identity(base_url: str, email: str, password: str) -> bool:
    """Delete a declared verification identity through the public Gateway."""
    import requests

    session = requests.Session()
    session.headers["Origin"] = PUBLIC_ORIGIN
    login = session.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if login.status_code in {401, 404}:
        return True
    if not login.ok:
        return False
    deleted = session.delete(f"{base_url}/api/v1/account", timeout=30)
    return deleted.status_code in {204, 404}


def _cleanup_identities(base_url: str) -> list[str]:
    """Remove declared test identities and return failed email addresses."""
    from requests import RequestException

    failures: list[str] = []
    for email, password in SESSION_IDENTITIES:
        try:
            deleted = _delete_identity(base_url, email, password)
        except RequestException:
            deleted = False
        if not deleted:
            failures.append(email)
    return failures


def _junit_counts(path: Path) -> dict[str, int]:
    """Count outcomes in trusted pytest-generated JUnit XML."""
    parser = ET.XMLPullParser(events=("start", "end"))
    parser.feed(path.read_text(encoding="utf-8"))
    _, root = next(parser.read_events())
    parser.close()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.attrib.get(key, "0"))
    xfail = sum(
        1
        for skipped in root.findall(".//testcase/skipped")
        if "xfail" in f"{skipped.attrib.get('type', '')} {skipped.attrib.get('message', '')}".lower()
    )
    totals["skipped"] -= xfail
    totals["xfail"] = xfail
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"] - totals["xfail"]
    return totals


def run_api() -> int:
    """Run the fail-closed API contract suite and persist its result."""
    base_url = os.environ.get("E2E_BASE_URL", "")
    if base_url != PUBLIC_ORIGIN:
        msg = f"E2E_BASE_URL must be {PUBLIC_ORIGIN}"
        raise SystemExit(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    collection_path = ARTIFACT_DIR / "collection.txt"
    log_path = ARTIFACT_DIR / "pytest.log"
    junit_path = ARTIFACT_DIR / "junit.xml"
    result_path = ARTIFACT_DIR / "result.json"
    command = [
        "uv",
        "run",
        "--project",
        "tests",
        "pytest",
        "-o",
        "xfail_strict=true",
        "tests/api",
    ]
    collect = subprocess.run(
        [*command, "--collect-only", "-q"],
        cwd="/workspace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    collection_path.write_text(collect.stdout, encoding="utf-8")
    log_path.write_text("collection failed; test execution did not start\n", encoding="utf-8")
    matches = re.findall(
        r"(?:collected\s+(\d+)\s+items?|(?<!\w)(\d+)\s+tests? collected)",
        collect.stdout,
    )
    reported_counts = {int(left or right) for left, right in matches}
    collected = reported_counts.pop() if len(reported_counts) == 1 else 0
    pre_cleanup_failures = _cleanup_identities(base_url)
    completed = subprocess.CompletedProcess(command, 1, "collection failed")
    post_cleanup_failures: list[str] = []
    try:
        if collect.returncode == 0 and collected:
            completed = subprocess.run(
                [*command, f"--junitxml={junit_path}"],
                cwd="/workspace",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            log_path.write_text(completed.stdout, encoding="utf-8")
    finally:
        post_cleanup_failures = _cleanup_identities(base_url)
    counts = (
        _junit_counts(junit_path)
        if junit_path.exists()
        else {
            "tests": 0,
            "passed": 0,
            "failures": 0,
            "errors": 1,
            "skipped": 0,
            "xfail": 0,
        }
    )
    result = {
        "contract": "nohiki-api-verification/v1",
        "collected": collected,
        **counts,
        "collection_exit_code": collect.returncode,
        "pytest_exit_code": completed.returncode,
        "pre_cleanup_failures": pre_cleanup_failures,
        "post_cleanup_failures": post_cleanup_failures,
    }
    valid = (
        collect.returncode == 0
        and completed.returncode == 0
        and collected > 0
        and counts["tests"] == collected
        and counts["failures"] == counts["errors"] == counts["skipped"] == counts["xfail"] == 0
        and not pre_cleanup_failures
        and not post_cleanup_failures
    )
    result["status"] = "passed" if valid else "failed"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if valid else 1


def _validated_proxy_host(raw_host: str) -> str:
    """Return an allowlisted Gateway route hostname, stripping an optional port."""
    match = re.fullmatch(r"([a-z0-9.-]+)(?::([0-9]{1,5}))?", raw_host)
    if match is None or match.group(1) not in PROXY_ALLOWED_HOSTS:
        msg = "request Host is not an allowed public route"
        raise ValueError(msg)
    if match.group(2) is not None and not 1 <= int(match.group(2)) <= 65535:
        msg = "request Host port is invalid"
        raise ValueError(msg)
    return match.group(1)


class _GatewayProxy(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def forward_request(self) -> None:
        """Forward the current request to the fixed Gateway upstream."""
        try:
            public_host = _validated_proxy_host(self.headers.get("Host", ""))
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        upstream = urlsplit(os.environ["NOHIKI_GATEWAY_UPSTREAM"])
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        headers = {key: value for key, value in self.headers.items() if key.lower() not in {"host", "connection"}}
        headers["Host"] = public_host
        connection = http.client.HTTPConnection(upstream.hostname, upstream.port or 80, timeout=300)
        connection.request(self.command, self.path, body=body or None, headers=headers)
        response = connection.getresponse()
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in {"connection", "content-length", "transfer-encoding"}:
                self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            while chunk := response.read1(64 * 1024):
                self.wfile.write(chunk)
                self.wfile.flush()
        self.close_connection = True
        connection.close()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"gateway-proxy: {fmt % args}\n")


for method in ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"):
    setattr(_GatewayProxy, f"do_{method}", _GatewayProxy.forward_request)


def run_proxy() -> int:
    """Run the loopback-only proxy after validating its fixed configuration."""
    upstream = os.environ.get("NOHIKI_GATEWAY_UPSTREAM", "")
    listen_host = os.environ.get("NOHIKI_PROXY_LISTEN_HOST", "")
    listen_port = os.environ.get("NOHIKI_PROXY_LISTEN_PORT", "")
    allowed_hosts = os.environ.get("NOHIKI_PROXY_ALLOWED_HOSTS", "")
    if upstream != PROXY_GATEWAY_UPSTREAM:
        msg = "NOHIKI_GATEWAY_UPSTREAM must target the in-cluster public Gateway Service"
        raise SystemExit(msg)
    if listen_host != PROXY_LISTEN_HOST or listen_port != str(PROXY_LISTEN_PORT):
        msg = "proxy must listen on loopback port 80"
        raise SystemExit(msg)
    if allowed_hosts.split(",") != sorted(PROXY_ALLOWED_HOSTS):
        msg = "NOHIKI_PROXY_ALLOWED_HOSTS must declare both public routes"
        raise SystemExit(msg)

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    with Server(("127.0.0.1", 80), _GatewayProxy) as server:
        server.serve_forever()
    return 0


def main() -> int:
    """Dispatch the selected API verification mode."""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("api", "proxy"))
    return run_api() if parser.parse_args().mode == "api" else run_proxy()


if __name__ == "__main__":
    raise SystemExit(main())
