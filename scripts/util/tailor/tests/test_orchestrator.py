"""Tests for tailor.core.orchestrator.TailorOrchestrator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from doc_template_service.schemas.models import ValidationIssue, ValidationReport
from tailor.core.context import TailorContext
from tailor.core.orchestrator import TailorOrchestrator
from tailor.core.types import JsonDict, OutputSpec
from tailor.exceptions import DataError, TailorError
from tailor.lint.models import RuleConfig, Severity
from tailor.models.inputs import ContextFile, JobFile, TailorInput
from tailor.models.outputs import GenerationResult, RenderResult, TailorOutput
from tailor.models.templates import SchemaInfo, TemplateInfo

_DEFAULT_GENERATION_DATA: JsonDict = {"name": "Alice"}


def _placeholder_rule() -> RuleConfig:
    """Return a minimal no-op RuleConfig for tests that need a non-empty rules tuple.

    Tests that don't care about rule content use this single placeholder so the LintConfig constructs.
    """
    return RuleConfig(
        rule_id="placeholder.rule",
        type="min_items",
        severity=Severity.INFO,
        scope_paths=("items",),
        params={"value": 0},
    )


@dataclass
class _LLMModeSetup:
    """Pre-wired orchestrator and mock adapters for LLM-mode generate tests.

    Keeps typed references to mock adapters so tests can verify calls without
    going through the orchestrator's concrete-typed attribute declarations.
    """

    orchestrator: TailorOrchestrator
    file_adapter: MagicMock
    llm_adapter: MagicMock
    template_adapter: MagicMock


def _make_template_info(name: str = "test_resume") -> TemplateInfo:
    """Build a minimal TemplateInfo for testing."""
    return TemplateInfo(
        path=Path(f"/templates/{name}.html"),
        name=name,
        content="<html></html>",
        version="1.0.0",
        description="Test template",
        access_scope="PUBLIC",
        namespace="default",
        schema_name="resume",
    )


def _make_schema_info(name: str = "resume") -> SchemaInfo:
    """Build a minimal SchemaInfo for testing."""
    return SchemaInfo(
        path=Path(f"/schemas/{name}_schema.json"),
        name=name,
        content={"title": "Resume Schema", "type": "object", "properties": {"name": {"type": "string"}}},
    )


def _make_generation_result(data: JsonDict | None = None) -> GenerationResult:
    """Build a GenerationResult for testing."""
    return GenerationResult(
        content=data if data is not None else _DEFAULT_GENERATION_DATA,
        prompt_tokens=100,
        completion_tokens=50,
        model_used="test-model",
        duration_seconds=1.0,
    )


def _make_render_result(content: str = "<html>done</html>") -> RenderResult:
    """Build a RenderResult for testing."""
    return RenderResult(
        content=content,
        content_type="text/html",
        size_bytes=len(content.encode("utf-8")),
    )


def make_orchestrator(
    file_adapter: MagicMock | None = None,
    llm_adapter: MagicMock | None = None,
    template_adapter: MagicMock | None = None,
    layout_extractor: MagicMock | None = None,
) -> TailorOrchestrator:
    """Construct a TailorOrchestrator with mock adapters."""
    return TailorOrchestrator(
        file_adapter=file_adapter or MagicMock(),
        llm_adapter=llm_adapter or MagicMock(),
        template_adapter=template_adapter or MagicMock(),
        layout_extractor=layout_extractor or MagicMock(),
    )


def _complete_llm_context(
    template_name: str = "test_resume",
    schema_name: str = "resume",
    outputs: list[OutputSpec] | None = None,
) -> TailorContext:
    """Build a complete LLM-mode TailorContext."""
    return TailorContext(
        context_file_paths=[Path("/ctx/profile.txt")],
        job_file_paths=[Path("/jobs/job.md")],
        template_name=template_name,
        schema_name=schema_name,
        outputs=outputs or [OutputSpec(path=Path("/out/resume.pdf"), format="pdf")],
    )


def _complete_manual_context(
    data_file_path: Path = Path("/data/resume.json"),
    template_name: str = "test_resume",
    schema_name: str = "resume",
    outputs: list[OutputSpec] | None = None,
) -> TailorContext:
    """Build a complete manual-mode TailorContext."""
    return TailorContext(
        data_file_path=data_file_path,
        template_name=template_name,
        schema_name=schema_name,
        outputs=outputs or [OutputSpec(path=Path("/out/resume.pdf"), format="pdf")],
    )


def _make_file_adapter_for_llm() -> MagicMock:
    """Build a fully-configured file adapter for LLM-mode orchestrator tests."""
    adapter = MagicMock()
    adapter.load_context_files = MagicMock(
        return_value=[ContextFile(path=Path("/ctx/a.txt"), content="resume", size_bytes=6, word_count=1)]
    )
    adapter.load_job_files = MagicMock(return_value=[JobFile(path=Path("/jobs/j.md"), content="job", size_bytes=3)])
    adapter.load_template = MagicMock(return_value=_make_template_info())
    adapter.load_schema = MagicMock(return_value=_make_schema_info())
    adapter.generate_filename = MagicMock(return_value="test_resume_2026-03-14.pdf")
    adapter.write_output = MagicMock(return_value=Path("/output/test_resume_2026-03-14.pdf"))
    return adapter


def _make_file_adapter_for_manual() -> MagicMock:
    """Build a file adapter configured for manual-mode orchestrator tests."""
    adapter = MagicMock()
    adapter.load_context_files = MagicMock(return_value=[])
    adapter.load_job_files = MagicMock(return_value=[])
    adapter.load_template = MagicMock(return_value=_make_template_info())
    adapter.load_schema = MagicMock(return_value=_make_schema_info())
    adapter.load_data_file = MagicMock(return_value={"name": "Carol"})
    adapter.generate_filename = MagicMock(return_value="test_resume_2026-03-14.pdf")
    adapter.write_output = MagicMock(return_value=Path("/output/test_resume_2026-03-14.pdf"))
    return adapter


def _make_file_adapter_for_json() -> MagicMock:
    """Build a file adapter configured for JSON-output-mode orchestrator tests."""
    adapter = MagicMock()
    adapter.load_context_files = MagicMock(
        return_value=[ContextFile(path=Path("/ctx/a.txt"), content="ctx", size_bytes=3, word_count=1)]
    )
    adapter.load_job_files = MagicMock(return_value=[JobFile(path=Path("/jobs/j.md"), content="job", size_bytes=3)])
    adapter.load_template = MagicMock(return_value=_make_template_info())
    adapter.load_schema = MagicMock(return_value=_make_schema_info())
    adapter.generate_filename = MagicMock(return_value="test_resume_2026-03-14.json")
    adapter.write_output = MagicMock(return_value=Path("/output/test_resume_2026-03-14.json"))
    return adapter


def _make_file_adapter_with_write(written_path: Path) -> MagicMock:
    """Build a file adapter whose write_output returns the given path."""
    adapter = MagicMock()
    adapter.write_output = MagicMock(return_value=written_path)
    return adapter


@pytest.fixture
def llm_mode_setup() -> _LLMModeSetup:
    """Return pre-wired orchestrator and mock adapters for LLM-mode generate tests.

    Each test accesses adapters directly via the returned dataclass instead of
    through the orchestrator's concrete-typed attributes, avoiding type narrowing issues.
    """
    file_adapter = _make_file_adapter_for_llm()
    llm_adapter = MagicMock()
    llm_adapter.generate = AsyncMock(return_value=_make_generation_result())
    template_adapter = MagicMock()
    template_adapter.render = AsyncMock(return_value=_make_render_result())
    orchestrator = make_orchestrator(
        file_adapter=file_adapter,
        llm_adapter=llm_adapter,
        template_adapter=template_adapter,
    )
    return _LLMModeSetup(
        orchestrator=orchestrator,
        file_adapter=file_adapter,
        llm_adapter=llm_adapter,
        template_adapter=template_adapter,
    )


class TestCreate:
    """Tests for TailorOrchestrator.create class method."""

    def test_create_returns_orchestrator_with_all_adapters(self) -> None:
        """create() must return an orchestrator with all three adapter types."""
        mock_settings = MagicMock()
        with (
            patch("tailor.core.orchestrator.TailorFileAdapter") as mock_file_cls,
            patch("tailor.core.orchestrator.TailorLLMAdapter") as mock_llm_cls,
            patch("tailor.core.orchestrator.TailorTemplateAdapter") as mock_tmpl_cls,
        ):
            mock_file_cls.return_value = MagicMock()
            mock_llm_cls.return_value = MagicMock()
            mock_tmpl_cls.return_value = MagicMock()
            orch = TailorOrchestrator.create(mock_settings)
        assert orch.file_adapter is not None
        assert orch.llm_adapter is not None
        assert orch.template_adapter is not None

    def test_create_uses_get_settings_when_no_settings_passed(self) -> None:
        """create() must call get_settings() when settings argument is None."""
        mock_settings = MagicMock()
        with (
            patch("tailor.core.orchestrator.get_settings", return_value=mock_settings) as mock_get,
            patch("tailor.core.orchestrator.TailorFileAdapter"),
            patch("tailor.core.orchestrator.TailorLLMAdapter"),
            patch("tailor.core.orchestrator.TailorTemplateAdapter"),
        ):
            TailorOrchestrator.create()
        mock_get.assert_called_once()


class TestCheckServices:
    """Tests for TailorOrchestrator.check_services."""

    async def test_check_services_returns_gotenberg_true(self) -> None:
        """check_services must return {'gotenberg': True} when health check passes."""
        template_adapter = MagicMock()
        template_adapter.health_check = AsyncMock(return_value=True)
        orch = make_orchestrator(template_adapter=template_adapter)
        result = await orch.check_services()
        assert result == {"gotenberg": True}

    async def test_check_services_returns_gotenberg_false(self) -> None:
        """check_services must return {'gotenberg': False} when health check fails."""
        template_adapter = MagicMock()
        template_adapter.health_check = AsyncMock(return_value=False)
        orch = make_orchestrator(template_adapter=template_adapter)
        result = await orch.check_services()
        assert result == {"gotenberg": False}


class TestValidateContext:
    """Tests for TailorOrchestrator._validate_context."""

    def test_does_not_raise_for_complete_context(self) -> None:
        """_validate_context must not raise when the context is complete."""
        ctx = _complete_llm_context()
        orch = make_orchestrator()
        orch._validate_context(ctx)  # should not raise

    def test_raises_tailor_error_for_incomplete_context(self) -> None:
        """_validate_context must raise TailorError when context is incomplete."""
        ctx = TailorContext()  # missing everything
        orch = make_orchestrator()
        with pytest.raises(TailorError) as exc_info:
            orch._validate_context(ctx)
        assert "context_file_paths" in exc_info.value.message
        assert "template_name" in exc_info.value.message

    def test_error_message_contains_missing_field_names(self) -> None:
        """TailorError message must list every missing field name."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/a.txt")],
            job_file_paths=[Path("/jobs/b.md")],
        )
        orch = make_orchestrator()
        with pytest.raises(TailorError) as exc_info:
            orch._validate_context(ctx)
        assert "template_name" in exc_info.value.message
        assert "schema_name" in exc_info.value.message


