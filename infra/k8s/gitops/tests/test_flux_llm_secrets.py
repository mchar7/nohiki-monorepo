from __future__ import annotations

import functools
import importlib.util
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
K8S = ROOT / "infra/k8s"
GITOPS = K8S / "gitops"
CHART = K8S / "helm"
BOOTSTRAP = GITOPS / "install/bootstrap.sh"
LOCAL_SECRET = GITOPS / "secrets/local/nohiki-llm-runtime.sops.yaml"
LOCAL_DERIVATIONS = GITOPS / "secrets/local/model-egress-secrets.yaml"
LOCAL_SECRET_CONTRACT = ROOT / "scripts/infra/local_secret_contract.py"
RUNTIME_SECRET = "nohiki-llm-runtime"
PROVIDER_SECRETS = {
    "nohiki-model-egress-anthropic": ("Authorization", "anthropic_api_key"),
    "nohiki-model-egress-openai": ("Authorization", "openai_api_key"),
    "nohiki-model-egress-openrouter": ("Authorization", "openrouter_api_key"),
}
CLIENT_SECRETS = {
    "nohiki-model-egress-client-doc-content": "doc-content",
    "nohiki-model-egress-client-job-ingest-enrichment": "job-ingest-enrichment",
}
AGE_RECIPIENT = re.compile(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}")
SOPS_VALUE = re.compile(r"ENC\[AES256_GCM,data:[^,]+,iv:[^,]+,tag:[^,]+,type:(?:str|bytes)\]")


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), path
    return loaded


@functools.cache
def _provider_credentials(values_name: str) -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("test_llm_local_secret_contract", LOCAL_SECRET_CONTRACT)
    assert spec is not None
    assert spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return contract.enabled_provider_credentials(CHART / "values.yaml", CHART / values_name)


def _documents(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        document for document in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(document, dict)
    )


def _external_targets(
    documents: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, Any]]:
    return {
        document["spec"]["target"]["name"]: document
        for document in documents
        if document.get("kind") == "ExternalSecret"
    }


def test_sops_policy_and_encrypted_manifest_have_exact_metadata() -> None:
    config = _load(ROOT / ".sops.yaml")
    assert set(config) == {"creation_rules"}
    assert len(config["creation_rules"]) == 1
    rule = config["creation_rules"][0]
    assert rule == {
        "path_regex": r"infra/k8s/gitops/secrets/local/.*\.sops\.yaml$",
        "encrypted_regex": "^(data|stringData)$",
        "age": rule["age"],
    }
    assert AGE_RECIPIENT.fullmatch(rule["age"])

    secret = _load(LOCAL_SECRET)
    assert set(secret) == {"apiVersion", "kind", "metadata", "type", "data", "sops"}
    assert secret["apiVersion"] == "v1"
    assert secret["kind"] == "Secret"
    assert secret["metadata"] == {"name": RUNTIME_SECRET, "namespace": "nohiki"}
    assert secret["type"] == "Opaque"
    assert set(secret["data"]) == {f"{credential}_api_key" for credential in _provider_credentials("values.local.yaml")}
    assert "stringData" not in secret
    assert all(
        isinstance(ciphertext, str) and SOPS_VALUE.fullmatch(ciphertext) for ciphertext in secret["data"].values()
    )
    assert secret["sops"]["encrypted_regex"] == "^(data|stringData)$"
    assert SOPS_VALUE.fullmatch(secret["sops"]["mac"])
    assert [entry["recipient"] for entry in secret["sops"]["age"]] == [rule["age"]]


def test_local_manifest_owns_only_source_store_not_derived_secrets() -> None:
    documents = _documents(LOCAL_DERIVATIONS)
    assert [document["kind"] for document in documents] == [
        "ServiceAccount",
        "Role",
        "RoleBinding",
        "SecretStore",
    ]
    assert not _external_targets(documents)
    assert not any(document.get("kind") == "Password" for document in documents)
    raw = LOCAL_DERIVATIONS.read_text(encoding="utf-8")
    assert not any(name in raw for name in (*PROVIDER_SECRETS, *CLIENT_SECRETS))


