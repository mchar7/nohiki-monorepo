"""Operator contract tests for deterministic document qualification CLI."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_llm_client import ApiKeyRegistry
from typer.testing import CliRunner, Result

from llm_benchmark.cli import app
from llm_benchmark.schemas.document_qualification import GateName

runner = CliRunner()
_HASH = "a" * 64


def _settings(path: Path, *, embedded_key: bool = False) -> Path:
    model: dict[str, object] = {
        "model": "openai:gpt-5.6-sol",
        "base_url": "https://provider.example.test/v1",
        "reasoning_effort": "medium",
    }
    if embedded_key:
        model["api_key"] = "credential-that-must-never-be-printed"
    path.write_text(
        json.dumps(
            {
                "provider": {"models": [model]},
                "chains": {
                    "doc_tailoring": {
                        "models": [
                            model,
                            {
                                "model": "openai:claude-opus-4-8",
                                "base_url": "https://provider.example.test/v1",
                                "reasoning_effort": "medium",
                            },
                            {
                                "model": "openrouter:moonshotai/kimi-k2.6",
                                "reasoning_effort": "high",
                                "provider_order": ["SiliconFlow"],
                                "provider_allow_fallbacks": False,
                                "provider_zdr": True,
                            },
                        ],
                        "max_tokens": 4096,
                        "timeout_seconds": 120,
                    }
                },
                "instrumentation": {"enabled": False},
            }
        )
    )
    return path


def _args(settings: Path, output: Path, *extra: str) -> list[str]:
    return [
        "qualify-document",
        "--output",
        str(output),
        "--llm-settings",
        str(settings),
        "--chain",
        "doc_tailoring",
        "--cost-cap",
        "1.25",
        *extra,
    ]


def _result(status: str, route_statuses: dict[str, str] | None = None) -> SimpleNamespace:
    routes: dict[str, SimpleNamespace] = {}
    for alias, route_status in (route_statuses or {}).items():
        cases = []
        if route_status == "route_qualified":
            cases.append(
                SimpleNamespace(
                    fixture_id="unicode_complete_resume",
                    run_number=1,
                    passed=True,
                    telemetry=SimpleNamespace(
                        cell_latency_ms=100.0,
                        actual_cost_usd=0.01,
                        charged_cost_usd=0.01,
                    ),
                )
            )
        routes[f"treatment-{alias}"] = SimpleNamespace(
            identity=SimpleNamespace(route_alias=alias),
            status=route_status,
            cases=cases,
            gate_totals={gate: {"passed": len(cases), "failed": 0} for gate in GateName},
        )
    return SimpleNamespace(
        status=status,
        experiment_fingerprint=_HASH,
        fixture_checksums={"unicode_complete_resume": _HASH},
        routes=routes,
    )


def _invoke_with_result(
    settings: Path,
    output: Path,
    result: SimpleNamespace,
    *extra: str,
) -> tuple[Result, AsyncMock]:
    resolved_chain = MagicMock()
    with (
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_api_keys",
            return_value=ApiKeyRegistry(),
        ),
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_credential_free_chain",
            return_value=((), resolved_chain),
        ),
        patch(
            "llm_benchmark.cli.commands.qualify_document.LLMSettings",
            return_value=MagicMock(),
        ),
        patch("llm_benchmark.engine.document_qualification.DocumentQualificationRunner"),
        patch(
            "llm_benchmark.cli.commands.qualify_document._run_qualification",
            new=AsyncMock(return_value=result),
        ) as run_qualification,
    ):
        invocation = runner.invoke(app, _args(settings, output, *extra))
    return invocation, run_qualification


def test_command_is_registered_and_help_is_operator_safe() -> None:
    root = runner.invoke(app, ["--help"])
    command = runner.invoke(app, ["qualify-document", "--help"])

    assert root.exit_code == 0
    assert "qualify-document" in root.output
    assert command.exit_code == 0
    assert b"\x1b" not in root.output_bytes
    assert b"\x1b" not in command.output_bytes
    assert "--output" in command.output
    assert "--llm-settings" in command.output
    assert "--chain" in command.output
    assert "--cost-cap" in command.output
    assert "--route" in command.output
    assert "--preflight" in command.output
    assert "--model" not in command.output
    assert "--api-key" not in command.output


@pytest.mark.parametrize("option", ["--output", "--llm-settings", "--chain", "--cost-cap"])
def test_required_options_are_enforced(tmp_path: Path, option: str) -> None:
    settings = _settings(tmp_path / "settings.json")
    args = _args(settings, tmp_path / "result.json")
    index = args.index(option)
    del args[index : index + 2]

    result = runner.invoke(app, args)

    assert result.exit_code != 0
    assert option in result.output
    assert "Missing option" in result.output


@pytest.mark.parametrize("forbidden", ["--model", "--api-key"])
def test_forbidden_credential_and_model_shortcuts_are_rejected(
    tmp_path: Path,
    forbidden: str,
) -> None:
    settings = _settings(tmp_path / "settings.json")
    result = runner.invoke(
        app,
        _args(settings, tmp_path / "result.json", forbidden, "unsafe-value"),
    )

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_embedded_credentials_fail_before_runner_construction(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "settings.json", embedded_key=True)
    secret = "credential-that-must-never-be-printed"
    with (
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_api_keys",
            return_value=ApiKeyRegistry(),
        ),
        patch("llm_benchmark.engine.document_qualification.DocumentQualificationRunner") as runner_type,
    ):
        result = runner.invoke(app, _args(settings, tmp_path / "result.json"))

    assert result.exit_code == 2
    runner_type.assert_not_called()
    assert secret not in result.output
    assert "https://provider.example.test/v1" not in result.output


def test_preflight_stays_non_qualified_and_passes_preflight_to_engine(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "settings.json")
    result, run_qualification = _invoke_with_result(
        settings,
        tmp_path / "preflight.json",
        _result("preflight"),
        "--preflight",
    )

    assert result.exit_code == 0
    assert "status=preflight" in result.output
    assert "status=qualified" not in result.output
    assert run_qualification.await_count == 1
    await_args = run_qualification.await_args
    assert await_args is not None
    assert await_args.kwargs["preflight"] is True
    assert await_args.kwargs["existing"] is None


@pytest.mark.parametrize(
    ("route_status", "expected_exit"),
    [("route_qualified", 0), ("incomplete", 1), ("failed", 1)],
)
def test_route_subset_status_controls_exit_code(
    tmp_path: Path,
    route_status: str,
    expected_exit: int,
) -> None:
    settings = _settings(tmp_path / "settings.json")
    root_status = "incomplete" if route_status != "failed" else "failed"
    result, run_qualification = _invoke_with_result(
        settings,
        tmp_path / "result.json",
        _result(root_status, {"sol": route_status}),
        "--route",
        "sol",
        "--fixture",
        "unicode_complete_resume",
    )

    assert result.exit_code == expected_exit
    assert f"route=sol status={route_status}" in result.output
    assert "route=opus" not in result.output
    assert "route=kimi" not in result.output
    await_args = run_qualification.await_args
    assert await_args is not None
    assert await_args.kwargs["selected_routes"] == ("sol",)


def test_missing_requested_route_is_incomplete_and_nonzero(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "settings.json")
    result, _ = _invoke_with_result(
        settings,
        tmp_path / "result.json",
        _result("incomplete"),
        "--route",
        "kimi",
        "--fixture",
        "unicode_complete_resume",
    )

    assert result.exit_code == 1
    assert "route=kimi status=incomplete" in result.output


def test_console_omits_exception_body_endpoint_and_credentials(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "settings.json")
    resolved_chain = MagicMock()
    unsafe = "credential-value https://provider.example.test/v1 raw-provider-body"
    with (
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_api_keys",
            return_value=ApiKeyRegistry(),
        ),
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_credential_free_chain",
            return_value=((), resolved_chain),
        ),
        patch(
            "llm_benchmark.cli.commands.qualify_document.LLMSettings",
            return_value=MagicMock(),
        ),
        patch("llm_benchmark.engine.document_qualification.DocumentQualificationRunner"),
        patch(
            "llm_benchmark.cli.commands.qualify_document._run_qualification",
            new=AsyncMock(side_effect=RuntimeError(unsafe)),
        ),
    ):
        result = runner.invoke(app, _args(settings, tmp_path / "result.json"))

    assert result.exit_code == 1
    assert "status=failed" in result.output
    assert unsafe not in result.output
    assert "credential-value" not in result.output
    assert "https://provider.example.test/v1" not in result.output
    assert "raw-provider-body" not in result.output


def test_incompatible_resume_is_safe_and_nonzero(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "settings.json")
    output = tmp_path / "result.json"
    unsafe = "https://provider.example.test/v1 credential-value"
    output.write_text(unsafe)
    with (
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_api_keys",
            return_value=ApiKeyRegistry(),
        ),
        patch(
            "llm_benchmark.cli.commands.qualify_document.load_credential_free_chain",
            return_value=((), MagicMock()),
        ),
        patch(
            "llm_benchmark.cli.commands.qualify_document.LLMSettings",
            return_value=MagicMock(),
        ),
        patch("llm_benchmark.engine.document_qualification.DocumentQualificationRunner"),
    ):
        result = runner.invoke(app, _args(settings, output))

    assert result.exit_code == 1
    assert "status=failed" in result.output
    assert unsafe not in result.output
    assert output.read_text() == unsafe
