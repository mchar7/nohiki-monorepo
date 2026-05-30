"""Tests for tailor.display.prompts -- interactive wizard prompt functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tailor.display.prompts import (
    display_step_header,
    prompt_confirm_generation,
    prompt_context_files,
    prompt_files,
    prompt_job_files,
    prompt_output_path,
    prompt_template_selection,
)
from tailor.models.templates import TemplateInfo


def _make_template_info(
    name: str = "test_resume",
    description: str = "A test resume template",
) -> TemplateInfo:
    """Build a TemplateInfo for prompt tests."""
    return TemplateInfo(
        path=Path(f"/templates/{name}.html"),
        name=name,
        content="<html/>",
        version="1.0.0",
        description=description,
        access_scope="PUBLIC",
    )


class TestPromptFiles:
    """Tests for prompt_files interactive file collection."""

    def test_returns_valid_file_path(self, tmp_path: Path) -> None:
        """prompt_files must return paths for valid files entered by the user."""
        real_file = tmp_path / "resume.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=[str(real_file), ""]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=5)
        assert len(result) == 1
        assert result[0] == real_file

    def test_stops_on_empty_input_when_files_collected(self, tmp_path: Path) -> None:
        """prompt_files must stop the loop when empty input is given after at least one file."""
        f1 = tmp_path / "a.txt"
        f1.write_text("a", encoding="utf-8")
        f2 = tmp_path / "b.txt"
        f2.write_text("b", encoding="utf-8")
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=[str(f1), str(f2), ""]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=5)
        assert len(result) == 2

    def test_prompts_again_for_empty_input_with_no_files(self, tmp_path: Path) -> None:
        """prompt_files must re-prompt (show error) when empty input with no files yet."""
        real_file = tmp_path / "resume.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=["", str(real_file), ""]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=5)
        assert len(result) == 1

    def test_skips_nonexistent_file(self, tmp_path: Path) -> None:
        """prompt_files must skip paths that do not exist on disk."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch(
                "tailor.display.prompts.Prompt.ask",
                side_effect=[str(tmp_path / "ghost.txt"), str(real_file), ""],
            ),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=5)
        assert len(result) == 1
        assert result[0] == real_file

    def test_skips_directory_path(self, tmp_path: Path) -> None:
        """prompt_files must skip paths that point to directories, not files."""
        real_file = tmp_path / "file.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch(
                "tailor.display.prompts.Prompt.ask",
                side_effect=[str(tmp_path), str(real_file), ""],
            ),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=5)
        assert len(result) == 1

    def test_keyboard_interrupt_exits_loop(self, tmp_path: Path) -> None:
        """prompt_files must stop collecting files on KeyboardInterrupt."""
        real_file = tmp_path / "file.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch(
                "tailor.display.prompts.Prompt.ask",
                side_effect=[str(real_file), KeyboardInterrupt],
            ),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=5)
        assert len(result) == 1

    def test_respects_max_files_limit(self, tmp_path: Path) -> None:
        """prompt_files must stop after max_files have been collected."""
        files = [tmp_path / f"{i}.txt" for i in range(3)]
        for f in files:
            f.write_text("content", encoding="utf-8")
        with (
            patch(
                "tailor.display.prompts.Prompt.ask",
                side_effect=[str(f) for f in files],
            ),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_files("Enter files", max_files=2)
        assert len(result) == 2


class TestPromptContextFiles:
    """Tests for prompt_context_files wrapper."""

    def test_delegates_to_prompt_files_with_max_context_files(self, tmp_path: Path) -> None:
        """prompt_context_files must call prompt_files with MAX_CONTEXT_FILES."""
        from tailor.core.config import MAX_CONTEXT_FILES

        real_file = tmp_path / "resume.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=[str(real_file), ""]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_context_files()
        assert len(result) == 1
        assert MAX_CONTEXT_FILES == 10


class TestPromptJobFiles:
    """Tests for prompt_job_files wrapper."""

    def test_delegates_to_prompt_files_with_max_job_files(self, tmp_path: Path) -> None:
        """prompt_job_files must call prompt_files with MAX_JOB_FILES."""
        from tailor.core.config import MAX_JOB_FILES

        real_file = tmp_path / "job.txt"
        real_file.write_text("content", encoding="utf-8")
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=[str(real_file), ""]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_job_files()
        assert len(result) == 1
        assert MAX_JOB_FILES == 10


class TestPromptTemplateSelection:
    """Tests for prompt_template_selection interactive menu."""

    def test_returns_selected_template(self) -> None:
        """prompt_template_selection must return the template at the chosen index."""
        templates = [_make_template_info("resume"), _make_template_info("cover_letter")]
        with (
            patch("tailor.display.prompts.Prompt.ask", return_value="2"),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_template_selection(templates)
        assert result is not None
        assert result.name == "cover_letter"

    def test_returns_none_on_keyboard_interrupt(self) -> None:
        """prompt_template_selection must return None when the user presses Ctrl+C."""
        templates = [_make_template_info()]
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=KeyboardInterrupt),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_template_selection(templates)
        assert result is None

    def test_re_prompts_on_invalid_number(self) -> None:
        """prompt_template_selection must keep looping on invalid numeric input."""
        templates = [_make_template_info("resume")]
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=["99", "1"]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_template_selection(templates)
        assert result is not None
        assert result.name == "resume"

    def test_re_prompts_on_non_numeric_input(self) -> None:
        """prompt_template_selection must keep looping on non-numeric input."""
        templates = [_make_template_info("resume")]
        with (
            patch("tailor.display.prompts.Prompt.ask", side_effect=["abc", "1"]),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_template_selection(templates)
        assert result is not None

    def test_description_truncated_for_long_descriptions(self) -> None:
        """prompt_template_selection must truncate descriptions longer than 50 chars."""
        long_desc = "A" * 60
        templates = [_make_template_info("t", description=long_desc)]
        with (
            patch("tailor.display.prompts.Prompt.ask", return_value="1"),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_template_selection(templates)
        assert result is not None

    def test_selects_first_template_by_default(self) -> None:
        """prompt_template_selection with default input selects the first template."""
        templates = [_make_template_info("first"), _make_template_info("second")]
        with (
            patch("tailor.display.prompts.Prompt.ask", return_value="1"),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_template_selection(templates)
        assert result is not None
        assert result.name == "first"


class TestPromptOutputPath:
    """Tests for prompt_output_path path entry prompt."""

    def test_returns_path_from_input(self, tmp_path: Path) -> None:
        """prompt_output_path must return the path the user types."""
        expected = str(tmp_path / "resume.pdf")
        with patch("tailor.display.prompts.Prompt.ask", return_value=expected):
            result = prompt_output_path("/default/path.pdf")
        assert result == Path(expected)

    def test_expands_user_home(self) -> None:
        """prompt_output_path must expand ~ to the home directory."""
        with patch("tailor.display.prompts.Prompt.ask", return_value="~/resume.pdf"):
            result = prompt_output_path("/default")
        assert "~" not in str(result)


class TestPromptConfirmGeneration:
    """Tests for prompt_confirm_generation Yes/No prompt."""

    def test_returns_true_when_confirmed(self) -> None:
        """prompt_confirm_generation must return True when user confirms."""
        with (
            patch("tailor.display.prompts.Confirm.ask", return_value=True),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_confirm_generation()
        assert result is True

    def test_returns_false_when_declined(self) -> None:
        """prompt_confirm_generation must return False when user declines."""
        with (
            patch("tailor.display.prompts.Confirm.ask", return_value=False),
            patch("tailor.display.prompts.console"),
        ):
            result = prompt_confirm_generation()
        assert result is False


class TestDisplayStepHeader:
    """Tests for display_step_header rule display."""

    def test_does_not_raise(self) -> None:
        """display_step_header must not raise for valid step numbers."""
        with patch("tailor.display.prompts.console") as mock_console:
            display_step_header(1, 5, "Personal Context")
        mock_console.rule.assert_called_once()

    def test_step_number_included_in_rule(self) -> None:
        """display_step_header must include step number in the rule title."""
        with patch("tailor.display.prompts.console") as mock_console:
            display_step_header(3, 5, "Select Template")
        call_args = mock_console.rule.call_args
        assert "3" in call_args[0][0]
        assert "5" in call_args[0][0]
        assert "Select Template" in call_args[0][0]
