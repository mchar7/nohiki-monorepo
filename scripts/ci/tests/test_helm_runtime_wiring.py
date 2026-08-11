"""Render-level Helm wiring contracts.

Database DSN expectations come from rendered migration Jobs rather than a
second service list. S3 URL assertions exercise the application's public URL
rules at the environment boundary.

Kafka scaler expectations are derived independently from production startup:
the test follows imports executed from each service's ``main`` module, locates
reachable ``message_handler`` decorators, and evaluates their topic and group
expressions from service settings defaults. Rendered ``(topic, consumerGroup)``
pairs must exactly equal that startup-reachable inventory.
"""

from __future__ import annotations

import ast
import subprocess
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from _documents import load_mapping, mapping_at, string_at
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_KAFKA_SCALER_SERVICES = {
    "nohiki-doc-content-service",
    "nohiki-doc-process-service",
    "nohiki-doc-template-service",
    "nohiki-job-correlation-evaluation-service",
    "nohiki-job-ingest-discovery-service",
    "nohiki-job-query-composition-service",
    "nohiki-job-storage-service",
    "nohiki-ml-compute-service",
    "nohiki-ml-gateway-service",
    "nohiki-skill-graph-service",
    "nohiki-user-entitlement-service",
    "nohiki-user-pref-service",
    "nohiki-user-upload-service",
}
_TOPICS_PATH = _ROOT / "backend" / "libs" / "nohiki-kafka-client" / "src" / "nohiki_kafka_client" / "topics.py"


def _topic_literals() -> dict[str, str]:
    tree = ast.parse(_TOPICS_PATH.read_text(encoding="utf-8"))
    literals: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            literals[target.id] = node.value.value
    return literals


_TOPIC_LITERALS = _topic_literals()


def _service_module_path(source: Path, package: str, module: str) -> Path | None:
    if module == package:
        candidates = (source / "__init__.py",)
    else:
        relative = module.removeprefix(f"{package}.").replace(".", "/")
        candidates = (source / f"{relative}.py", source / relative / "__init__.py")
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _executed_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    imports: list[ast.Import | ast.ImportFrom] = []

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            # Type-only imports are not executed by production startup.
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                continue
            if isinstance(node, ast.Import | ast.ImportFrom):
                imports.append(node)
                continue
            for field, value in ast.iter_fields(node):
                if field in {"body", "orelse", "finalbody"} and isinstance(value, list):
                    visit(value)
                elif field == "handlers":
                    for handler in value:
                        visit(handler.body)

    visit(tree.body)
    return imports


def _startup_modules(service: str) -> dict[str, ast.Module]:
    package = service.replace("-", "_")
    source = _ROOT / "backend" / "services" / service / "src" / package
    pending = [f"{package}.main"]
    modules: dict[str, ast.Module] = {}

    while pending:
        module = pending.pop()
        path = _service_module_path(source, package, module)
        if path is None or module in modules:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules[module] = tree
        current_package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]

        for node in _executed_imports(tree):
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            else:
                if node.level:
                    parts = current_package.split(".")
                    prefix = ".".join(parts[: len(parts) - node.level + 1])
                    base = f"{prefix}.{node.module}" if node.module else prefix
                else:
                    base = node.module or ""
                candidates = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            pending.extend(
                candidate
                for candidate in candidates
                if candidate.startswith(package) and _service_module_path(source, package, candidate)
            )
    return modules


def _service_settings(service: str) -> tuple[dict[str, str], ast.expr | None]:
    package = service.replace("-", "_")
    source = _ROOT / "backend" / "services" / service / "src" / package
    facts = {"service_name": service}
    consumer_group_property: ast.expr | None = None

    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                value = node.value
                if isinstance(target, ast.Name):
                    if target.id == "service_name" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                        facts["service_name"] = value.value
                    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
                        default = next(
                            (
                                keyword.value.value
                                for keyword in value.keywords
                                if keyword.arg == "default" and isinstance(keyword.value, ast.Constant)
                            ),
                            None,
                        )
                        if isinstance(default, str):
                            facts[target.id] = default
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "kafka_consumer_group":
                returned = next((item for item in ast.walk(node) if isinstance(item, ast.Return)), None)
                if returned is not None:
                    consumer_group_property = returned.value
    return facts, consumer_group_property


