"""Main orchestrator for document tailoring pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from doc_template_service.core.validation import validate_data
from nohiki_observability import get_logger

from tailor.adapters.file_adapter import TailorFileAdapter
from tailor.adapters.llm_adapter import TailorLLMAdapter
from tailor.adapters.template_adapter import TailorTemplateAdapter
from tailor.core.config import get_settings
from tailor.core.context import TailorContext
from tailor.core.types import JsonDict, OutputSpec, RenderOutputFormat
from tailor.exceptions import DataError, LintConfigError, TailorError
from tailor.lint.config import load_lint_config
from tailor.lint.engine import run_lint
from tailor.lint.layout import (
    LayoutExtractor,
    PdfPlumberLayoutExtractor,
    run_layout_lint,
)
from tailor.lint.meta import build_runtime, extract_tailor_meta
from tailor.lint.models import LintConfig, LintIssue
from tailor.lint.runtime import LintRuntimeContext
from tailor.models.inputs import TailorInput
from tailor.models.outputs import (
    GenerationResult,
    OutputResult,
    RenderResult,
    TailorOutput,
)

if TYPE_CHECKING:
    from tailor.core.config import TailorSettings

logger = get_logger(__name__)


@dataclass
class TailorOrchestrator:
    """Coordinates the full tailoring pipeline.

    Single entry point for both interactive wizard and CLI args modes.
    """

    file_adapter: TailorFileAdapter
    llm_adapter: TailorLLMAdapter
    template_adapter: TailorTemplateAdapter
    layout_extractor: LayoutExtractor

    @classmethod
    def create(cls, settings: TailorSettings | None = None) -> TailorOrchestrator:
        """Create orchestrator with default adapters.

        The default layout extractor is :class:`PdfPlumberLayoutExtractor`;
        tests can inject a stub via the constructor.
        """
        resolved_settings = settings if settings is not None else get_settings()
        return cls(
            file_adapter=TailorFileAdapter(resolved_settings),
            llm_adapter=TailorLLMAdapter(resolved_settings),
            template_adapter=TailorTemplateAdapter(resolved_settings),
            layout_extractor=PdfPlumberLayoutExtractor(),
        )

    async def generate(self, context: TailorContext) -> TailorOutput:
        """Execute the full tailoring pipeline.

        The pipeline runs content lint **before** rendering, renders outputs,
        then runs layout lint on the first PDF render (if any) and merges
        layout issues into the final ``lint_issues`` list. Layout lint is
        non-blocking: extractor failures are logged and produce zero issues.
        """
        self._validate_context(context)
        self._log_pipeline_start(context)

        tailor_input = self._load_inputs(context)
        runtime: LintRuntimeContext | None = None
        if context.is_manual_mode:
            manual_data, runtime = self._load_manual_data_with_meta(context)
            self._validate_manual_data(manual_data, tailor_input.schema_content)
            generation_result = self._build_manual_generation_result(manual_data)
        else:
            generation_result = await self._generate_content(tailor_input)

        data_for_lint = cast("dict[str, object]", generation_result.content)
        lint_config = self._load_lint_config(tailor_input.template_path)
        lint_issues = self._run_content_lint(data_for_lint, lint_config, runtime)

        output_results = await self._render_outputs(
            context.outputs,
            tailor_input.template_content,
            generation_result.content,
        )
        lint_issues.extend(
            self._run_layout_lint(data_for_lint, lint_config, runtime, output_results),
        )

        logger.info(
            "Tailoring complete",
            output_count=len(output_results),
            tokens_used=generation_result.total_tokens,
        )

        return TailorOutput(
            outputs=output_results,
            generation_result=generation_result,
            lint_issues=lint_issues,
        )

    async def aclose(self) -> None:
        """Close owned external clients."""
        await self.llm_adapter.close()

    async def check_services(self) -> dict[str, bool]:
        """Check availability of required services."""
        return {"gotenberg": await self.template_adapter.health_check()}

    def _validate_context(self, context: TailorContext) -> None:
        """Validate context completeness."""
        if not context.is_complete:
            msg = f"Incomplete context: missing {', '.join(context.missing_fields)}"
            raise TailorError(msg)

    @staticmethod
    def _log_pipeline_start(context: TailorContext) -> None:
        """Log pipeline start."""
        logger.info(
            "Starting tailoring pipeline",
            template=context.template_name,
            schema=context.schema_name,
            output_count=len(context.outputs),
        )

    def _load_inputs(self, context: TailorContext) -> TailorInput:
        """Load all input files and templates synchronously."""
        context_files = self.file_adapter.load_context_files(context.context_file_paths)
        job_files = self.file_adapter.load_job_files(context.job_file_paths)
        template = self.file_adapter.load_template(context.template_name)
        schema = self.file_adapter.load_schema(context.schema_name)

        return TailorInput(
            context_files=context_files,
            job_files=job_files,
            template_name=context.template_name,
            schema_name=context.schema_name,
            outputs=context.outputs,
            template_content=template.content,
            schema_content=schema.content,
            template_path=template.path,
        )

    @staticmethod
    def _load_lint_config(template_path: Path | None) -> LintConfig | None:
        """Load the ``.lint.yaml`` co-located with ``template_path``.

        Non-blocking: ``LintConfigError`` is logged and downgraded to ``None``
        so the pipeline continues without lint coverage. This matches the
        previous behaviour and keeps lint issues advisory, not fatal.
        """
        if template_path is None:
            return None
        try:
            return load_lint_config(template_path)
        except LintConfigError as e:
            logger.warning("Lint config error — skipping lint", error=str(e))
            return None

    @staticmethod
    def _run_content_lint(
        data: dict[str, object],
        lint_config: LintConfig | None,
        runtime: LintRuntimeContext | None,
    ) -> list[LintIssue]:
        """Run content linting against ``data`` if a lint config exists.

        Non-blocking: execution errors are logged and swallowed. Lint issues
        are advisory, not fatal to the generate pipeline.

        Args:
            data: Generated document data (``_tailor_meta`` already stripped).
            lint_config: Parsed config from :meth:`_load_lint_config` or
                ``None`` if no config is present / config parsing failed.
            runtime: Optional runtime context built from ``_tailor_meta``.
                LLM-mode generation passes ``None``.

        Returns:
            List of lint issues, or empty list if no config or on error.
        """
        if lint_config is None:
            return []
        try:
            return run_lint(data, lint_config, runtime)
        except (KeyError, TypeError, ValueError, RuntimeError) as e:
            # KeyError: unknown rule type in registry or missing sibling reference.
            # TypeError: rule check failed (e.g., wrong params type).
            # ValueError: validation errors, regex compile errors.
            # RuntimeError: unexpected runtime failures.
            logger.warning("Lint execution error — skipping lint", error=str(e))
            return []

    def _run_layout_lint(
        self,
        data: dict[str, object],
        lint_config: LintConfig | None,
        runtime: LintRuntimeContext | None,
        outputs: list[OutputResult],
    ) -> list[LintIssue]:
        """Extract layout metadata from the first PDF output and run layout rules.

        Non-blocking: extraction and rule-evaluation errors are logged and
        swallowed. Layout lint is skipped entirely when the lint config has
        no ``layout:`` block or when no PDF output was rendered this run.
        """
        if lint_config is None or lint_config.layout is None or not lint_config.layout.rules:
            return []
        pdf_bytes = _first_pdf_bytes(outputs)
        if pdf_bytes is None:
            logger.info("Layout lint skipped — no PDF output rendered this run")
            return []
        try:
            layout_meta = self.layout_extractor.extract(pdf_bytes, data)
            return run_layout_lint(
                lint_config.layout.rules,
                layout_meta,
                data=data,
                runtime=runtime,
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as e:
            logger.warning("Layout lint error — skipping layout rules", error=str(e))
            return []

    def _load_manual_data_with_meta(
        self,
        context: TailorContext,
    ) -> tuple[JsonDict, LintRuntimeContext | None]:
        """Load manual JSON data and split off any ``_tailor_meta`` runtime block.

        The stripped data is what downstream validation, rendering, and linting
        operate on — the meta block is invisible to the template and schema.

        Returns:
            ``(stripped_data, runtime_or_none)``. ``runtime`` is ``None`` when
            the data file has no ``_tailor_meta`` block.

        Raises:
            DataError: Manual mode is selected but no data file path is set.
        """
        if context.data_file_path is None:
            msg = "Manual mode requires a data file"
            raise DataError(msg)
        raw = self.file_adapter.load_data_file(context.data_file_path)
        stripped_raw, meta = extract_tailor_meta(raw)
        # ``extract_tailor_meta`` returns ``dict[str, object]``; the broader
        # ``JsonValue`` subtyping is irrelevant for rendering so we cast back.
        stripped = cast("JsonDict", stripped_raw)
        if meta is None:
            return stripped, None
        runtime = build_runtime(meta, base_dir=context.data_file_path.parent)
        return stripped, runtime

    @staticmethod
    def _validate_manual_data(data: JsonDict, schema: JsonDict) -> None:
        """Validate manual data against schema and raise on errors."""
        report = validate_data(data, schema)
        if report.valid:
            return

        messages = "; ".join(issue.message for issue in report.issues) or "Unknown schema errors"
        msg = f"Manual data failed schema validation: {messages}"
        raise DataError(msg)

    @staticmethod
    def _build_manual_generation_result(data: JsonDict) -> GenerationResult:
        """Build a GenerationResult for manual JSON data."""
        return GenerationResult(
            content=data,
            prompt_tokens=0,
            completion_tokens=0,
            model_used="manual",
            duration_seconds=0.0,
        )

    @staticmethod
    def _serialize_json_output(data: JsonDict) -> str:
        """Serialize JSON output for writing to disk."""
        return json.dumps(data, indent=2, sort_keys=True)

    @staticmethod
    def _build_json_render_result(content: str) -> RenderResult:
        """Build RenderResult for JSON-only output."""
        return RenderResult(
            content=content,
            content_type="application/json",
            size_bytes=len(content.encode("utf-8")),
        )

    async def _generate_content(self, tailor_input: TailorInput) -> GenerationResult:
        """Generate content using LLM."""
        return await self.llm_adapter.generate(
            schema=tailor_input.schema_content,
            context_content=tailor_input.combined_context_content,
            job_content=tailor_input.combined_job_content,
            schema_name=tailor_input.schema_name,
        )

    async def _render_outputs(
        self,
        specs: list[OutputSpec],
        template_content: str,
        data: JsonDict,
    ) -> list[OutputResult]:
        """Render and write all output specs sequentially.

        JSON outputs are serialized directly. Rendered outputs go through
        the template adapter (Gotenberg). Each result is written to disk
        immediately after rendering.

        Args:
            specs: Output specifications with paths and formats.
            template_content: HTML template content for rendering.
            data: Generated document data.

        Returns:
            List of output results in the same order as specs.
        """
        results: list[OutputResult] = []
        for spec in specs:
            if spec.format == "json":
                content = self._serialize_json_output(data)
                render_result = self._build_json_render_result(content)
                written_path = self.file_adapter.write_output(content, spec.path)
            else:
                render_format: RenderOutputFormat = spec.format
                render_result = await self.template_adapter.render(
                    template_content=template_content,
                    data=data,
                    output_format=render_format,
                )
                written_path = self.file_adapter.write_output(render_result.content, spec.path)
            results.append(OutputResult(spec=spec, render_result=render_result, written_path=written_path))
        return results


def _first_pdf_bytes(outputs: list[OutputResult]) -> bytes | None:
    """Return the first PDF render's bytes, or ``None`` when none was rendered.

    Identifies PDFs by ``RenderResult.content_type`` rather than output spec
    format, so renderers that emit PDFs under alternative spec formats still
    feed the layout extractor correctly. Silently skips outputs whose
    ``content`` is not ``bytes`` (e.g. JSON strings).
    """
    for output in outputs:
        render_result = output.render_result
        if not isinstance(render_result.content, bytes):
            continue
        if "pdf" in render_result.content_type.lower():
            return render_result.content
    return None
