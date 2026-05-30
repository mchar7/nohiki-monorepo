"""Tests for tailor.core.context.TailorContext.

Covers is_manual_mode, is_complete, and missing_fields properties for both
LLM mode (context + job files) and manual mode (pre-built JSON data file).
"""

from __future__ import annotations

from pathlib import Path

from tailor.core.context import TailorContext
from tailor.core.types import OutputSpec


class TestIsManualMode:
    """Tests for TailorContext.is_manual_mode property."""

    def test_false_when_data_file_path_is_none(self) -> None:
        """is_manual_mode must be False when data_file_path is not set."""
        ctx = TailorContext()
        assert ctx.is_manual_mode is False

    def test_true_when_data_file_path_is_set(self) -> None:
        """is_manual_mode must be True when data_file_path is set."""
        ctx = TailorContext(data_file_path=Path("/data/manual.json"))
        assert ctx.is_manual_mode is True


class TestIsComplete:
    """Tests for TailorContext.is_complete property."""

    def test_false_for_empty_default_context(self) -> None:
        """is_complete must be False for a default-constructed TailorContext."""
        assert TailorContext().is_complete is False

    def test_llm_mode_true_when_all_required_set(self) -> None:
        """is_complete in LLM mode must be True when all required fields are set."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            template_name="resume_template",
            schema_name="resume",
            outputs=[OutputSpec(path=Path("/out/r.pdf"), format="pdf")],
        )
        assert ctx.is_complete is True

    def test_llm_mode_false_without_context_files(self) -> None:
        """is_complete must be False in LLM mode when context_file_paths is empty."""
        ctx = TailorContext(
            job_file_paths=[Path("/jobs/job.md")],
            template_name="resume_template",
            schema_name="resume",
        )
        assert ctx.is_complete is False

    def test_llm_mode_false_without_job_files(self) -> None:
        """is_complete must be False in LLM mode when job_file_paths is empty."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            template_name="resume_template",
            schema_name="resume",
        )
        assert ctx.is_complete is False

    def test_llm_mode_false_without_template_name(self) -> None:
        """is_complete must be False in LLM mode when template_name is empty."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            schema_name="resume",
        )
        assert ctx.is_complete is False

    def test_llm_mode_false_without_schema_name(self) -> None:
        """is_complete must be False in LLM mode when schema_name is empty."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            template_name="resume_template",
        )
        assert ctx.is_complete is False

    def test_manual_mode_true_when_all_required_set(self) -> None:
        """is_complete in manual mode must be True when data_file, template and schema are set."""
        ctx = TailorContext(
            data_file_path=Path("/data/resume.json"),
            template_name="resume_template",
            schema_name="resume",
            outputs=[OutputSpec(path=Path("/out/r.pdf"), format="pdf")],
        )
        assert ctx.is_complete is True

    def test_manual_mode_false_without_template_name(self) -> None:
        """is_complete in manual mode must be False when template_name is empty."""
        ctx = TailorContext(
            data_file_path=Path("/data/resume.json"),
            schema_name="resume",
        )
        assert ctx.is_complete is False

    def test_manual_mode_false_without_schema_name(self) -> None:
        """is_complete in manual mode must be False when schema_name is empty."""
        ctx = TailorContext(
            data_file_path=Path("/data/resume.json"),
            template_name="resume_template",
        )
        assert ctx.is_complete is False


class TestMissingFields:
    """Tests for TailorContext.missing_fields property."""

    def test_llm_mode_lists_all_missing_when_empty(self) -> None:
        """missing_fields in LLM mode must list all required fields when none are set."""
        ctx = TailorContext()
        missing = ctx.missing_fields
        assert "context_file_paths" in missing
        assert "job_file_paths" in missing
        assert "template_name" in missing
        assert "schema_name" in missing

    def test_llm_mode_empty_when_complete(self) -> None:
        """missing_fields must return [] in LLM mode when all required fields are set."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            template_name="resume_template",
            schema_name="resume",
            outputs=[OutputSpec(path=Path("/out/r.pdf"), format="pdf")],
        )
        assert ctx.missing_fields == []

    def test_llm_mode_lists_outputs_when_empty(self) -> None:
        """missing_fields must list outputs in LLM mode when outputs is empty."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            template_name="resume_template",
            schema_name="resume",
        )
        assert "outputs" in ctx.missing_fields

    def test_llm_mode_only_template_missing(self) -> None:
        """missing_fields must list only template_name when just that field is absent."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            schema_name="resume",
            outputs=[OutputSpec(path=Path("/out/r.pdf"), format="pdf")],
        )
        assert ctx.missing_fields == ["template_name"]

    def test_llm_mode_only_schema_missing(self) -> None:
        """missing_fields must list only schema_name when just that field is absent."""
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/resume.txt")],
            job_file_paths=[Path("/jobs/job.md")],
            template_name="resume_template",
            outputs=[OutputSpec(path=Path("/out/r.pdf"), format="pdf")],
        )
        assert ctx.missing_fields == ["schema_name"]

    def test_manual_mode_empty_when_complete(self) -> None:
        """missing_fields must return [] in manual mode when all required fields are set."""
        ctx = TailorContext(
            data_file_path=Path("/data/resume.json"),
            template_name="resume_template",
            schema_name="resume",
            outputs=[OutputSpec(path=Path("/out/r.pdf"), format="pdf")],
        )
        assert ctx.missing_fields == []

    def test_manual_mode_lists_template_and_schema_when_missing(self) -> None:
        """missing_fields in manual mode must list template_name and schema_name when absent."""
        ctx = TailorContext(data_file_path=Path("/data/resume.json"))
        missing = ctx.missing_fields
        assert "template_name" in missing
        assert "schema_name" in missing
        # data_file_path is set so it should NOT appear
        assert "data_file_path" not in missing

    def test_manual_mode_does_not_include_context_or_job_files(self) -> None:
        """missing_fields in manual mode must not report context_file_paths or job_file_paths."""
        ctx = TailorContext(data_file_path=Path("/data/resume.json"))
        missing = ctx.missing_fields
        assert "context_file_paths" not in missing
        assert "job_file_paths" not in missing


class TestMutability:
    """Tests confirming TailorContext is a mutable regular dataclass."""

    def test_fields_can_be_mutated_directly(self) -> None:
        """TailorContext is not frozen; fields must be assignable after construction."""
        ctx = TailorContext()
        ctx.template_name = "new_template"
        assert ctx.template_name == "new_template"

    def test_list_fields_can_be_appended_to(self) -> None:
        """List fields must support in-place mutation via .append()."""
        ctx = TailorContext()
        ctx.context_file_paths.append(Path("/ctx/new.txt"))
        assert Path("/ctx/new.txt") in ctx.context_file_paths

    def test_outputs_can_be_mutated(self) -> None:
        """Outputs field must support in-place mutation via .append()."""
        ctx = TailorContext()
        ctx.outputs.append(OutputSpec(path=Path("/out/x.pdf"), format="pdf"))
        assert len(ctx.outputs) == 1