class TestSerializeJsonOutput:
    """Tests for TailorOrchestrator._serialize_json_output."""

    def test_returns_valid_json_string(self) -> None:
        """_serialize_json_output must return a valid JSON string."""
        data: JsonDict = {"name": "Alice", "age": 30}
        result = TailorOrchestrator._serialize_json_output(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_output_is_sorted_and_indented(self) -> None:
        """_serialize_json_output must use indent=2 and sort_keys=True."""
        data: JsonDict = {"z": 1, "a": 2}
        result = TailorOrchestrator._serialize_json_output(data)
        assert result == json.dumps(data, indent=2, sort_keys=True)
        assert result.index('"a"') < result.index('"z"')


class TestBuildJsonRenderResult:
    """Tests for TailorOrchestrator._build_json_render_result."""

    def test_content_type_is_application_json(self) -> None:
        """_build_json_render_result must set content_type to 'application/json'."""
        result = TailorOrchestrator._build_json_render_result('{"name": "Alice"}')
        assert result.content_type == "application/json"

    def test_size_bytes_equals_utf8_length(self) -> None:
        """_build_json_render_result must set size_bytes to the UTF-8 byte length."""
        content = '{"name": "Alice"}'
        result = TailorOrchestrator._build_json_render_result(content)
        assert result.size_bytes == len(content.encode("utf-8"))

    def test_content_preserved(self) -> None:
        """_build_json_render_result must preserve the content string."""
        content = '{"x": 42}'
        result = TailorOrchestrator._build_json_render_result(content)
        assert result.content == content


class TestBuildManualGenerationResult:
    """Tests for TailorOrchestrator._build_manual_generation_result."""

    def test_model_used_is_manual(self) -> None:
        """_build_manual_generation_result must set model_used to 'manual'."""
        data: JsonDict = {"name": "Bob"}
        result = TailorOrchestrator._build_manual_generation_result(data)
        assert result.model_used == "manual"

    def test_tokens_are_zero(self) -> None:
        """_build_manual_generation_result must report zero tokens."""
        data: JsonDict = {"name": "Bob"}
        result = TailorOrchestrator._build_manual_generation_result(data)
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0

    def test_content_matches_input_data(self) -> None:
        """_build_manual_generation_result must store the provided data in content."""
        data: JsonDict = {"name": "Bob", "email": "bob@example.com"}
        result = TailorOrchestrator._build_manual_generation_result(data)
        assert result.content == data


class TestLoadLintConfig:
    """Tests for TailorOrchestrator._load_lint_config static method."""

    def test_returns_none_when_template_path_is_none(self) -> None:
        """_load_lint_config must return None when template_path is None."""
        assert TailorOrchestrator._load_lint_config(None) is None

    def test_returns_none_when_load_returns_none(self) -> None:
        """_load_lint_config must return None when no .lint.yaml is co-located."""
        with patch("tailor.core.orchestrator.load_lint_config", return_value=None):
            assert TailorOrchestrator._load_lint_config(Path("/some/template.html")) is None

    def test_returns_parsed_config(self) -> None:
        """_load_lint_config must return the parsed config when found."""
        from tailor.lint.models import LintConfig

        expected = LintConfig(rules=(_placeholder_rule(),))
        with patch("tailor.core.orchestrator.load_lint_config", return_value=expected):
            assert TailorOrchestrator._load_lint_config(Path("/some/template.html")) is expected

    def test_returns_none_on_lint_config_error(self) -> None:
        """_load_lint_config must downgrade LintConfigError to a warning + None."""
        from tailor.exceptions import LintConfigError

        with patch("tailor.core.orchestrator.load_lint_config", side_effect=LintConfigError("bad config")):
            assert TailorOrchestrator._load_lint_config(Path("/some/template.html")) is None


class TestRunContentLint:
    """Tests for TailorOrchestrator._run_content_lint static method."""

    def test_returns_empty_when_lint_config_is_none(self) -> None:
        """_run_content_lint must return [] when lint_config is None."""
        assert TailorOrchestrator._run_content_lint({}, None, None) == []

    def test_returns_empty_when_rules_are_empty(self) -> None:
        """_run_content_lint must return [] when lint_config has no rules (nothing to run)."""
        from tailor.lint.models import LintConfig

        # run_lint itself returns [] for empty-rules configs; patch to confirm call-through.
        with patch("tailor.core.orchestrator.run_lint", return_value=[]) as mock_run:
            result = TailorOrchestrator._run_content_lint({}, LintConfig(rules=(_placeholder_rule(),)), None)
        assert result == []
        mock_run.assert_called_once()

    def test_returns_issues_from_engine(self) -> None:
        """_run_content_lint must return issues from run_lint when config present."""
        from tailor.lint.models import LintConfig, LintIssue, RuleConfig, Severity

        mock_issue = LintIssue(rule="r", severity=Severity.WARNING, path="p", message="m")
        mock_config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.rule",
                    type="min_items",
                    severity=Severity.WARNING,
                    scope_paths=("items",),
                    params={"value": 1},
                ),
            )
        )
        with patch("tailor.core.orchestrator.run_lint", return_value=[mock_issue]):
            result = TailorOrchestrator._run_content_lint({}, mock_config, None)
        assert result == [mock_issue]

    def test_passes_runtime_through(self) -> None:
        """_run_content_lint must thread the runtime argument to run_lint."""
        from tailor.lint.models import LintConfig
        from tailor.lint.runtime import LintRuntimeContext

        runtime = LintRuntimeContext()
        config = LintConfig(rules=(_placeholder_rule(),))
        with patch("tailor.core.orchestrator.run_lint", return_value=[]) as mock_run:
            TailorOrchestrator._run_content_lint({"k": "v"}, config, runtime)
        args, _ = mock_run.call_args
        assert args[0] == {"k": "v"}
        assert args[1] is config
        assert args[2] is runtime

    def test_returns_empty_on_expected_exception(self) -> None:
        """_run_content_lint must swallow expected exception types and return []."""
        from tailor.lint.models import LintConfig

        config = LintConfig(rules=(_placeholder_rule(),))
        for exc in (KeyError("missing"), TypeError("bad type"), ValueError("bad value"), RuntimeError("oops")):
            with patch("tailor.core.orchestrator.run_lint", side_effect=exc):
                assert TailorOrchestrator._run_content_lint({}, config, None) == []