def _handler_value(
    expression: ast.expr,
    assignments: dict[str, ast.expr],
    base_group: str,
    facts: dict[str, str],
    consumer_group_property: ast.expr | None,
) -> str:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    if isinstance(expression, ast.Name):
        return _handler_value(
            assignments[expression.id],
            assignments,
            base_group,
            facts,
            consumer_group_property,
        )
    if isinstance(expression, ast.JoinedStr):
        literal_parts: list[str] = []
        for value in expression.values:
            if isinstance(value, ast.FormattedValue):
                literal_parts.append(
                    _handler_value(value.value, assignments, base_group, facts, consumer_group_property)
                )
            else:
                assert isinstance(value, ast.Constant)
                assert isinstance(value.value, str)
                literal_parts.append(value.value)
        return "".join(literal_parts)
    if isinstance(expression, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = expression
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        dotted = ".".join(reversed(parts))
        value: str | None = None
        if dotted == "settings.kafka.consumer_group":
            value = base_group
        elif dotted == "settings.kafka_consumer_group":
            value = (
                base_group
                if consumer_group_property is None
                else _handler_value(consumer_group_property, assignments, base_group, facts, None)
            )
        elif dotted.startswith("settings.kafka."):
            value = facts[dotted.rsplit(".", 1)[1]]
        elif dotted in {"settings.service_name", "self.service_name"}:
            value = facts["service_name"]
        elif dotted.startswith("Topics."):
            value = _TOPIC_LITERALS[dotted.split(".", 1)[1]]
        if value is not None:
            return value
    unsupported = f"unsupported handler registration expression: {ast.dump(expression)}"
    raise AssertionError(unsupported)


def _startup_handler_pairs(service: str, base_group: str) -> set[tuple[str, str]]:
    facts, consumer_group_property = _service_settings(service)
    pairs: set[tuple[str, str]] = set()
    for tree in _startup_modules(service).values():
        assignments: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign | ast.AnnAssign):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if isinstance(target, ast.Name) and node.value is not None:
                    assignments[target.id] = node.value

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    not isinstance(decorator, ast.Call)
                    or not isinstance(decorator.func, ast.Attribute)
                    or decorator.func.attr != "message_handler"
                ):
                    continue
                group_expression = next(keyword.value for keyword in decorator.keywords if keyword.arg == "group_id")
                pairs.add(
                    (
                        _handler_value(
                            decorator.args[0],
                            assignments,
                            base_group,
                            facts,
                            consumer_group_property,
                        ),
                        _handler_value(
                            group_expression,
                            assignments,
                            base_group,
                            facts,
                            consumer_group_property,
                        ),
                    )
                )
    return pairs


_WARM_KAFKA_SCALERS = {
    "nohiki-job-storage-service",
    "nohiki-ml-compute-service",
}
_LIFECYCLE_EXCLUSIONS = {
    "nohiki-job-ingest-enrichment-service",
    "nohiki-job-ingest-schedule-service",
    "nohiki-notification-service",
}


def _render(values_name: str, tmp_path: Path, *extra_args: str) -> tuple[dict, ...]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    command.extend(runtime_eso_args(environment))
    command.extend(extra_args)
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _deployments(documents: tuple[dict, ...]) -> dict[str, dict]:
    return {document["metadata"]["name"]: document for document in documents if document.get("kind") == "Deployment"}


def _db_backed_services(documents: tuple[dict, ...]) -> set[str]:
    """Services with a ``{svc}-db-migrate`` Job -- the source of truth for DB-backed workloads."""
    return {
        document["metadata"]["name"].removesuffix("-db-migrate")
        for document in documents
        if document.get("kind") == "Job" and document["metadata"]["name"].endswith("-db-migrate")
    }


def _migration_secret(documents: tuple[dict, ...], svc: str) -> str:
    """Name of the Secret the migration Job reads its DSN from (matched by the Deployment)."""
    job = next(
        document
        for document in documents
        if document.get("kind") == "Job" and document["metadata"]["name"] == f"{svc}-db-migrate"
    )
    for container in job["spec"]["template"]["spec"]["containers"]:
        for entry in container.get("env", []):
            reference = entry.get("valueFrom", {}).get("secretKeyRef")
            if reference and entry["name"].startswith("DATABASE"):
                return reference["name"]
    message = f"{svc}-db-migrate Job has no DATABASE_URL secretKeyRef"
    raise AssertionError(message)


