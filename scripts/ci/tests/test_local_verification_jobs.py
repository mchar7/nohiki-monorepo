"""Contracts for the local API and browser verification runners and Flux DAG."""

from __future__ import annotations

import ast
import functools
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_API_RUNNER = _ROOT / "tests" / "api" / "run_k8s_verification.py"
_API_DOCKERFILE = _ROOT / "tests" / "Dockerfile.api-runner"
_FRONTEND = _ROOT / "typescript" / "apps" / "frontend"
_BROWSER_DOCKERFILE = _FRONTEND / "Dockerfile.playwright-runner"
_E2E_DIR = _FRONTEND / "e2e"
_BROWSER_CONFIG = _FRONTEND / "e2e" / "playwright.k8s.config.ts"
_BROWSER_RUNNER = _FRONTEND / "e2e" / "run-k8s-verification.mjs"
_API_FIXTURES = _ROOT / "tests" / "api" / "conftest.py"
_BROWSER_SETUP = _FRONTEND / "e2e" / "global-setup.ts"
_BROWSER_TEARDOWN = _FRONTEND / "e2e" / "global-teardown.ts"
_VERIFICATION = _ROOT / "infra" / "k8s" / "gitops" / "verification"
_GITIGNORE = _ROOT / ".gitignore"
_LOCAL_CLUSTER = _ROOT / "infra" / "k8s" / "gitops" / "clusters" / "local"
_GATEWAY_DNS = "nohiki-gateway.nohiki.svc.cluster.local:80"
_PUBLIC_ORIGIN = "http://nohiki.localhost"
_FORBIDDEN_RUNTIME_TARGETS = (
    "host.docker.internal",
    "127.0.0.1:5173",
    ":8000",
    "bff-service",
    "frontend-service",
)
_DECLARED_INPUT_ANNOTATIONS = {
    "verification.nohiki.dev/revision",
    "verification.nohiki.dev/runner-image-digest",
    "verification.nohiki.dev/gateway-url",
    "verification.nohiki.dev/suite-digest",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


@functools.cache
def _stage_documents(lane: str) -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        [
            "helm",
            "template",
            f"nohiki-{lane}-verification",
            str(_VERIFICATION),
            "--namespace",
            "nohiki-verification",
            "--set-string",
            f"stage={lane}",
            "--set-string",
            f"global.imageDigests.api-verification-runner=sha256:{'a' * 64}",
            "--set-string",
            f"global.imageDigests.playwright-verification-runner=sha256:{'b' * 64}",
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _job(lane: str) -> dict[str, Any]:
    matches = [document for document in _stage_documents(lane) if document.get("kind") == "Job"]
    assert len(matches) == 1, (
        lane,
        [document.get("kind") for document in _stage_documents(lane)],
    )
    return matches[0]


def _pod_spec(lane: str) -> dict[str, Any]:
    return _job(lane)["spec"]["template"]["spec"]


def _container(lane: str, name: str) -> dict[str, Any]:
    spec = _pod_spec(lane)
    containers = [*spec.get("initContainers", []), *spec.get("containers", [])]
    matches = [container for container in containers if container["name"] == name]
    assert len(matches) == 1, (lane, name, [item["name"] for item in containers])
    return matches[0]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_playwright_list(output: str) -> tuple[set[str], int]:
    total = re.search(r"(?:^|\n)Total:\s+([0-9]+) tests? in [0-9]+ files?\n?\Z", output)
    assert total is not None, f"playwright --list output is incomplete: missing final Total line\n{output}"
    collected = {match.group(1) for match in re.finditer(r"(?:^|\s)([\w-]+\.spec\.ts):[0-9]+:[0-9]+", output)}
    return collected, int(total.group(1))


def _import_playwright_configs(
    *artifact_dirs: str | None,
) -> tuple[dict[str, Any], ...]:
    script = f"""
const results = [];
for (const [index, artifactDir] of {json.dumps(artifact_dirs)}.entries()) {{
  if (artifactDir === null) delete process.env.E2E_ARTIFACT_DIR;
  else process.env.E2E_ARTIFACT_DIR = artifactDir;
  const config = (await import({_BROWSER_CONFIG.as_uri()!r} + `?probe=${{index}}`)).default;
  const reporters = Object.fromEntries(
    config.reporter.filter((entry) => entry.length > 1).map(([name, options]) => [name, options]),
  );
  results.push({{
    outputDir: config.outputDir,
    htmlReport: reporters.html.outputFolder,
    jsonReport: reporters.json.outputFile,
  }});
}}
console.log(JSON.stringify(results));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=os.environ | {"E2E_BASE_URL": _PUBLIC_ORIGIN},
    )
    configs = json.loads(result.stdout)
    assert isinstance(configs, list)
    assert all(isinstance(config, dict) for config in configs)
    return tuple(configs)


def _assert_hardened(container: dict[str, Any], *, bind_service: bool = False) -> None:
    context = container["securityContext"]
    assert context["allowPrivilegeEscalation"] is False
    assert context["readOnlyRootFilesystem"] is True
    assert context["runAsNonRoot"] is True
    expected_add = ["NET_BIND_SERVICE"] if bind_service else []
    assert context["capabilities"] == {"drop": ["ALL"], "add": expected_add}


def test_api_runner_collects_the_authoritative_suite_and_fails_closed() -> None:
    text = _text(_API_RUNNER)
    ast.parse(text)
    assert "tests/api" in text
    assert "--collect-only" in text
    assert "--junitxml" in text
    assert 'Path("/artifacts/api")' in text
    for artifact in ("collection.txt", "pytest.log", "junit.xml", "result.json"):
        assert artifact in text
    assert re.search(r'counts\["tests"\]\s*==\s*collected', text)
    for outcome in ("failures", "errors", "skipped", "xfail"):
        assert outcome in text, f"runner does not account for {outcome}"
    assert "finally:" in text
    assert 'session.delete(f"{base_url}/api/v1/account"' in text
    assert text.count("_cleanup_identities(base_url)") >= 2
    assert "E2E_BASE_URL" in text
    assert 'Server(("127.0.0.1", 80)' in text
    for forbidden in _FORBIDDEN_RUNTIME_TARGETS:
        assert forbidden not in text


def test_api_collection_is_nonzero_and_reports_the_exact_current_count(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class CollectionCounter:
        count: int | None = None

        def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
            self.count = len(items)

    counter = CollectionCounter()
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    exit_code = pytest.main(
        [
            "-p",
            "pytest_asyncio.plugin",
            "-p",
            "pytest_timeout",
            str(_ROOT / "tests" / "api"),
            "--collect-only",
            "-q",
        ],
        plugins=[counter],
    )
    output = capsys.readouterr().out
    matches = {
        *(int(value) for value in re.findall(r"(?m)^collected ([0-9]+) items$", output)),
        *(int(value) for value in re.findall(r"([0-9]+) tests? collected", output)),
    }
    assert exit_code == pytest.ExitCode.OK, output
    assert counter.count is not None
    assert matches == {counter.count}, output
    assert counter.count > 0


def test_playwright_config_is_cluster_only_same_origin_and_unmasked() -> None:
    text = _text(_BROWSER_CONFIG)
    assert re.search(r"webServer\s*:\s*undefined", text)
    assert re.search(r"retries\s*:\s*0\b", text)
    assert re.search(r"workers\s*:\s*1\b", text)
    assert "E2E_BASE_URL" in text
    assert _PUBLIC_ORIGIN in text
    assert re.search(r"trace\s*:\s*['\"](?:on|retain-on-failure)['\"]", text)
    assert re.search(r"screenshot\s*:\s*['\"]only-on-failure['\"]", text)
    assert re.search(r"video\s*:\s*['\"](?:on|retain-on-failure)['\"]", text)
    for forbidden in ("vite", "5173", "5174", "8000", "docker", "compose"):
        assert forbidden.lower() not in text.lower()


# `playwright.k8s.config.ts` imports `@playwright/test`, a bare specifier ESM resolves at link
# time, so evaluating it needs the installed workspace and not just a `node` binary.
@pytest.mark.requires_node_modules
def test_playwright_artifacts_have_one_canonical_e2e_root() -> None:
    default, overridden = _import_playwright_configs(None, "/artifacts/playwright")
    assert default == {
        "outputDir": ".output/k8s/results",
        "htmlReport": ".output/k8s/report",
        "jsonReport": ".output/k8s/results.json",
    }
    resolved = {name: (_E2E_DIR / path).resolve() for name, path in default.items()}
    expected_root = (_E2E_DIR / ".output" / "k8s").resolve()
    assert resolved == {
        "outputDir": expected_root / "results",
        "htmlReport": expected_root / "report",
        "jsonReport": expected_root / "results.json",
    }
    assert all("e2e/e2e" not in path.as_posix() for path in resolved.values())

    pvc_root = "/artifacts/playwright"
    assert overridden == {
        "outputDir": f"{pvc_root}/results",
        "htmlReport": f"{pvc_root}/report",
        "jsonReport": f"{pvc_root}/results.json",
    }


@pytest.mark.requires_node_modules
def test_playwright_rejects_noncanonical_relative_artifact_override() -> None:
    script = f"await import({_BROWSER_CONFIG.as_uri()!r});"
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "E2E_BASE_URL": _PUBLIC_ORIGIN,
            "E2E_ARTIFACT_DIR": "relative/artifacts",
        },
    )
    assert result.returncode != 0
    assert "E2E_ARTIFACT_DIR must be an absolute path" in result.stderr


def test_playwright_output_is_ignored_without_a_nested_source_path() -> None:
    ignore_rules = {
        line.strip() for line in _text(_GITIGNORE).splitlines() if line.strip() and not line.lstrip().startswith("#")
    }
    assert "typescript/apps/frontend/e2e/.output/" in ignore_rules
    assert "e2e/.output" not in _text(_BROWSER_CONFIG)


def test_browser_runner_accounts_for_every_outcome_and_retains_artifacts() -> None:
    text = _text(_BROWSER_RUNNER)
    for token in ("--list", "result.json", "report", "results", "console", "network"):
        assert token in text
    for outcome in ("failed", "skipped", "interrupted", "timedOut", "retried"):
        assert outcome.lower() in text.lower(), f"browser runner ignores {outcome}"
    assert "playwright.k8s.config.ts" in text
    assert "--grep" not in text
    assert "--project" not in text
    assert "preCleanPrimaryIdentity" in text
    assert "cleanupPrimaryIdentity" in text
    assert re.search(r"valid\s*=\s*preCleanupSucceeded", text)
    assert "&& cleanupSucceeded" in text


def test_playwright_list_parser_rejects_incomplete_capture() -> None:
    output = "Listing tests:\n  [chromium] > smoke.spec.ts:7:1 > smoke\n"
    with pytest.raises(AssertionError, match="missing final Total line"):
        _parse_playwright_list(output)


@pytest.mark.requires_node_modules
def test_playwright_collects_every_authoritative_journey_file() -> None:
    # Playwright force-exits before asynchronous pipe writes drain, while regular-file writes are synchronous.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout:
        result = subprocess.run(
            [
                "pnpm",
                "--filter",
                "nohiki-frontend",
                "exec",
                "playwright",
                "test",
                "--config=e2e/playwright.k8s.config.ts",
                "--list",
                "--reporter=list",
            ],
            cwd=_ROOT,
            check=True,
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ | {"E2E_BASE_URL": _PUBLIC_ORIGIN},
        )
        stdout.seek(0)
        output = stdout.read()
    authoritative = {path.name for path in (_FRONTEND / "e2e" / "journeys").glob("*.spec.ts")}
    collected, total = _parse_playwright_list(output)
    assert authoritative
    assert collected == authoritative, f"playwright --list output:\n{output}\n{result.stderr}"
    assert total > len(authoritative)


def test_runner_images_are_pinned_nonroot_and_copy_whole_suites() -> None:
    api = _text(_API_DOCKERFILE)
    browser = _text(_BROWSER_DOCKERFILE)
    for path, text in ((_API_DOCKERFILE, api), (_BROWSER_DOCKERFILE, browser)):
        assert re.search(r"^FROM\s+\S+@sha256:[0-9a-f]{64}(?:\s|$)", text, re.MULTILINE), path
        assert re.search(r"^USER\s+(?!0(?:\s|$)|root(?:\s|$))", text, re.MULTILINE), path
        assert "latest" not in text.lower()
    assert "tests/api" in api
    assert "run_k8s_verification.py" in api
    assert "typescript/apps/frontend" in browser
    assert "run-k8s-verification.mjs" in browser


def test_jobs_use_only_the_gateway_proxy_and_hardened_runners() -> None:
    for lane, runner_name in (
        ("api", "api-verification"),
        ("playwright", "playwright-verification"),
    ):
        job = _job(lane)
        spec = _pod_spec(lane)
        assert spec["restartPolicy"] == "Never"
        assert job["spec"]["backoffLimit"] == 0
        assert job["spec"]["activeDeadlineSeconds"] > 0
        runner = _container(lane, runner_name)
        proxy = _container(lane, "gateway-proxy")
        _assert_hardened(runner)
        _assert_hardened(proxy, bind_service=True)
        assert proxy["restartPolicy"] == "Always"
        assert proxy in spec["initContainers"]
        rendered = yaml.safe_dump(job)
        assert _GATEWAY_DNS in rendered
        assert _PUBLIC_ORIGIN in rendered
        for probe_name in ("startupProbe", "readinessProbe"):
            probe = proxy[probe_name]["httpGet"]
            assert (probe["host"], probe["port"], probe["path"]) == (
                "127.0.0.1",
                80,
                "/api/ping",
            )
        assert "nohiki.localhost" in rendered
        assert "/api/ping" in rendered
        for forbidden in _FORBIDDEN_RUNTIME_TARGETS:
            assert forbidden not in rendered
        digest = "a" * 64 if lane == "api" else "b" * 64
        assert runner["image"] == (f"localhost:5000/{lane}-verification-runner@sha256:{digest}")


def test_jobs_retain_results_and_completed_objects_until_declared_input_changes() -> None:
    for lane in ("api", "playwright"):
        job = _job(lane)
        assert "ttlSecondsAfterFinished" not in job["spec"]
        annotations = job["metadata"]["annotations"]
        assert annotations.keys() >= _DECLARED_INPUT_ANNOTATIONS
        assert all(annotations[key] for key in _DECLARED_INPUT_ANNOTATIONS)
        pod_spec = _pod_spec(lane)
        claims = [
            volume["persistentVolumeClaim"]["claimName"]
            for volume in pod_spec["volumes"]
            if "persistentVolumeClaim" in volume
        ]
        assert claims, f"{lane} artifacts are not persistent"
        pvcs = [document for document in _stage_documents(lane) if document.get("kind") == "PersistentVolumeClaim"]
        assert len(pvcs) == 1
        assert claims == [pvcs[0]["metadata"]["name"]]
        runner = _container(lane, f"{lane}-verification")
        assert any(mount["mountPath"] == "/artifacts" for mount in runner["volumeMounts"])
        kustomization = _load(_VERIFICATION / lane / "kustomization.yaml")
        assert kustomization["resources"] == ["helmrelease.yaml"]


def test_flux_orders_health_then_api_then_browser_and_health_checks_jobs() -> None:
    api = _load(_LOCAL_CLUSTER / "verification-api.yaml")
    browser = _load(_LOCAL_CLUSTER / "verification-playwright.yaml")
    assert api["spec"]["dependsOn"] == [{"name": "health-verification"}]
    assert browser["spec"]["dependsOn"] == [{"name": "api-verification"}]
    for lane, manifest, release_name, expected_job_name in (
        ("api", api, "nohiki-api-verification", _job("api")["metadata"]["name"]),
        (
            "playwright",
            browser,
            "nohiki-playwright-verification",
            _job("playwright")["metadata"]["name"],
        ),
    ):
        spec = manifest["spec"]
        assert spec["wait"] is True
        assert spec["prune"] is False
        assert spec.get("force", False) is False
        assert spec["healthChecks"] == [
            {
                "apiVersion": "helm.toolkit.fluxcd.io/v2",
                "kind": "HelmRelease",
                "name": release_name,
                "namespace": "flux-system",
            },
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "name": expected_job_name,
                "namespace": "nohiki-verification",
            },
        ]
        release = _load(_VERIFICATION / lane / "helmrelease.yaml")
        assert release["spec"]["upgrade"] == {
            "force": True,
            "remediation": {"retries": 0},
        }
        assert release["spec"]["values"] == {"stage": lane}
        assert release["spec"]["valuesFrom"] == [
            {
                "kind": "ConfigMap",
                "name": "nohiki-image-digests",
                "valuesKey": "values.yaml",
                "optional": False,
            }
        ]
        assert spec["timeout"]
        assert spec["retryInterval"]


def test_local_root_declares_each_verification_stage_once() -> None:
    root = _load(_LOCAL_CLUSTER / "kustomization.yaml")
    resources = root["resources"]
    assert resources.count("verification-api.yaml") == 1
    assert resources.count("verification-playwright.yaml") == 1
    assert resources.index("verification-api.yaml") < resources.index("verification-playwright.yaml")


def test_synthetic_identities_have_fail_closed_finalizers() -> None:
    api = _text(_API_FIXTURES)
    assert "cleanup_synthetic_identities" in api
    assert "autouse=True" in api
    assert "cleanup_client.login(email, password)" in api
    assert "cleanup_client.delete_account()" in api
    assert "tuple(cleanup_clients)" in api
    assert "pytest.fail" in api

    setup = _text(_BROWSER_SETUP)
    teardown = _text(_BROWSER_TEARDOWN)
    config = _text(_BROWSER_CONFIG)
    assert re.search(r"function\s+generateUniqueEmail\(\):\s*string\s*\{", setup)
    assert re.search(r"return\s+`[^`]*\$\{Date\.now\(\)\}[^`]*`;", setup)
    assert "const uniqueEmail = generateUniqueEmail();" in setup
    assert "fillRegistrationForm(page, uniqueEmail)" in setup
    assert "globalTeardown: './global-teardown.ts'" in config
    assert "PRIMARY_USER_STORAGE_STATE_PATH" in teardown
    assert "method: 'DELETE'" in teardown
    assert "/api/v1/account" in teardown
    assert "await rm(storageStatePath, { force: true })" in teardown
    assert re.search(r"try\s*\{.*?finally\s*\{\s*await rm\(storageStatePath", teardown, re.DOTALL)
    assert "password" not in teardown.lower()
    assert "token" not in teardown.lower()