class TestRunLayoutLint:
    """Tests for TailorOrchestrator._run_layout_lint (instance method)."""

    def test_returns_empty_when_lint_config_is_none(self) -> None:
        """Layout lint must be skipped entirely when no content config was loaded."""
        orch = make_orchestrator()
        assert orch._run_layout_lint({}, None, None, []) == []

    def test_returns_empty_when_layout_block_missing(self) -> None:
        """Layout lint must be skipped when the config has no ``layout:`` block."""
        from tailor.lint.models import LintConfig

        orch = make_orchestrator()
        config = LintConfig(rules=(_placeholder_rule(),))  # layout defaults to None
        assert orch._run_layout_lint({}, config, None, []) == []

    def test_returns_empty_when_layout_rules_empty(self) -> None:
        """Layout lint must be skipped when ``layout.rules`` is an empty tuple."""
        from tailor.lint.models import LayoutConfig, LintConfig

        orch = make_orchestrator()
        # ``LayoutConfig.rules`` is allowed to be empty (unlike top-level
        # ``LintConfig.rules``) so templates can declare a layout block with
        # no active rules if they choose.
        config = LintConfig(rules=(_placeholder_rule(),), layout=LayoutConfig(rules=()))
        assert orch._run_layout_lint({}, config, None, []) == []

    def test_returns_empty_when_no_pdf_rendered(self) -> None:
        """Layout lint must be skipped when no PDF output exists in this run."""
        from tailor.lint.models import LayoutConfig, LintConfig, RuleConfig, Severity

        orch = make_orchestrator()
        config = LintConfig(
            rules=(_placeholder_rule(),),
            layout=LayoutConfig(
                rules=(
                    RuleConfig(
                        rule_id="layout.max_pages_exceeded.resume",
                        type="max_pages_exceeded",
                        severity=Severity.ERROR,
                        scope_paths=("$",),
                        params={"max_pages": 1},
                    ),
                ),
            ),
        )
        # No outputs at all.
        assert orch._run_layout_lint({}, config, None, []) == []

    def test_extracts_and_delegates_to_layout_engine(self) -> None:
        """A PDF output triggers layout extraction + run_layout_lint dispatch."""
        from tailor.lint.layout.extractor import LayoutMetadata
        from tailor.lint.models import LayoutConfig, LintConfig, LintIssue, RuleConfig, Severity
        from tailor.models.outputs import OutputResult

        layout_extractor = MagicMock()
        layout_extractor.extract = MagicMock(
            return_value=LayoutMetadata(
                page_count=1,
                page_size_pt=(612.0, 792.0),
                paragraphs=(),
                total_content_height_pt=0.0,
            )
        )
        orch = make_orchestrator(layout_extractor=layout_extractor)
        rule = RuleConfig(
            rule_id="layout.max_pages_exceeded.resume",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        config = LintConfig(rules=(_placeholder_rule(),), layout=LayoutConfig(rules=(rule,)))
        outputs = [
            OutputResult(
                spec=OutputSpec(path=Path("/out/resume.pdf"), format="pdf"),
                render_result=RenderResult(content=b"%PDF-1.4 fake", content_type="application/pdf", size_bytes=13),
                written_path=Path("/out/resume.pdf"),
            ),
        ]
        issue = LintIssue(rule=rule.rule_id, severity=rule.severity, path="$", message="ok")
        with patch("tailor.core.orchestrator.run_layout_lint", return_value=[issue]) as mock_run:
            result = orch._run_layout_lint({}, config, None, outputs)
        layout_extractor.extract.assert_called_once()
        mock_run.assert_called_once()
        assert result == [issue]

    def test_returns_empty_on_extractor_failure(self) -> None:
        """Layout extractor errors must be logged and downgraded to empty issues."""
        from tailor.lint.models import LayoutConfig, LintConfig, RuleConfig, Severity
        from tailor.models.outputs import OutputResult

        layout_extractor = MagicMock()
        layout_extractor.extract = MagicMock(side_effect=ValueError("malformed PDF"))
        orch = make_orchestrator(layout_extractor=layout_extractor)
        rule = RuleConfig(
            rule_id="layout.max_pages_exceeded.resume",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        config = LintConfig(rules=(_placeholder_rule(),), layout=LayoutConfig(rules=(rule,)))
        outputs = [
            OutputResult(
                spec=OutputSpec(path=Path("/out/resume.pdf"), format="pdf"),
                render_result=RenderResult(content=b"bad", content_type="application/pdf", size_bytes=3),
                written_path=Path("/out/resume.pdf"),
            ),
        ]
        assert orch._run_layout_lint({}, config, None, outputs) == []


class TestFirstPdfBytes:
    """Tests for the module-level _first_pdf_bytes helper."""

    def test_returns_none_for_empty_outputs(self) -> None:
        """No outputs means no PDF."""
        from tailor.core.orchestrator import _first_pdf_bytes

        assert _first_pdf_bytes([]) is None

    def test_returns_none_when_no_pdf_content_type(self) -> None:
        """JSON/text outputs must not be picked up as PDFs."""
        from tailor.core.orchestrator import _first_pdf_bytes
        from tailor.models.outputs import OutputResult

        outputs = [
            OutputResult(
                spec=OutputSpec(path=Path("/out/data.json"), format="json"),
                render_result=RenderResult(content='{"k": 1}', content_type="application/json", size_bytes=8),
                written_path=Path("/out/data.json"),
            ),
        ]
        assert _first_pdf_bytes(outputs) is None

    def test_returns_first_pdf_bytes(self) -> None:
        """First PDF-content-type bytes output wins, even if later outputs are also PDFs."""
        from tailor.core.orchestrator import _first_pdf_bytes
        from tailor.models.outputs import OutputResult

        first = b"%PDF-1.4 first"
        second = b"%PDF-1.4 second"
        outputs = [
            OutputResult(
                spec=OutputSpec(path=Path("/out/a.pdf"), format="pdf"),
                render_result=RenderResult(content=first, content_type="application/pdf", size_bytes=len(first)),
                written_path=Path("/out/a.pdf"),
            ),
            OutputResult(
                spec=OutputSpec(path=Path("/out/b.pdf"), format="pdf"),
                render_result=RenderResult(content=second, content_type="application/pdf", size_bytes=len(second)),
                written_path=Path("/out/b.pdf"),
            ),
        ]
        assert _first_pdf_bytes(outputs) == first

    def test_skips_string_content_even_if_content_type_is_pdf(self) -> None:
        """Malformed str content with pdf content_type is skipped (defensive)."""
        from tailor.core.orchestrator import _first_pdf_bytes
        from tailor.models.outputs import OutputResult

        outputs = [
            OutputResult(
                spec=OutputSpec(path=Path("/out/a.pdf"), format="pdf"),
                render_result=RenderResult(content="not bytes", content_type="application/pdf", size_bytes=9),
                written_path=Path("/out/a.pdf"),
            ),
        ]
        assert _first_pdf_bytes(outputs) is None


class TestGenerateLLMMode:
    """Tests for TailorOrchestrator.generate in LLM mode."""

    async def test_calls_load_context_files(self, llm_mode_setup: _LLMModeSetup) -> None:
        """generate() in LLM mode must call file_adapter.load_context_files."""
        await llm_mode_setup.orchestrator.generate(_complete_llm_context())
        llm_mode_setup.file_adapter.load_context_files.assert_called_once()

    async def test_calls_load_job_files(self, llm_mode_setup: _LLMModeSetup) -> None:
        """generate() in LLM mode must call file_adapter.load_job_files."""
        await llm_mode_setup.orchestrator.generate(_complete_llm_context())
        llm_mode_setup.file_adapter.load_job_files.assert_called_once()

    async def test_calls_llm_adapter_generate(self, llm_mode_setup: _LLMModeSetup) -> None:
        """generate() in LLM mode must call llm_adapter.generate."""
        await llm_mode_setup.orchestrator.generate(_complete_llm_context())
        llm_mode_setup.llm_adapter.generate.assert_called_once()

    async def test_calls_template_adapter_render_for_pdf(self, llm_mode_setup: _LLMModeSetup) -> None:
        """generate() must call template_adapter.render when output_format is not JSON."""
        await llm_mode_setup.orchestrator.generate(_complete_llm_context())
        llm_mode_setup.template_adapter.render.assert_called_once()

    async def test_returns_tailor_output(self, llm_mode_setup: _LLMModeSetup) -> None:
        """generate() must return a TailorOutput instance."""
        result = await llm_mode_setup.orchestrator.generate(_complete_llm_context())
        assert isinstance(result, TailorOutput)

    async def test_generate_returns_lint_issues_in_output(self, llm_mode_setup: _LLMModeSetup) -> None:
        """generate() must include lint_issues in the returned TailorOutput."""
        from tailor.lint.models import LintConfig, LintIssue, RuleConfig, Severity

        mock_issue = LintIssue(rule="r", severity=Severity.WARNING, path="p", message="m")
        mock_config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.rule",
                    type="min_items",
                    severity=Severity.WARNING,
                    scope_paths=("items",),
                    params={"value": 1},
                ),
            )
        )
        with (
            patch("tailor.core.orchestrator.load_lint_config", return_value=mock_config),
            patch("tailor.core.orchestrator.run_lint", return_value=[mock_issue]),
        ):
            result = await llm_mode_setup.orchestrator.generate(_complete_llm_context())
        assert result.lint_issues == [mock_issue]

    async def test_lint_runs_before_render_and_write(self, llm_mode_setup: _LLMModeSetup) -> None:
        """Lint must execute before rendering and writing to catch issues early."""
        call_order: list[str] = []
        original_render = llm_mode_setup.template_adapter.render
        original_write = llm_mode_setup.file_adapter.write_output

        async def track_render(*args: object, **kwargs: object) -> object:
            call_order.append("render")
            return await original_render(*args, **kwargs)

        def track_write(*args: object, **kwargs: object) -> object:
            call_order.append("write")
            return original_write(*args, **kwargs)

        llm_mode_setup.template_adapter.render = track_render
        llm_mode_setup.file_adapter.write_output = track_write

        with patch.object(
            TailorOrchestrator,
            "_run_content_lint",
            side_effect=lambda *_args, **_kwargs: (call_order.append("lint"), [])[1],
        ):
            await llm_mode_setup.orchestrator.generate(_complete_llm_context())

        assert call_order.index("lint") < call_order.index("render")
        assert call_order.index("lint") < call_order.index("write")

    async def test_raises_tailor_error_when_context_incomplete(self) -> None:
        """generate() must raise TailorError when context.is_complete is False."""
        orch = make_orchestrator()
        with pytest.raises(TailorError):
            await orch.generate(TailorContext())