def _dsn_reference(deployment: dict) -> tuple[str, str] | None:
    """Return ``(secret_name, key)`` for the ``*DATABASE__DSN`` env, or ``None`` when absent."""
    for container in deployment["spec"]["template"]["spec"]["containers"]:
        for entry in container.get("env", []):
            if entry["name"].endswith("DATABASE__DSN"):
                reference = entry.get("valueFrom", {}).get("secretKeyRef")
                assert reference is not None, (
                    f"{deployment['metadata']['name']} {entry['name']} must come from a Secret, not an inline value"
                )
                return reference["name"], reference["key"]
    return None


def _s3_public_urls(documents: tuple[dict, ...]) -> dict[str, str]:
    """Map Deployment name -> its ``*S3__PUBLIC_URL`` env value (inline values only)."""
    urls: dict[str, str] = {}
    for name, deployment in _deployments(documents).items():
        for container in deployment["spec"]["template"]["spec"]["containers"]:
            for entry in container.get("env", []):
                if entry["name"].endswith("S3__PUBLIC_URL") and "value" in entry:
                    urls[name] = entry["value"]
    return urls


def _is_accepted_public_url(value: str, *, allow_http_loopback: bool) -> bool:
    """Mirror ``nohiki_s3_client.S3Settings.validate_public_url`` (kept in sync with the app)."""
    if any(character.isspace() for character in value) or any(delimiter in value for delimiter in "?#\\"):
        return False
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http" or not allow_http_loopback:
        return False
    host = parsed.hostname.strip("[]").rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = False
    return loopback


def test_local_db_backed_deployments_receive_dsn_from_credential_secret(
    tmp_path: Path,
) -> None:
    documents = _render("values.local.yaml", tmp_path)
    db_services = _db_backed_services(documents)
    assert db_services, "expected the local render to contain DB-backed services"
    deployments = _deployments(documents)

    for svc in sorted(db_services):
        deployment = deployments.get(f"nohiki-{svc}")
        assert deployment is not None, f"missing Deployment nohiki-{svc} for DB-backed service"
        reference = _dsn_reference(deployment)
        assert reference is not None, f"nohiki-{svc} must receive DATABASE__DSN from its credential Secret"
        secret_name, key = reference
        assert secret_name == f"{svc}-db-credentials"
        # Same Secret the migration Job connects with, so the deployment reaches the migrated schema.
        assert secret_name == _migration_secret(documents, svc)
        assert key == "dsn"


def test_local_non_db_workloads_never_receive_dsn(tmp_path: Path) -> None:
    documents = _render("values.local.yaml", tmp_path)
    db_services = _db_backed_services(documents)
    deployments = _deployments(documents)

    # Sentinel: a known non-DB first-party service must render and stay DSN-free,
    # so this test cannot pass vacuously on a broken render.
    assert "nohiki-ml-gateway-service" in deployments
    assert "ml-gateway-service" not in db_services

    for name, deployment in deployments.items():
        if name.removeprefix("nohiki-") in db_services:
            continue
        assert _dsn_reference(deployment) is None, f"non-DB workload {name} must not receive DATABASE__DSN"


def test_local_s3_public_url_is_accepted_loopback_http(tmp_path: Path) -> None:
    documents = _render("values.local.yaml", tmp_path)
    assert "nohiki-bff-service" in _deployments(documents)
    value = _s3_public_urls(documents).get("nohiki-bff-service")
    assert value == "http://s3.nohiki.localhost:8080"
    assert _is_accepted_public_url(value, allow_http_loopback=True), (
        f"{value!r} must be an accepted RFC localhost HTTP public URL"
    )
    assert not _is_accepted_public_url(
        "http://storage.example.com:8080",
        allow_http_loopback=True,
    )


def test_staging_and_production_s3_public_urls_are_not_insecure_http(
    tmp_path: Path,
) -> None:
    prod = _render("values.prod.yaml", tmp_path)
    # Production must publish an HTTPS presign endpoint (concrete anchor for this guardrail).
    assert _s3_public_urls(prod).get("nohiki-bff-service") == "https://nohikiprod.blob.core.windows.net"

    for values_name in ("values.staging.yaml", "values.prod.yaml"):
        documents = prod if values_name == "values.prod.yaml" else _render(values_name, tmp_path)
        for name, value in _s3_public_urls(documents).items():
            assert value.startswith("https://"), f"{name} S3 public URL must use HTTPS in {values_name}, got {value!r}"