def test_local_secret_store_can_read_only_encrypted_sources() -> None:
    documents = _documents(LOCAL_DERIVATIONS)
    role = next(document for document in documents if document.get("kind") == "Role")
    secret_rule = next(rule for rule in role["rules"] if rule.get("resources") == ["secrets"])
    assert secret_rule == {
        "apiGroups": [""],
        "resources": ["secrets"],
        "resourceNames": [RUNTIME_SECRET, "nohiki-model-egress-tls-source"],
        "verbs": ["get"],
    }
    store = next(document for document in documents if document.get("kind") == "SecretStore")
    assert store["spec"]["provider"]["kubernetes"]["remoteNamespace"] == "nohiki"
    assert store["spec"]["provider"]["kubernetes"]["auth"] == {"serviceAccount": {"name": "nohiki-local-secret-reader"}}


def test_flux_reconciles_secret_sources_before_consumers() -> None:
    local = _load(GITOPS / "secrets/local/kustomization.yaml")
    assert local["resources"] == [
        "namespace.yaml",
        "nohiki-llm-runtime.sops.yaml",
        "nohiki-model-egress-tls-source.sops.yaml",
        "nohiki-app-secrets.sops.yaml",
        "model-egress-secrets.yaml",
    ]
    cluster = _load(GITOPS / "clusters/local/kustomization.yaml")
    assert cluster["resources"] == [
        "gateway-api-crds.yaml",
        "infrastructure.yaml",
        "registry.yaml",
        "runtime-secrets.yaml",
        "platform.yaml",
        "observability.yaml",
        "health.yaml",
        "verification-api.yaml",
        "verification-playwright.yaml",
    ]
    runtime = _load(GITOPS / "clusters/local/runtime-secrets.yaml")
    assert runtime["spec"]["dependsOn"] == [{"name": "infrastructure"}]
    assert runtime["spec"]["path"] == "./infra/k8s/gitops/secrets/local"
    assert runtime["spec"]["decryption"] == {
        "provider": "sops",
        "secretRef": {"name": "sops-age"},
    }
    assert runtime["spec"]["healthChecks"] == [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "name": RUNTIME_SECRET,
            "namespace": "nohiki",
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "name": "nohiki-model-egress-tls-source",
            "namespace": "nohiki",
        },
        {
            "apiVersion": "external-secrets.io/v1",
            "kind": "SecretStore",
            "name": "nohiki-local-secret-store",
            "namespace": "nohiki",
        },
    ]
    assert _load(GITOPS / "clusters/local/platform.yaml")["spec"]["dependsOn"] == [
        {"name": "runtime-secrets"},
        {"name": "registry"},
    ]


def test_local_secret_owners_are_age_only_and_nonduplicated() -> None:
    local_values = _load(CHART / "values.local.yaml")
    assert local_values["global"]["secrets"]["inlineSecretsEnabled"] is False
    assert local_values["rustfs"]["secret"]["existingSecret"] == ("nohiki-rustfs-credentials")

    local = _load(GITOPS / "secrets/local/kustomization.yaml")
    encrypted_paths = [
        GITOPS / "secrets/local" / resource for resource in local["resources"] if resource.endswith(".sops.yaml")
    ]
    assert {path.name for path in encrypted_paths} == {
        "nohiki-llm-runtime.sops.yaml",
        "nohiki-model-egress-tls-source.sops.yaml",
        "nohiki-app-secrets.sops.yaml",
    }
    identities = [
        (document["metadata"]["namespace"], document["metadata"]["name"])
        for path in encrypted_paths
        for document in _documents(path)
    ]
    assert len(identities) == len(set(identities))


