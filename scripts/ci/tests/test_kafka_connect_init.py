"""Static regression coverage for Compose Kafka Connect registration."""

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import TypedDict, cast

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONNECT_ROOT = _REPOSITORY_ROOT / "infra" / "k8s" / "kafka-connect"
_DOCKERFILE = (_CONNECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
_REGISTRATION = (_CONNECT_ROOT / "scripts" / "register-connectors.sh").read_text(encoding="utf-8")


class _CdcState(TypedDict):
    connectors: list[str]
    slots: dict[str, bool]
    publications: list[str]
    configs: dict[str, dict[str, object]]


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
    version = "4.1.135.Final"
    artifacts = {
        "netty-buffer": "2a194f99fc93d07c4d442d04ac71bd2dc56d3188cd0e4270cdc2a953d1956bf9",
        "netty-codec": "7252171264dbb5bb8ed38e77f89643b31e3cabc96144ec27b6882435d718a61e",
        "netty-codec-dns": "5e996d7ac7597f368ab114fbb91d16788918c7e5bf166345c51e56db54d50fd1",
        "netty-codec-http": "4018529d3d6aecf4044b98c75d9a90c91839ddf49c7aa484c5ac81c90a15da02",
        "netty-codec-http2": "aa4e81ab5fa3b7b243eb3e814aa582ab26c073d31b0abffdbb58ee150fa49c16",
        "netty-codec-socks": "ec7a39e8d7d7e223014115a021273f011c3cb1e8fb187cbfb90a74e76d68c25c",
        "netty-common": "26775ca95820711403cf065fa2ec0134a0a04ff5417c688c0237aee68b55838d",
        "netty-handler": "245e74e04b6f4e8ef98853152412e3bf1499ce6fcf15329b798c8ce36c3537e2",
        "netty-handler-proxy": "75661010630a44468f0e85d7ed8be7779c0cb1369fe85d30799cedc52e9ed3b7",
        "netty-resolver": "77dd03865965b6c12b9e521bddec82f035caeb33156e09c158289c5094318481",
        "netty-resolver-dns": "ca25581e4cebd55797ef3b4d0953b75df32c1af77fe771b96bfaa9e701cdb7c3",
        "netty-transport": "6bde734d1ec073142eed31b1e68cd5d68fbf241e060b37f07a164e5ecb15631c",
        "netty-transport-native-unix-common": "a7895075f112611d1640a596c2678a28aab92d5681c1c14755b109b8998f995e",
    }

    assert "/kafka/external_libs/apicurio/netty-*.jar" in dockerfile
    assert "4.1.133.Final" not in dockerfile
    for artifact, checksum in artifacts.items():
        assert f"fetch_jar io/netty/{artifact}/{version}/{artifact}-{version}.jar" in dockerfile
        assert checksum in dockerfile


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

    assert "ARG QDRANT_CONNECTOR_VERSION=1.3.3" in dockerfile
    assert (
        "ARG QDRANT_CONNECTOR_SHA256=f35b1eef7db212e561019b9e9218e4674d231ca577b603a40e028e1de8f59fa6"
    ) in dockerfile

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
) -> tuple[subprocess.CompletedProcess[str], _CdcState]:
    secrets_dir = tmp_path / "secrets" / "database"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "dsn").write_text("postgresql://user:pass@postgres:5432/nohiki\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "connectors": ["nohiki-outbox-user_auth"],
                "slots": {"nohiki_outbox_slot_user_auth": superseded_slot_active},
                "publications": ["nohiki_outbox_pub_user_auth"],
                "configs": {},
            }
        ),
        encoding="utf-8",
    )
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

            if "SELECT CASE WHEN active" in query:
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
    assert "superseded replication slot nohiki_outbox_slot_user_auth is still active" in result.stderr
    assert state["slots"]["nohiki_outbox_slot_user_auth"] is True
    assert "nohiki_outbox_pub_user_auth" in state["publications"]


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