class TestGenerateManualMode:
    """Tests for TailorOrchestrator.generate in manual mode."""

    async def test_does_not_call_llm_adapter_generate(self, tmp_path: Path) -> None:
        """generate() in manual mode must NOT call llm_adapter.generate."""
        data_file = tmp_path / "resume.json"
        data_file.write_text('{"name": "Carol"}', encoding="utf-8")
        file_adapter = _make_file_adapter_for_manual()
        llm_adapter = MagicMock()
        llm_adapter.generate = AsyncMock()
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock(return_value=_make_render_result())

        valid_schema: JsonDict = {"type": "object", "properties": {"name": {"type": "string"}}}
        file_adapter.load_schema.return_value = SchemaInfo(
            path=tmp_path / "resume_schema.json",
            name="resume",
            content=valid_schema,
        )

        orch = make_orchestrator(file_adapter=file_adapter, llm_adapter=llm_adapter, template_adapter=template_adapter)
        ctx = _complete_manual_context(data_file_path=data_file)

        with patch("tailor.core.orchestrator.validate_data") as mock_validate:
            mock_validate.return_value = ValidationReport(valid=True, issues=[])
            await orch.generate(ctx)

        llm_adapter.generate.assert_not_called()

    async def test_calls_load_data_file(self, tmp_path: Path) -> None:
        """generate() in manual mode must call file_adapter.load_data_file."""
        data_file = tmp_path / "resume.json"
        data_file.write_text('{"name": "Carol"}', encoding="utf-8")
        file_adapter = _make_file_adapter_for_manual()
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock(return_value=_make_render_result())

        orch = make_orchestrator(file_adapter=file_adapter, template_adapter=template_adapter)
        ctx = _complete_manual_context(data_file_path=data_file)

        with patch("tailor.core.orchestrator.validate_data") as mock_validate:
            mock_validate.return_value = ValidationReport(valid=True, issues=[])
            await orch.generate(ctx)

        file_adapter.load_data_file.assert_called_once_with(data_file)

    async def test_generation_result_uses_manual_model(self, tmp_path: Path) -> None:
        """generate() in manual mode must produce GenerationResult with model_used='manual' and zero tokens."""
        data_file = tmp_path / "resume.json"
        data_file.write_text('{"name": "Carol"}', encoding="utf-8")
        file_adapter = _make_file_adapter_for_manual()
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock(return_value=_make_render_result())

        orch = make_orchestrator(file_adapter=file_adapter, template_adapter=template_adapter)
        ctx = _complete_manual_context(data_file_path=data_file)

        with patch("tailor.core.orchestrator.validate_data") as mock_validate:
            mock_validate.return_value = ValidationReport(valid=True, issues=[])
            result = await orch.generate(ctx)

        assert result.generation_result.model_used == "manual"
        assert result.generation_result.total_tokens == 0