def test_kafka_scalers_match_startup_reachable_topic_groups(tmp_path: Path) -> None:
    for values_name, expected_maximum in (
        ("values.local.yaml", 1),
        ("values.dev.yaml", 3),
        ("values.staging.yaml", 3),
        ("values.prod.yaml", 3),
    ):
        documents = _render(values_name, tmp_path)
        scalers = {
            document["metadata"]["name"]: document for document in documents if document.get("kind") == "ScaledObject"
        }
        deployments = _deployments(documents)
        assert set(scalers) == _KAFKA_SCALER_SERVICES, values_name
        assert not set(scalers) & _LIFECYCLE_EXCLUSIONS
        assert not any(
            document.get("apiVersion", "").startswith("http.keda.sh/") or document.get("kind") == "HTTPInterceptorProxy"
            for document in documents
        )

        for name, scaler in scalers.items():
            spec = scaler["spec"]
            triggers = [trigger for trigger in spec["triggers"] if trigger["type"] == "kafka"]
            environment = deployments[name]["spec"]["template"]["spec"]["containers"][0]["env"]
            base_group = next(
                entry["value"] for entry in environment if entry["name"].endswith("KAFKA__CONSUMER_GROUP")
            )
            expected_pairs = _startup_handler_pairs(name.removeprefix("nohiki-"), base_group)
            rendered_pairs = {
                (trigger["metadata"]["topic"], trigger["metadata"]["consumerGroup"]) for trigger in triggers
            }
            assert rendered_pairs == expected_pairs, (
                values_name,
                name,
                {"missing": expected_pairs - rendered_pairs, "extra": rendered_pairs - expected_pairs},
            )
            assert spec["minReplicaCount"] == (1 if name in _WARM_KAFKA_SCALERS else 0), (values_name, name)
            assert spec["maxReplicaCount"] == expected_maximum
            if name in _WARM_KAFKA_SCALERS:
                assert "idleReplicaCount" not in spec
            else:
                assert spec["idleReplicaCount"] == 0


def test_local_kafka_scalers_wait_for_bootstrap_service(tmp_path: Path) -> None:
    documents = _render("values.local.yaml", tmp_path)
    gates = [
        document
        for document in documents
        if document.get("kind") == "Job"
        and document.get("metadata", {}).get("name") == "nohiki-kafka-scaler-bootstrap-gate"
    ]
    assert len(gates) == 1

    gate = gates[0]
    assert gate["metadata"]["annotations"] == {
        "helm.sh/hook": "post-install,post-upgrade",
        "helm.sh/hook-delete-policy": "before-hook-creation,hook-succeeded,hook-failed",
        "helm.sh/hook-weight": "-10",
    }
    container = gate["spec"]["template"]["spec"]["containers"][0]
    image = mapping_at(load_mapping(_CHART / "values.yaml"), "opentelemetry-operator", "testFramework", "image")
    assert container["image"] == f"{string_at(image, 'repository')}:{string_at(image, 'tag')}"
    assert container["env"] == [
        {"name": "KAFKA_BOOTSTRAP_HOST", "value": "nohiki-kafka-kafka-bootstrap"},
        {"name": "KAFKA_BOOTSTRAP_PORT", "value": "9092"},
    ]
    assert "nslookup" not in container["args"][0]
    assert 'until nc -z -w 2 "${KAFKA_BOOTSTRAP_HOST}" "${KAFKA_BOOTSTRAP_PORT}"' in container["args"][0]

    scalers = [document for document in documents if document.get("kind") == "ScaledObject"]
    assert {scaler["metadata"]["name"] for scaler in scalers} == _KAFKA_SCALER_SERVICES
    assert all(
        scaler["metadata"]["annotations"]
        == {
            "helm.sh/hook": "post-install,post-upgrade",
            "helm.sh/hook-delete-policy": "before-hook-creation,hook-failed",
            "helm.sh/hook-weight": "0",
        }
        for scaler in scalers
    )

    for values_name in ("values.dev.yaml", "values.staging.yaml", "values.prod.yaml"):
        cloud_documents = _render(values_name, tmp_path)
        assert not any(
            document.get("metadata", {}).get("name") == "nohiki-kafka-scaler-bootstrap-gate"
            for document in cloud_documents
        )
        assert not any(
            document.get("metadata", {}).get("name") == "nohiki-kafka-scaler-hook-cleanup"
            for document in cloud_documents
        )
        assert all(
            "helm.sh/hook" not in scaler.get("metadata", {}).get("annotations", {})
            for scaler in cloud_documents
            if scaler.get("kind") == "ScaledObject"
        )


