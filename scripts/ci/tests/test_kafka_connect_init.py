"""Static regression coverage for Compose Kafka Connect registration."""

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TypedDict, cast

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONNECT_ROOT = _REPOSITORY_ROOT / "infra" / "k8s" / "kafka-connect"
_DOCKERFILE = (_CONNECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
_REGISTRATION = (_CONNECT_ROOT / "scripts" / "register-connectors.sh").read_text(encoding="utf-8")


class _CdcState(TypedDict):
    connectors: list[str]
    slots: dict[str, bool]
    publications: list[str]
    publication_tables: dict[str, list[str]]
    configs: dict[str, dict[str, object]]


def _fetch_jars(dockerfile: str) -> list[tuple[str, str, str]]:
    matches = re.finditer(
        r"(?m)^\s*fetch_jar (?P<coordinate>\S+) \\\n"
        r"\s+(?P<checksum>\S+) \\\n"
        r"\s+(?P<destination>\S+);(?: \\)?$",
        dockerfile,
    )
    return [(match["coordinate"], match["checksum"], match["destination"]) for match in matches]


def _dockerfile_arg(name: str) -> str:
    values = re.findall(rf"(?m)^ARG {re.escape(name)}=(\S+)\s*$", _DOCKERFILE)
    assert len(values) == 1, name
    return values[0]


def test_connect_image_installs_postgresql_client_before_non_root_user() -> None:
    dockerfile = _DOCKERFILE
    registration = _REGISTRATION

    assert re.search(r"\bpsql\b", registration), "connector registration requires the PostgreSQL CLI"

    non_root_user = dockerfile.index("USER 1001")
    privileged_build = dockerfile[:non_root_user]
    install = re.search(
        r"RUN\s+microdnf\s+install\s+-y\s+['\"]?(?P<package>postgresql-[^\s'\"\\]+)['\"]?\s+&&\s*\\\s*\n"
        r"\s*microdnf\s+clean\s+all",
        privileged_build,
    )
    assert install is not None, "install PostgreSQL client and clean microdnf cache before USER 1001"
    assert install.group("package") == "postgresql-16.*"
    assert not re.fullmatch(r"postgresql-\d+\.\d+-\d+\.fc\d+", install.group("package"))
    assert re.search(r"Fedora\s*\n# 41-based Debezium Connect image", dockerfile)
    assert not re.search(r"Fedora\s*\n# 42-based Debezium Connect image", dockerfile)


def test_dsn_secret_is_not_exposed_in_python_process_arguments(tmp_path: Path) -> None:
    secret = "credential-process-table-marker"
    secrets_dir = tmp_path / "secrets" / "database"
    secrets_dir.mkdir(parents=True)
    dsn = f"postgresql://user:{secret}@postgres:5432/nohiki"
    (secrets_dir / "dsn").write_text(f"{dsn}\n", encoding="utf-8")

    argv_log = tmp_path / "python-argv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_wrapper = bin_dir / "python3"
    python_wrapper.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "$PYTHON_ARGV_LOG"\nexec {sys.executable} "$@"\n',
        encoding="utf-8",
    )
    python_wrapper.chmod(0o755)

    result = subprocess.run(
        ["bash", str(_CONNECT_ROOT / "scripts" / "register-connectors.sh"), "help"],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PYTHON_ARGV_LOG": str(argv_log),
            "SECRETS_DIR": str(tmp_path / "secrets"),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    observed_argv = argv_log.read_text(encoding="utf-8")
    assert observed_argv.strip() == "-"
    assert secret not in observed_argv
    assert dsn not in observed_argv


def test_default_connect_image_is_strimzi_compatible_and_carries_every_plugin() -> None:
    final_stage = _DOCKERFILE.rsplit("\nFROM ", maxsplit=1)[1]

    assert final_stage.startswith(
        "quay.io/strimzi/kafka:1.1.0-kafka-4.3.0@sha256:"
        "b6848a53c01eec98b37866450a1227c3a41707785ec65b37063d2733a105bf36 AS strimzi"
    )
    assert "/opt/kafka/plugins/debezium-postgres/" in final_stage
    assert "/opt/kafka/plugins/qdrant-kafka/" in final_stage
    assert "/opt/kafka/plugins/nohiki-wal-router/" in final_stage


def test_connect_image_replaces_vulnerable_netty_family_as_one_unit() -> None:
    dockerfile = _DOCKERFILE
    fetches = _fetch_jars(dockerfile)
    assert fetches
    assert all(re.fullmatch(r"[0-9a-f]{64}", checksum) for _, checksum, _ in fetches)

    netty_fetches = [
        (coordinate, checksum, destination)
        for coordinate, checksum, destination in fetches
        if coordinate.startswith("io/netty/")
    ]
    expected_artifacts = {
        "netty-buffer",
        "netty-codec",
        "netty-codec-dns",
        "netty-codec-http",
        "netty-codec-http2",
        "netty-codec-socks",
        "netty-common",
        "netty-handler",
        "netty-handler-proxy",
        "netty-resolver",
        "netty-resolver-dns",
        "netty-transport",
        "netty-transport-native-unix-common",
    }
    artifacts = {coordinate.split("/")[2] for coordinate, _, _ in netty_fetches}
    versions = {coordinate.split("/")[3] for coordinate, _, _ in netty_fetches}
    assert artifacts == expected_artifacts
    assert len(versions) == 1
    version = next(iter(versions))
    assert re.fullmatch(r"\d+\.\d+\.\d+\.Final", version)
    for coordinate, _, destination in netty_fetches:
        _, group, artifact, artifact_version, filename = coordinate.split("/")
        assert group == "netty"
        assert artifact_version == version
        assert filename == f"{artifact}-{version}.jar"
        assert destination == f"/kafka/external_libs/apicurio/{filename}"

    assert "/kafka/external_libs/apicurio/netty-*.jar" in dockerfile


def test_registration_accepts_asyncpg_database_dsn(tmp_path: Path) -> None:
    """The Connect registration boundary accepts the async SQLAlchemy DSN form."""
    secrets_dir = tmp_path / "secrets" / "database"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "dsn").write_text(
        "postgresql+asyncpg://user%40name:p%40ss%2Fword@db.example:5433/appdb\n",
        encoding="utf-8",
    )
    config_dir = tmp_path / "connectors"
    config_dir.mkdir()
    template = json.dumps(
        {
            "name": "SERVICE_NAME",
            "config": {
                "database.hostname": "DATABASE_HOST",
                "database.port": "DATABASE_PORT",
                "database.user": "DATABASE_USER",
                "database.password": "DATABASE_PASSWORD",
                "database.dbname": "DATABASE_NAME",
            },
        }
    )
    for template_name in (
        "outbox-connector-template.json",
        "wal-connector-template.json",
    ):
        (config_dir / template_name).write_text(template, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "connector.json"
    (bin_dir / "curl").write_text(
        textwrap.dedent(
            """
            #!/bin/sh
            wants_code=0
            has_data=0
            url=''
            for arg in "$@"; do
              [ "$arg" = "-w" ] && wants_code=1
              [ "$arg" = "--data-binary" ] && has_data=1
              case "$arg" in http://*|https://*) url="$arg" ;; esac
            done
            if [ "$wants_code" -eq 1 ]; then
              printf '404'
              exit 0
            fi
            case "$url" in
              */connectors/*) exit 22 ;;
              */connectors)
                [ "$has_data" -eq 1 ] && cat > "$CONNECTOR_CAPTURE"
                exit 0
                ;;
            esac
            exit 0
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "psql").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "psql").chmod(0o755)

    result = subprocess.run(
        ["bash", str(_CONNECT_ROOT / "scripts" / "register-connectors.sh")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SECRETS_DIR": str(tmp_path / "secrets"),
            "CONFIG_DIR": str(config_dir),
            "CONNECTOR_CAPTURE": str(capture),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(capture.read_text(encoding="utf-8"))
    assert payload["config"] == {
        "database.hostname": "db.example",
        "database.port": "5433",
        "database.user": "user@name",
        "database.password": "p@ss/word",
        "database.dbname": "appdb",
    }


def test_qdrant_connector_restores_shaded_dns_name_resolver_provider() -> None:
    dockerfile = _DOCKERFILE
    version = _dockerfile_arg("QDRANT_CONNECTOR_VERSION")
    checksum_value = _dockerfile_arg("QDRANT_CONNECTOR_SHA256")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert re.fullmatch(r"[0-9a-f]{64}", checksum_value)

    install_start = dockerfile.index("WORKDIR /kafka/connect/qdrant-kafka")
    install_end = dockerfile.index("WORKDIR /kafka", install_start + 1)
    body = dockerfile[install_start:install_end]
    assert "RUN set -eu;" in body, "Qdrant installation must fail closed"
    descriptor = "META-INF/services/shadow.grpc.NameResolverProvider"
    dns_provider = "shadow.grpc.internal.DnsNameResolverProvider"
    uds_provider = "shadow.grpc.netty.shaded.io.grpc.netty.UdsNameResolverProvider"
    assert f"descriptor='{descriptor}'" in body
    assert f"dns_provider='{dns_provider}'" in body
    assert f"uds_provider='{uds_provider}'" in body
    assert (
        'connector_jar="qdrant-kafka-${QDRANT_CONNECTOR_VERSION}/lib/kafka-${QDRANT_CONNECTOR_VERSION}.jar"'
    ) in body

    checksum = body.index("sha256sum --check --strict qdrant-kafka.sha256")
    extract = body.index("unzip qdrant-kafka.zip")
    validate_class = body.index(
        "unzip -Z1 \"${connector_jar}\" | grep -Fxq 'shadow/grpc/internal/DnsNameResolverProvider.class'"
    )
    validate_descriptor = body.index('unzip -Z1 "${connector_jar}" | grep -Fxq "${descriptor}"')
    retain_uds = body.index('unzip -p "${connector_jar}" "${descriptor}" | grep -Fxq "${uds_provider}"')
    write_descriptor = body.index('printf \'%s\\n%s\\n\' "${dns_provider}" "${uds_provider}" > "${descriptor}"')
    patch_jar = body.index('zip -q -X "${connector_jar}" "${descriptor}"')
    verify_patch = body.index(
        'test "$(unzip -p "${connector_jar}" "${descriptor}")" = '
        '"$(printf \'%s\\n%s\' "${dns_provider}" "${uds_provider}")"'
    )
    cleanup = body.index("rm -rf META-INF qdrant-kafka.zip qdrant-kafka.sha256")

    assert checksum < extract < validate_class < validate_descriptor < retain_uds
    assert retain_uds < write_descriptor < patch_jar < verify_patch < cleanup


def _expected_compose_cdc_inventory() -> tuple[set[str], set[str], set[str]]:
    outbox_array = re.search(r"OUTBOX_CONNECTORS=\(\n(?P<entries>.*?)\n\)", _REGISTRATION, re.DOTALL)
    wal_array = re.search(r"WAL_CONNECTORS=\(\n(?P<entries>.*?)\n\)", _REGISTRATION, re.DOTALL)
    assert outbox_array is not None
    assert wal_array is not None

    outbox = re.findall(r'"([^:"]+):([^:"]+)"', outbox_array.group("entries"))
    wal = re.findall(r'"([^:"]+):([^:"]+):([^:"]+)"', wal_array.group("entries"))
    connectors = {f"{service}-outbox" for service, _ in outbox}
    connectors.update(f"{service}-wal" for service, _, _ in wal)
    if (_CONNECT_ROOT / "connectors" / "qdrant-embedding-sink.json").is_file():
        connectors.add("qdrant-embedding-sink")
    slots = {f"{service.removesuffix('-service').replace('-', '_')}_outbox_slot" for service, _ in outbox}
    slots.update(f"{prefix}_wal_slot" for _, _, prefix in wal)
    publications = {f"{service.removesuffix('-service').replace('-', '_')}_outbox_pub" for service, _ in outbox}
    publications.update(f"{prefix}_wal_pub" for _, _, prefix in wal)
    return connectors, slots, publications


def _run_compose_cdc_reconciliation(
    tmp_path: Path,
    *,
    superseded_slot_active: bool,
    unsupported_resource: tuple[str, str] | None = None,
    failed_delete: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], _CdcState]:
    secrets_dir = tmp_path / "secrets" / "database"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "dsn").write_text("postgresql://user:pass@postgres:5432/nohiki\n", encoding="utf-8")
    state: _CdcState = {
        "connectors": ["nohiki-outbox-user_auth"],
        "slots": {"nohiki_outbox_slot_user_auth": superseded_slot_active},
        "publications": ["nohiki_outbox_pub_user_auth"],
        "publication_tables": {"nohiki_outbox_pub_user_auth": ["user_auth_schema.outbox"]},
        "configs": {},
    }
    if unsupported_resource is not None:
        kind, identity = unsupported_resource
        if kind == "connector":
            state["connectors"].append(identity)
        elif kind == "slot":
            state["slots"][identity] = False
        elif kind == "publication":
            state["publications"].append(identity)
        else:
            publication, table = identity.split("|", 1)
            state["publication_tables"].setdefault(publication, []).append(table)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["CDC_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            args = sys.argv[1:]
            method = args[args.index("-X") + 1] if "-X" in args else "GET"
            url = next(arg for arg in args if arg.startswith(("http://", "https://")))

            def save():
                state_path.write_text(json.dumps(state), encoding="utf-8")

            if "/connectors/" in url:
                name = url.split("/connectors/", 1)[1].split("/", 1)[0]
                if method == "DELETE":
                    if name == os.environ.get("FAIL_DELETE_NAME"):
                        if "-w" in args:
                            print("500", end="")
                        raise SystemExit(0)
                    present = name in state["connectors"]
                    if present:
                        state["connectors"].remove(name)
                        state["configs"].pop(name, None)
                        save()
                    if "-w" in args:
                        print("204" if present else "404", end="")
                    raise SystemExit(0)
                if name not in state["connectors"]:
                    raise SystemExit(22)
                if url.endswith("/status"):
                    print(json.dumps({"connector": {"state": "RUNNING"}, "tasks": [{"state": "RUNNING"}]}))
                elif url.endswith("/config"):
                    print(json.dumps(state["configs"][name]))
                else:
                    print("{}")
                raise SystemExit(0)

            if method == "GET" and url.endswith("/connectors"):
                print(json.dumps(state["connectors"]))
                raise SystemExit(0)

            if method == "POST" and url.endswith("/connectors"):
                payload = json.load(sys.stdin)
                name = payload["name"]
                config = payload["config"]
                if name not in state["connectors"]:
                    state["connectors"].append(name)
                state["configs"][name] = config
                if slot := config.get("slot.name"):
                    state["slots"][slot] = True
                if publication := config.get("publication.name"):
                    if publication not in state["publications"]:
                        state["publications"].append(publication)
                    if table := config.get("table.include.list"):
                        state["publication_tables"][publication] = [table]
                save()
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (bin_dir / "psql").write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            import json
            import os
            import re
            import sys
            from pathlib import Path

            state_path = Path(os.environ["CDC_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            args = sys.argv[1:]
            query = args[args.index("-c") + 1]

            if "SELECT slot_name, active FROM pg_replication_slots" in query:
                print("\\n".join(f"{name}|{'t' if active else 'f'}" for name, active in sorted(state["slots"].items())))
            elif "SELECT pubname FROM pg_publication" in query:
                print("\\n".join(sorted(state["publications"])))
            elif "FROM pg_publication_tables" in query:
                print(
                    "\\n".join(
                        f"{publication}|{table}"
                        for publication, tables in sorted(state["publication_tables"].items())
                        for table in sorted(tables)
                    )
                )
            elif "SELECT CASE WHEN active" in query:
                name = re.search(r"slot_name = '([^']+)'", query).group(1)
                if name in state["slots"]:
                    print("active" if state["slots"][name] else "inactive")
            elif "pg_drop_replication_slot" in query:
                name = re.search(r"pg_drop_replication_slot\\('([^']+)'\\)", query).group(1)
                state["slots"].pop(name, None)
                state_path.write_text(json.dumps(state), encoding="utf-8")
            elif "DROP PUBLICATION" in query:
                name = re.search(r'DROP PUBLICATION IF EXISTS "([^"]+)"', query).group(1)
                if name in state["publications"]:
                    state["publications"].remove(name)
                state["publication_tables"].pop(name, None)
                state_path.write_text(json.dumps(state), encoding="utf-8")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    for executable in (bin_dir / "curl", bin_dir / "psql"):
        executable.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            str(_CONNECT_ROOT / "scripts" / "register-connectors.sh"),
            "reconcile-compose-cdc",
        ],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SECRETS_DIR": str(tmp_path / "secrets"),
            "CDC_STATE": str(state_path),
            "FAIL_DELETE_NAME": failed_delete or "",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    state = cast("_CdcState", json.loads(state_path.read_text(encoding="utf-8")))
    return result, state


def test_reconcile_compose_cdc_recovers_exact_inventory_from_superseded_resources(tmp_path: Path) -> None:
    expected_connectors, expected_slots, expected_publications = _expected_compose_cdc_inventory()

    result, state = _run_compose_cdc_reconciliation(tmp_path, superseded_slot_active=False)

    assert result.returncode == 0, result.stderr
    assert set(state["connectors"]) == expected_connectors
    assert set(state["slots"]) == expected_slots
    assert set(state["publications"]) == expected_publications
    assert all(state["slots"].values())


def test_reconcile_compose_cdc_refuses_active_superseded_slot(tmp_path: Path) -> None:
    result, state = _run_compose_cdc_reconciliation(tmp_path, superseded_slot_active=True)

    assert result.returncode != 0
    assert "active slot nohiki_outbox_slot_user_auth" in result.stderr
    assert "No resources were changed" in result.stderr
    assert "nohiki-outbox-user_auth" in state["connectors"]
    assert state["slots"]["nohiki_outbox_slot_user_auth"] is True
    assert "nohiki_outbox_pub_user_auth" in state["publications"]


@pytest.mark.parametrize(
    ("kind", "identity"),
    [
        ("connector", "third-party-source"),
        ("slot", "third_party_slot"),
        ("publication", "third_party_publication"),
        ("table", "nohiki_outbox_pub_user_auth|third_party_schema.events"),
    ],
)
def test_reconcile_compose_cdc_refuses_identity_outside_bounded_inventory(
    tmp_path: Path,
    kind: str,
    identity: str,
) -> None:
    result, state = _run_compose_cdc_reconciliation(
        tmp_path,
        superseded_slot_active=False,
        unsupported_resource=(kind, identity),
    )

    assert result.returncode != 0
    assert f"{kind} {identity}" in result.stderr
    assert "No resources were changed" in result.stderr
    assert "manually" in result.stderr
    assert "nohiki-outbox-user_auth" in state["connectors"]
    assert "nohiki_outbox_slot_user_auth" in state["slots"]
    assert "nohiki_outbox_pub_user_auth" in state["publications"]


def test_reconcile_compose_cdc_explains_partial_state_after_mutation_failure(tmp_path: Path) -> None:
    result, _ = _run_compose_cdc_reconciliation(
        tmp_path,
        superseded_slot_active=False,
        failed_delete="nohiki-outbox-user_auth",
    )

    assert result.returncode != 0
    assert "state may be partially applied" in result.stderr
    assert "rerun this command" in result.stderr
    assert "No automatic rollback occurred" in result.stderr


def test_outbox_connectors_use_service_owned_schemas() -> None:
    registration = _REGISTRATION

    connector_array = re.search(r"OUTBOX_CONNECTORS=\(\n(?P<entries>.*?)\n\)", registration, re.DOTALL)
    assert connector_array is not None, "registration must define the canonical connector mapping"

    connectors = re.findall(r'"([^:"]+):([^:"]+)"', connector_array.group("entries"))
    assert dict(connectors) == {
        "user-auth-service": "user_auth_schema",
        "user-pref-service": "user_pref_schema",
        "user-upload-service": "user_upload_schema",
        "user-entitlement-service": "user_entitlement_schema",
        "job-query-composition-service": "job_query_schema",
        "job-ingest-enrichment-service": "job_ingest_enrichment_schema",
        "job-storage-service": "job_storage_schema",
        "doc-template-service": "doc_template_schema",
        "skill-graph-service": "skill_graph_schema",
        "bff-service": "bff_schema",
        "notification-service": "notification_schema",
    }
    assert len(connectors) == len(dict(connectors)), "each canonical service must be registered exactly once"


def test_schedule_outbox_connector_is_absent() -> None:
    """The retired schedule outbox must not be registered or templated."""
    registration = _REGISTRATION
    connector_array = re.search(r"OUTBOX_CONNECTORS=\(\n(?P<entries>.*?)\n\)", registration, re.DOTALL)
    assert connector_array is not None

    connectors = dict(re.findall(r'"([^:"]+):([^:"]+)"', connector_array.group("entries")))
    assert "job-ingest-schedule-service" not in connectors
    assert "job_schedule_schema" not in connectors.values()
    assert "job-ingest-schedule-service-outbox" not in registration