class TestGenerateJsonOutputFormat:
    """Tests for TailorOrchestrator.generate when output_format is 'json'."""

    async def test_does_not_call_template_adapter_render(self) -> None:
        """generate() with output_format='json' must NOT call template_adapter.render."""
        file_adapter = _make_file_adapter_for_json()
        llm_adapter = MagicMock()
        llm_adapter.generate = AsyncMock(return_value=_make_generation_result())
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock()
        orch = make_orchestrator(file_adapter=file_adapter, llm_adapter=llm_adapter, template_adapter=template_adapter)
        await orch.generate(_complete_llm_context(outputs=[OutputSpec(path=Path("/out/data.json"), format="json")]))
        template_adapter.render.assert_not_called()

    async def test_render_result_content_type_is_application_json(self) -> None:
        """generate() with output_format='json' must set render_result.content_type to application/json."""
        file_adapter = _make_file_adapter_for_json()
        llm_adapter = MagicMock()
        llm_adapter.generate = AsyncMock(return_value=_make_generation_result())
        template_adapter = MagicMock()
        orch = make_orchestrator(file_adapter=file_adapter, llm_adapter=llm_adapter, template_adapter=template_adapter)
        result = await orch.generate(
            _complete_llm_context(outputs=[OutputSpec(path=Path("/out/data.json"), format="json")])
        )
        assert result.outputs[0].render_result.content_type == "application/json"


