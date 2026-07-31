import json
from pathlib import Path

import pytest
from _documents import (
    Manifest,
    containers_of,
    load_compose,
    load_jsonc,
    load_manifests,
    load_mapping,
    load_workflow,
    mapping_at,
    mapping_sequence_at,
    metadata_of,
    pod_spec_of,
    pod_template_of,
    sequence_at,
    string_at,
    string_sequence_at,
    workload_spec_of,
)

_ROOT = Path(__file__).parents[3]


def test_mapping_loaders_reject_non_mapping_documents(tmp_path: Path) -> None:
    path = tmp_path / "sequence.yml"
    path.write_text("- not\n- a mapping\n", encoding="utf-8")

    with pytest.raises(TypeError, match=r"document .* must contain a mapping, got list"):
        load_mapping(path)
    with pytest.raises(TypeError, match=r"workflow .* must contain a mapping, got list"):
        load_workflow(path)
    with pytest.raises(TypeError, match=r"compose file .* must contain a mapping, got list"):
        load_compose(path)


def test_jsonc_loader_preserves_double_slashes_inside_string(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text(r'{"url": "ssh://git@github.com/mchar7/skylos"}', encoding="utf-8")

    assert load_jsonc(path) == {"url": "ssh://git@github.com/mchar7/skylos"}


def test_jsonc_loader_honors_escaped_quotes_inside_string(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text(r'{"value": "escaped \" quote, then // text"}', encoding="utf-8")

    assert load_jsonc(path) == {"value": 'escaped " quote, then // text'}


def test_jsonc_loader_removes_line_comment(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text('{"value": 1, // removed\n"other": 2}', encoding="utf-8")

    assert load_jsonc(path) == {"value": 1, "other": 2}


def test_jsonc_loader_removes_block_comment(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text('{"value": /* removed */ 1}', encoding="utf-8")

    assert load_jsonc(path) == {"value": 1}


def test_jsonc_loader_preserves_block_comment_marker_inside_string(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text('{"value": "looks /* like a comment */"}', encoding="utf-8")

    assert load_jsonc(path) == {"value": "looks /* like a comment */"}


def test_jsonc_loader_removes_trailing_commas_from_mapping_and_sequence(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text('{"items": [1, 2,],}', encoding="utf-8")

    assert load_jsonc(path) == {"items": [1, 2]}


def test_jsonc_loader_rejects_non_mapping_root(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(TypeError, match=r"document .* must contain a mapping, got list"):
        load_jsonc(path)


def test_jsonc_loader_rejects_single_quoted_string_after_removing_comments(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text(
        """{
  "enabled": true, // scanner removes this
  "value": 'single quoted'
}""",
        encoding="utf-8",
    )

    with pytest.raises(json.JSONDecodeError) as error:
        load_jsonc(path)
    assert "// scanner removes this" not in error.value.doc
    assert "'single quoted'" in error.value.doc


def test_jsonc_loader_rejects_unquoted_key_after_removing_comments(tmp_path: Path) -> None:
    path = tmp_path / "config.json5"
    path.write_text(
        """{
  /* scanner removes this */
  unquoted: true
}""",
        encoding="utf-8",
    )

    with pytest.raises(json.JSONDecodeError) as error:
        load_jsonc(path)
    assert "/* scanner removes this */" not in error.value.doc
    assert "unquoted" in error.value.doc


def test_jsonc_loader_reads_real_renovate_config_without_comment_keys() -> None:
    config = load_jsonc(_ROOT / ".github" / "renovate.json5")
    rules = config["packageRules"]
    assert isinstance(rules, list)

    pending: list[object] = [rules]
    comment_keys: list[str] = []
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, nested in value.items():
                if isinstance(key, str) and key.startswith("//"):
                    comment_keys.append(key)
                pending.append(nested)
        elif isinstance(value, list):
            pending.extend(value)

    assert comment_keys == []


def test_manifest_loader_skips_empty_documents_and_rejects_non_mappings() -> None:
    manifests = load_manifests("---\n---\napiVersion: v1\nkind: Service\nmetadata:\n  name: gateway\n---\n")

    assert len(manifests) == 1
    assert manifests[0]["metadata"]["name"] == "gateway"

    with pytest.raises(TypeError, match=r"manifest document 2 must contain a mapping, got list"):
        load_manifests("apiVersion: v1\nkind: Service\nmetadata:\n  name: gateway\n---\n- invalid\n")


def test_secret_fields_load_through_manifest_boundary() -> None:
    secret: Manifest = load_manifests(
        """
apiVersion: v1
kind: Secret
metadata:
  name: registry
data:
  username: YWRtaW4=
stringData:
  password: plain-text
sops:
  encrypted_regex: ^(data|stringData)$
"""
    )[0]

    assert secret["data"]["username"] == "YWRtaW4="
    assert secret["stringData"]["password"] == "plain-text"
    assert secret["sops"] == {"encrypted_regex": "^(data|stringData)$"}


def test_manifest_accessors_return_concrete_workload_and_pod_shapes() -> None:
    deployment, pod = load_manifests(
        """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 2
  template:
    metadata:
      name: api
    spec:
      containers:
        - name: api
          image: registry.example/api:latest
---
apiVersion: v1
kind: Pod
metadata:
  name: shell
spec:
  restartPolicy: Never
  containers:
    - name: shell
      image: busybox:latest
"""
    )

    assert metadata_of(deployment)["name"] == "api"
    assert workload_spec_of(deployment)["replicas"] == 2
    assert pod_template_of(deployment)["metadata"]["name"] == "api"
    assert pod_spec_of(deployment)["containers"][0]["name"] == "api"
    assert containers_of(deployment)[0]["image"] == "registry.example/api:latest"
    assert pod_spec_of(pod)["restartPolicy"] == "Never"
    assert containers_of(pod)[0]["name"] == "shell"


def test_manifest_accessors_report_kind_name_and_expected_shape() -> None:
    malformed_metadata = load_manifests("apiVersion: v1\nkind: Secret\nmetadata:\n  name: 7\n")[0]
    malformed_workload = load_manifests("apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: broken\nspec: {}\n")[
        0
    ]

    with pytest.raises(
        TypeError,
        match=r"manifest kind 'Secret' named 7 expected metadata with a string name, got dict",
    ):
        metadata_of(malformed_metadata)
    with pytest.raises(
        TypeError,
        match=r"manifest kind 'Deployment' named 'broken' expected spec with a pod template, got dict",
    ):
        workload_spec_of(malformed_workload)
    with pytest.raises(
        TypeError,
        match=r"manifest kind 'Deployment' named 'broken' expected spec\.template to be a pod template, got NoneType",
    ):
        pod_template_of(malformed_workload)
    with pytest.raises(
        TypeError,
        match=r"manifest kind 'Deployment' named 'broken' expected spec\.template\.spec to be a pod spec, got NoneType",
    ):
        pod_spec_of(malformed_workload)
    with pytest.raises(
        TypeError,
        match=(
            r"manifest kind 'Deployment' named 'broken' expected "
            r"spec\.template\.spec\.containers to be a list of containers, got NoneType"
        ),
    ):
        containers_of(malformed_workload)


def test_real_workflow_loads_with_typed_jobs() -> None:
    workflow = load_workflow(_ROOT / ".github" / "workflows" / "checks.yml")

    assert workflow["name"] == "Checks"
    assert workflow["jobs"]["changes"]["name"] == "Router"
    assert "pull_request" in workflow["on"]


def test_compose_loader_accepts_realistic_document(tmp_path: Path) -> None:
    path = tmp_path / "compose.yml"
    path.write_text(
        """
services:
  api:
    image: registry.example/api:latest
    environment:
      LOG_LEVEL: info
      WORKERS: 2
    ports:
      - "8000:8000"
    volumes:
      - "./data:/data"
    depends_on:
      database:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "--fail", "http://localhost:8000/health"]
    command: ["serve", "--port", "8000"]
    networks: [backend]
    restart: unless-stopped
    entrypoint: /bin/sh
  worker:
    image: registry.example/worker:latest
    environment:
      - QUEUE=default
    depends_on:
      - database
    command: run-worker
    entrypoint: ["/bin/sh", "-c"]
  database:
    image: postgres:18
networks:
  backend: {}
volumes:
  data: {}
configs:
  api: {file: ./api.conf}
secrets:
  token: {file: ./token}
x-llm-provider-endpoints:
  NOHIKI_LLM_OPENAI_BASE_URL: http://llm:8080
""",
        encoding="utf-8",
    )

    compose = load_compose(path)

    assert compose["services"]["api"]["image"] == "registry.example/api:latest"
    assert compose["services"]["api"]["environment"] == {
        "LOG_LEVEL": "info",
        "WORKERS": 2,
    }
    assert compose["services"]["api"]["depends_on"] == {"database": {"condition": "service_healthy"}}
    assert compose["services"]["worker"]["environment"] == ["QUEUE=default"]
    assert compose["services"]["worker"]["depends_on"] == ["database"]
    assert compose["networks"]["backend"] == {}
    assert compose["volumes"]["data"] == {}
    assert compose["configs"]["api"] == {"file": "./api.conf"}
    assert compose["secrets"]["token"] == {"file": "./token"}
    assert compose["x-llm-provider-endpoints"]["NOHIKI_LLM_OPENAI_BASE_URL"] == "http://llm:8080"


def test_document_path_navigators_return_validated_values() -> None:
    document: dict[str, object] = {
        "helm": {
            "image": {
                "repository": "registry.example/api",
                "tags": ["stable", "canary"],
            },
            "phases": ["build", 2],
        },
        "evidence": {
            "counts": [1, 2],
            "phases": [{"name": "build"}, {"name": "deploy"}],
        },
    }

    assert mapping_at(document, "helm", "image") == {
        "repository": "registry.example/api",
        "tags": ["stable", "canary"],
    }
    assert string_at(document, "helm", "image", "repository") == "registry.example/api"
    assert sequence_at(document, "helm", "phases") == ["build", 2]
    assert string_sequence_at(document, "helm", "image", "tags") == ["stable", "canary"]
    assert mapping_sequence_at(document, "evidence", "phases") == [
        {"name": "build"},
        {"name": "deploy"},
    ]


def test_document_path_navigators_name_missing_paths() -> None:
    document: dict[str, object] = {"helm": {"image": {}}}

    with pytest.raises(KeyError, match=r"helm\.missing.*dict"):
        mapping_at(document, "helm", "missing")
    with pytest.raises(KeyError, match=r"helm\.missing.*dict"):
        mapping_sequence_at(document, "helm", "missing")
    with pytest.raises(KeyError, match=r"helm\.missing.*dict"):
        string_at(document, "helm", "missing")
    with pytest.raises(KeyError, match=r"helm\.missing.*dict"):
        sequence_at(document, "helm", "missing")
    with pytest.raises(KeyError, match=r"helm\.missing.*dict"):
        string_sequence_at(document, "helm", "missing")


def test_document_path_navigators_name_wrong_types() -> None:
    document: dict[str, object] = {
        "helm": {
            "image": {"repository": "registry.example/api"},
            "phases": ["build", 2],
        },
        "evidence": {"counts": [1, 2]},
    }

    with pytest.raises(TypeError, match=r"helm\.image\.repository.*str"):
        mapping_at(document, "helm", "image", "repository")
    with pytest.raises(TypeError, match=r"helm\.image.*dict"):
        string_at(document, "helm", "image")
    with pytest.raises(TypeError, match=r"helm\.image.*dict"):
        sequence_at(document, "helm", "image")
    with pytest.raises(TypeError, match=r"evidence\.counts\[0\].*int"):
        mapping_sequence_at(document, "evidence", "counts")
    with pytest.raises(TypeError, match=r"evidence\.counts\[0\].*int"):
        string_sequence_at(document, "evidence", "counts")

    with pytest.raises(TypeError, match=r"helm\.image\.repository\.tag.*str"):
        string_at(document, "helm", "image", "repository", "tag")