def test_local_scaler_hook_cleanup_covers_upgrade_uninstall_and_opt_out(tmp_path: Path) -> None:
    cleanup_name = "nohiki-kafka-scaler-hook-cleanup"
    hook_resources = [
        document
        for document in _render("values.local.yaml", tmp_path)
        if document.get("metadata", {}).get("name") == cleanup_name
    ]
    assert {document["kind"] for document in hook_resources} == {
        "ServiceAccount",
        "Role",
        "RoleBinding",
        "Job",
    }
    expected_weights = {
        "ServiceAccount": "-30",
        "Role": "-30",
        "RoleBinding": "-20",
        "Job": "-10",
    }
    for resource in hook_resources:
        annotations = resource["metadata"]["annotations"]
        assert annotations["helm.sh/hook"] == "pre-upgrade,pre-delete"
        assert annotations["helm.sh/hook-delete-policy"] == ("before-hook-creation,hook-succeeded,hook-failed")
        assert annotations["helm.sh/hook-weight"] == expected_weights[resource["kind"]]

    role = next(resource for resource in hook_resources if resource["kind"] == "Role")
    assert role["rules"] == [
        {
            "apiGroups": ["keda.sh"],
            "resources": ["scaledobjects"],
            "verbs": ["delete", "deletecollection", "get", "list"],
        }
    ]
    cleanup_job = next(resource for resource in hook_resources if resource["kind"] == "Job")
    assert cleanup_job["spec"]["activeDeadlineSeconds"] == 120
    assert cleanup_job["spec"]["backoffLimit"] == 0
    pod_spec = cleanup_job["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == cleanup_name
    cleanup_container = pod_spec["containers"][0]
    cleanup_command = cleanup_container["args"][0]
    assert "kubectl delete scaledobjects.keda.sh" in cleanup_command
    assert "app.kubernetes.io/instance=${HELM_RELEASE}" in cleanup_command
    assert "app.kubernetes.io/part-of=nohiki" in cleanup_command
    assert "environment=local" in cleanup_command
    assert "--timeout=90s" in cleanup_command
    upgraded = _render("values.local.yaml", tmp_path, "--is-upgrade")
    assert {document["kind"] for document in upgraded if document.get("metadata", {}).get("name") == cleanup_name} == {
        "ServiceAccount",
        "Role",
        "RoleBinding",
        "Job",
    }
    assert all(
        scaler["metadata"]["annotations"]["helm.sh/hook"] == "post-install,post-upgrade"
        for scaler in upgraded
        if scaler.get("kind") == "ScaledObject"
    )

    opted_out = _render(
        "values.local.yaml",
        tmp_path,
        "--is-upgrade",
        "--set",
        "global.kafka.bootstrapGate.enabled=false",
    )
    assert not any(
        document.get("metadata", {}).get("name") == "nohiki-kafka-scaler-bootstrap-gate" for document in opted_out
    )
    assert {document["kind"] for document in opted_out if document.get("metadata", {}).get("name") == cleanup_name} == {
        "ServiceAccount",
        "Role",
        "RoleBinding",
        "Job",
    }
    opted_out_scalers = [document for document in opted_out if document.get("kind") == "ScaledObject"]
    assert {scaler["metadata"]["name"] for scaler in opted_out_scalers} == _KAFKA_SCALER_SERVICES
    assert all("helm.sh/hook" not in scaler["metadata"].get("annotations", {}) for scaler in opted_out_scalers)


def test_kafka_scaler_auth_follows_global_kafka_security(tmp_path: Path) -> None:
    for values_name in ("values.local.yaml", "values.dev.yaml", "values.staging.yaml"):
        documents = _render(values_name, tmp_path)
        triggers = [
            trigger
            for document in documents
            if document.get("kind") == "ScaledObject"
            for trigger in document["spec"]["triggers"]
            if trigger["type"] == "kafka"
        ]
        assert triggers
        assert all("authenticationRef" not in trigger for trigger in triggers)
        assert all("tls" not in trigger["metadata"] for trigger in triggers)

    production = _render("values.prod.yaml", tmp_path)
    triggers = [
        trigger
        for document in production
        if document.get("kind") == "ScaledObject"
        for trigger in document["spec"]["triggers"]
        if trigger["type"] == "kafka"
    ]
    assert triggers
    assert all(trigger["authenticationRef"] == {"name": "nohiki-kafka-auth"} for trigger in triggers)
    assert all(trigger["metadata"]["tls"] == "enable" for trigger in triggers)