class TestRenderOutputs:
    """Tests for TailorOrchestrator._render_outputs."""

    async def test_single_pdf_renders_and_writes(self) -> None:
        """_render_outputs with a PDF spec must call render and write_output."""
        file_adapter = MagicMock()
        file_adapter.write_output = MagicMock(return_value=Path("/out/resume.pdf"))
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock(return_value=_make_render_result())
        orch = make_orchestrator(file_adapter=file_adapter, template_adapter=template_adapter)
        specs = [OutputSpec(path=Path("/out/resume.pdf"), format="pdf")]
        results = await orch._render_outputs(specs, "<html/>", {"name": "Alice"})
        assert len(results) == 1
        template_adapter.render.assert_called_once()
        file_adapter.write_output.assert_called_once()

    async def test_json_spec_skips_render(self) -> None:
        """_render_outputs with a JSON spec must NOT call template_adapter.render."""
        file_adapter = MagicMock()
        file_adapter.write_output = MagicMock(return_value=Path("/out/data.json"))
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock()
        orch = make_orchestrator(file_adapter=file_adapter, template_adapter=template_adapter)
        specs = [OutputSpec(path=Path("/out/data.json"), format="json")]
        results = await orch._render_outputs(specs, "<html/>", {"name": "Alice"})
        assert len(results) == 1
        template_adapter.render.assert_not_called()
        assert results[0].render_result.content_type == "application/json"

    async def test_multiple_specs_returns_results_in_order(self) -> None:
        """_render_outputs must return results in the same order as specs."""
        pdf_path = Path("/out/resume.pdf")
        json_path = Path("/out/data.json")
        file_adapter = MagicMock()
        file_adapter.write_output = MagicMock(side_effect=[pdf_path, json_path])
        template_adapter = MagicMock()
        template_adapter.render = AsyncMock(return_value=_make_render_result())
        orch = make_orchestrator(file_adapter=file_adapter, template_adapter=template_adapter)
        specs = [
            OutputSpec(path=pdf_path, format="pdf"),
            OutputSpec(path=json_path, format="json"),
        ]
        results = await orch._render_outputs(specs, "<html/>", {"name": "Alice"})
        assert len(results) == 2
        assert results[0].spec.format == "pdf"
        assert results[1].spec.format == "json"


