#!/usr/bin/env python3
"""Wait for ordered Flux verification Jobs without mutating the cluster."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any


def kubectl(binary: str, namespace: str, *args: str) -> str:
    """Run kubectl in a namespace and return standard output."""
    result = subprocess.run(
        [binary, "-n", namespace, *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kubectl command failed")
    return result.stdout


def wait_job(binary: str, namespace: str, name: str, container: str, deadline: float) -> dict[str, Any]:
    """Wait for one Job and return its sole passing result contract."""
    while time.monotonic() < deadline:
        job = json.loads(kubectl(binary, namespace, "get", "job", name, "-o", "json"))
        conditions = {
            condition["type"]: condition["status"] for condition in job.get("status", {}).get("conditions", [])
        }
        if conditions.get("Failed") == "True" or job.get("status", {}).get("failed", 0):
            msg = f"{name} failed; inspect its retained Job and artifact PVC"
            raise RuntimeError(msg)
        if conditions.get("Complete") == "True":
            logs = kubectl(binary, namespace, "logs", f"job/{name}", "-c", container)
            results = []
            for line in logs.splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("contract", "").startswith("nohiki-"):
                    results.append(value)
            if len(results) != 1 or results[0].get("status") != "passed":
                msg = f"{name} completed without one deterministic passing result contract"
                raise RuntimeError(msg)
            result = results[0]
            for key in (
                "failures",
                "errors",
                "skipped",
                "xfail",
                "failed",
                "timedOut",
                "interrupted",
                "retried",
            ):
                if int(result.get(key, 0)) != 0:
                    msg = f"{name} masked verification outcome: {key}={result[key]}"
                    raise RuntimeError(msg)
            return result
        time.sleep(2)
    msg = f"timed out waiting for {name}; inspect Flux and Job conditions"
    raise TimeoutError(msg)


def main() -> int:
    """Verify the ordered API and browser Jobs, then emit their result contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="nohiki-verification")
    parser.add_argument("--api-job", default="nohiki-api-verification-v1")
    parser.add_argument("--playwright-job", default="nohiki-playwright-verification-v1")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    binary = os.environ.get("KUBECTL", "kubectl")
    deadline = time.monotonic() + args.timeout_seconds
    api = wait_job(binary, args.namespace, args.api_job, "api-verification", deadline)
    browser = wait_job(binary, args.namespace, args.playwright_job, "playwright-verification", deadline)
    sys.stdout.write(
        json.dumps(
            {
                "contract": "nohiki-verification-dag/v1",
                "status": "passed",
                "api": api,
                "playwright": browser,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