def test_active_platforms_continuously_check_gateway_external_secrets() -> None:
    for cluster, namespace, values_name in (
        ("local", "nohiki", "values.local.yaml"),
        ("dev-aks", "nohiki-dev", "values.dev.yaml"),
        ("staging-aks", "nohiki-staging", "values.staging.yaml"),
        ("prod-aks", "nohiki-prod", "values.prod.yaml"),
    ):
        derived = [
            *(f"nohiki-model-egress-{credential}" for credential in _provider_credentials(values_name)),
            "nohiki-model-egress-tls",
            "nohiki-model-egress-ca",
            *CLIENT_SECRETS,
        ]
        assert "enabled" not in _load(CHART / values_name)["global"].get("modelEgress", {})
        platform = _load(GITOPS / f"clusters/{cluster}/platform.yaml")
        assert platform["spec"]["wait"] is False
        checks = platform["spec"]["healthChecks"]
        assert checks[0] == {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "name": "nohiki",
            "namespace": "flux-system",
        }
        checked_names = [check["name"] for check in checks[1:]]
        assert len(checked_names) == len(set(checked_names))
        assert set(derived) <= set(checked_names)
        assert all(check["namespace"] == namespace for check in checks[1:])
        if cluster == "local":
            assert checked_names[: len(derived)] == derived


def test_managed_environments_define_gateway_only_remote_refs() -> None:
    model_egress = {
        "nohiki-model-egress-openai": {"Authorization": "model-egress-openai-authorization"},
        "nohiki-model-egress-anthropic": {"Authorization": "model-egress-anthropic-authorization"},
        "nohiki-model-egress-openrouter": {"Authorization": "model-egress-openrouter-authorization"},
        "nohiki-model-egress-tls": {
            "tls.crt": "model-egress-tls-crt",
            "tls.key": "model-egress-tls-key",
        },
        "nohiki-model-egress-ca": {"ca.crt": "model-egress-ca-crt"},
    }
    for values_name in ("values.dev.yaml", "values.staging.yaml", "values.prod.yaml"):
        refs = _load(CHART / values_name)["global"]["eso"]["remoteRefs"]
        assert "direct" not in refs
        assert refs["modelEgress"] == model_egress
        assert RUNTIME_SECRET not in refs["shared"]
        assert RUNTIME_SECRET not in yaml.safe_dump(refs)


def test_eso_uses_values_driven_exact_per_purpose_clients() -> None:
    values = _load(CHART / "values.yaml")
    clients = values["global"]["modelEgress"]["clients"]
    assert clients == [
        {
            "name": "doc-content-service",
            "secretName": "nohiki-model-egress-client-doc-content",
            "secretKey": "doc-content",
            "allowedRoutes": ["responses"],
        },
        {
            "name": "job-ingest-enrichment-service",
            "secretName": "nohiki-model-egress-client-job-ingest-enrichment",
            "secretKey": "job-ingest-enrichment",
            "allowedRoutes": ["responses"],
        },
    ]
    assert all("correlation" not in str(value) for client in clients for value in client.values())

    eso = (CHART / "templates/eso-external-secrets.yaml").read_text(encoding="utf-8")
    env = (CHART / "charts/nohiki-common/templates/_env.tpl").read_text(encoding="utf-8")
    assert "$modeName" not in eso
    assert 'dict "shared" $sharedRefs "modelEgress" $modelRefs' in eso
    assert "range $client := $root.Values.global.modelEgress.clients" in eso
    assert "range $client := $modelEgress.clients" in env
    assert "$modelClients" not in eso
    assert "$modelClients" not in env
    assert len(re.findall(r"^kind: Password$", eso, re.MULTILINE)) == 1
    assert eso.count("refreshPolicy: CreatedOnce") == 1
    assert eso.count("creationPolicy: Owner") >= 1
    assert 'printf "nohiki.io/model-egress-route-%s" $route' in eso
    assert "generatorRef:" in eso
    assert not re.search(r"name:\s+nohiki-model-egress-client\s*(?:\n|$)", eso)
    assert "nohiki-model-egress-client-job-correlation-evaluation" not in eso
    assert "$modelEgress.enabled" not in eso
    assert "{{- if or $managed $localStoreName }}" in eso