class TestValidateManualData:
    """Tests for TailorOrchestrator._validate_manual_data."""

    def test_does_not_raise_when_data_is_valid(self) -> None:
        """_validate_manual_data must not raise when validate_data returns a valid report."""
        data: JsonDict = {"name": "Alice"}
        schema: JsonDict = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        with patch("tailor.core.orchestrator.validate_data") as mock_validate:
            mock_validate.return_value = ValidationReport(valid=True, issues=[])
            TailorOrchestrator._validate_manual_data(data, schema)  # should not raise

    def test_raises_data_error_when_validation_fails(self) -> None:
        """_validate_manual_data must raise DataError when validate_data returns invalid report."""
        data: JsonDict = {}
        schema: JsonDict = {"type": "object", "required": ["name"]}
        issue = ValidationIssue(path="$", keyword="required", message="'name' is a required property")
        with patch("tailor.core.orchestrator.validate_data") as mock_validate:
            mock_validate.return_value = ValidationReport(valid=False, issues=[issue])
            with pytest.raises(DataError) as exc_info:
                TailorOrchestrator._validate_manual_data(data, schema)
        assert "name" in exc_info.value.message

    def test_error_message_includes_issue_messages(self) -> None:
        """_validate_manual_data error message must contain each validation issue message."""
        data: JsonDict = {}
        schema: JsonDict = {"type": "object", "required": ["name", "email"]}
        issues = [
            ValidationIssue(path="$", keyword="required", message="'name' is required"),
            ValidationIssue(path="$", keyword="required", message="'email' is required"),
        ]
        with patch("tailor.core.orchestrator.validate_data") as mock_validate:
            mock_validate.return_value = ValidationReport(valid=False, issues=issues)
            with pytest.raises(DataError) as exc_info:
                TailorOrchestrator._validate_manual_data(data, schema)
        assert "'name' is required" in exc_info.value.message
        assert "'email' is required" in exc_info.value.message


class TestLoadManualData:
    """Tests for TailorOrchestrator._load_manual_data."""

    def test_raises_data_error_when_data_file_path_is_none(self) -> None:
        """_load_manual_data_with_meta must raise DataError when context.data_file_path is None."""
        ctx = TailorContext(
            template_name="test_resume",
            schema_name="resume",
        )
        orch = make_orchestrator()
        with pytest.raises(DataError):
            orch._load_manual_data_with_meta(ctx)

    def test_delegates_to_file_adapter_load_data_file(self, tmp_path: Path) -> None:
        """_load_manual_data_with_meta must call file_adapter.load_data_file with the path."""
        data_path = tmp_path / "data.json"
        expected: JsonDict = {"name": "Dave"}
        file_adapter = MagicMock()
        file_adapter.load_data_file = MagicMock(return_value=expected)
        ctx = TailorContext(
            data_file_path=data_path,
            template_name="test_resume",
            schema_name="resume",
        )
        orch = make_orchestrator(file_adapter=file_adapter)
        stripped, runtime = orch._load_manual_data_with_meta(ctx)
        file_adapter.load_data_file.assert_called_once_with(data_path)
        assert stripped == expected
        # No ``_tailor_meta`` key in the test fixture, so no runtime is built.
        assert runtime is None

    def test_extracts_tailor_meta_and_builds_runtime(self, tmp_path: Path) -> None:
        """When ``_tailor_meta`` is present, it is stripped and a runtime is built."""
        data_path = tmp_path / "data.json"
        raw: JsonDict = {
            "name": "Dave",
            "_tailor_meta": {
                "lint_tags": ["dev_role"],
                "lint_vars": {"employer_name": "Acme"},
            },
        }
        file_adapter = MagicMock()
        file_adapter.load_data_file = MagicMock(return_value=raw)
        ctx = TailorContext(
            data_file_path=data_path,
            template_name="test_resume",
            schema_name="resume",
        )
        orch = make_orchestrator(file_adapter=file_adapter)
        stripped, runtime = orch._load_manual_data_with_meta(ctx)
        assert "_tailor_meta" not in stripped
        assert stripped == {"name": "Dave"}
        assert runtime is not None
        assert "dev_role" in runtime.active_tags
        assert runtime.variables == {"employer_name": "Acme"}


class TestLoadInputs:
    """Tests for TailorOrchestrator._load_inputs."""

    def test_returns_tailor_input_with_all_fields(self) -> None:
        """_load_inputs must return a TailorInput populated from file adapter calls."""
        template = _make_template_info()
        schema = _make_schema_info()
        ctx_file = ContextFile(path=Path("/ctx/a.txt"), content="ctx", size_bytes=3, word_count=1)
        job_file = JobFile(path=Path("/jobs/j.md"), content="job", size_bytes=3)

        file_adapter = MagicMock()
        file_adapter.load_context_files = MagicMock(return_value=[ctx_file])
        file_adapter.load_job_files = MagicMock(return_value=[job_file])
        file_adapter.load_template = MagicMock(return_value=template)
        file_adapter.load_schema = MagicMock(return_value=schema)

        orch = make_orchestrator(file_adapter=file_adapter)
        ctx = _complete_llm_context()
        result = orch._load_inputs(ctx)

        assert isinstance(result, TailorInput)
        assert result.template_name == "test_resume"
        assert result.schema_name == "resume"
        assert result.outputs