def test_readiness_hook_covers_gateway_secrets_and_waits_for_current_generation() -> None:
    eso = (CHART / "templates/eso-external-secrets.yaml").read_text(encoding="utf-8")
    assert "$readinessNames = append $readinessNames $name" in eso
    assert "$readinessNames = append $readinessNames $secretName" in eso
    assert "range $credential := $providerCredentials" in eso
    assert "$localProviderNames = append $localProviderNames" in eso
    assert "$readinessNames = concat $localProviderNames (list" in eso
    assert '  "nohiki-model-egress-tls"' in eso
    assert '  "nohiki-model-egress-ca"' in eso
    assert '$readinessNames = list "nohiki-llm-runtime"' not in eso

    assert "kind: Job" in eso
    assert "helm.sh/hook: post-install,post-upgrade" in eso
    assert "helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded" in eso
    assert "activeDeadlineSeconds: 180" in eso
    assert "backoffLimit: 0" in eso
    assert 'resources: ["externalsecrets"]' in eso
    assert "{{- range $name := $readinessNames }}" in eso
    assert 'verbs: ["get"]' in eso

    assert "kubectl get externalsecret" in eso
    assert ".metadata.generation" in eso
    assert ".status.syncedResourceVersion" in eso
    assert '.status.conditions[?(@.type=="Ready")].status' in eso
    assert "generation=\"$(printf '%s\\n' \"${status}\" | sed -n '1p')\"" in eso
    assert "synced_resource_version=\"$(printf '%s\\n' \"${status}\" | sed -n '2p')\"" in eso
    assert "condition_status=\"$(printf '%s\\n' \"${status}\" | sed -n '3p')\"" in eso
    assert '[ -n "${generation}" ]' in eso
    assert '"${generation}-"?*) current_generation=true' in eso
    assert '[ "${current_generation}" = true ]' in eso
    assert '[ "${condition_status}" = True ]' in eso
    assert "for attempt in $(seq 1 75); do" in eso
    assert "sleep 2" in eso

    assert "Authorization: Bearer" not in eso
    assert "token_file=" not in eso
    assert "curl" not in eso


def test_bootstrap_protects_key_file_and_temporary_material() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert stat.S_IMODE(BOOTSTRAP.stat().st_mode) == 0o755
    assert "umask 077" in text
    assert 'BOOTSTRAP_TMP_ROOT="$(mktemp -d)"' in text
    assert 'rm -rf -- "${BOOTSTRAP_TMP_ROOT}"' in text
    snapshot = 'BOOTSTRAP_AGE_KEY_SHA256="$(python3 "${SNAPSHOT_HELPER}" snapshot-age-key'
    secret_create = text.index("create secret generic sops-age")
    assert text.index(snapshot) < secret_create
    assert "readonly BOOTSTRAP_AGE_KEY BOOTSTRAP_AGE_KEY_SHA256" in text
    assert "pki_dir" not in text
    assert "openssl req" not in text
    assert "nohiki-model-egress-tls-source" not in text


def test_bootstrap_secret_apply_is_idempotent_and_silent() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    start = text.index("create secret generic sops-age")
    block = text[start : text.index("\n  printf", start)]
    assert "--from-file=age.agekey=@AGEKEY@" in block
    assert "bound_kubectl_with_age create secret generic sops-age" in text
    assert '"${BOOTSTRAP_KUBECONFIG_SHA256}" @KUBECONFIG@' in text
    assert '"${BOOTSTRAP_AGE_KEY_SHA256}" @AGEKEY@ --' in text
    assert 'kubectl --kubeconfig=@KUBECONFIG@ --context="${BOOTSTRAP_CONTEXT}"' in text
    assert "--dry-run=client -o yaml" in block
    assert "apply -f - >/dev/null" in block
    assert not re.search(r"\b(?:cat|echo|printf|tee)\b.*SOPS_AGE_KEY_FILE", text)
    assert "--from-literal" not in block
    assert "set -x" not in text


def test_tracked_files_contain_no_private_age_key_or_cli_secret_literal() -> None:
    completed = subprocess.run(
        [
            "git",
            "grep",
            "-En",
            r"AGE-SECRET-KEY-|SOPS_AGE_KEY=",
            "--",
            ":(exclude,glob)**/tests/**",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode in {0, 1}, completed.stderr
    assert completed.stdout == "", completed.stdout
