"""Tests for tailor.exceptions -- verifies the full exception hierarchy.

All tailor exceptions extend TailorError, which itself extends Exception.
Each subclass adds structured attributes for downstream diagnostics.
"""

from __future__ import annotations

import pytest
from tailor.exceptions import (
    ConfigError,
    DataError,
    FileLoadError,
    GenerationError,
    GotenbergError,
    LintConfigError,
    RenderError,
    SchemaError,
    TailorError,
    TemplateError,
)

# Extracted to module level to satisfy EM101 (string literals in raise) and TRY003 ruff rules.
_MSG_BASE = "base error"
_MSG_LINT_CONFIG = "invalid lint config"
_MSG_LINT_BAD_YAML = "bad yaml syntax"
_MSG_LINT_TEST = "lint test error"
_MSG_RAISED = "raised"
_MSG_CONFIG = "missing API key"
_MSG_READABLE = "readable message"
_MSG_CHECK_ARGS = "check args"
_MSG_BAD_CONFIG = "bad config"
_MSG_FILE_MISSING = "file missing"
_MSG_NOT_FOUND = "not found"
_MSG_MISSING_FILE = "missing file"
_MSG_LOAD_ERROR = "load error"
_MSG_BAD_TEMPLATE = "bad template"
_MSG_INVALID_SCHEMA = "invalid schema"
_MSG_BAD_DATA = "bad data"
_MSG_GEN_FAILED = "gen failed"
_MSG_GEN_ERROR = "gen error"
_MSG_GEN_FAILED_DETAIL = "generation failed"
_MSG_GEN_SHORT = "gen"
_MSG_RENDER_FAILED = "render failed"
_MSG_RENDER_ERROR = "render error"
_MSG_BAD_RENDER = "bad render"
_MSG_SERVER_ERROR = "server error"
_MSG_GOTENBERG_ERROR = "gotenberg error"
_MSG_CONNECTION_REFUSED = "connection refused"
_MSG_BAD_STATUS = "bad status"


class TestTailorError:
    """Tests for the TailorError base exception."""

    def test_message_attribute_stored(self) -> None:
        """Message attribute must equal the constructor argument."""
        err = TailorError("something went wrong")
        assert err.message == "something went wrong"

    def test_str_equals_message(self) -> None:
        """Str representation must equal the message for readable error display."""
        err = TailorError(_MSG_READABLE)
        assert str(err) == _MSG_READABLE

    def test_inherits_from_exception(self) -> None:
        """TailorError must be catch-able as a plain Exception."""
        with pytest.raises(TailorError, match=_MSG_BASE):
            raise TailorError(_MSG_BASE)

    def test_args_tuple_populated(self) -> None:
        """Calling super with message must populate the args tuple."""
        err = TailorError(_MSG_CHECK_ARGS)
        assert err.args == (_MSG_CHECK_ARGS,)

    def test_can_be_raised_and_caught(self) -> None:
        """TailorError must be raise-able and catch-able."""
        with pytest.raises(TailorError, match=_MSG_RAISED):
            raise TailorError(_MSG_RAISED)


class TestConfigError:
    """Tests for ConfigError."""

    def test_inherits_from_tailor_error(self) -> None:
        """ConfigError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_CONFIG):
            raise ConfigError(_MSG_CONFIG)

    def test_message_stored(self) -> None:
        """ConfigError must expose the message attribute from TailorError."""
        err = ConfigError(_MSG_BAD_CONFIG)
        assert err.message == _MSG_BAD_CONFIG

    def test_str_equals_message(self) -> None:
        """Str of ConfigError must equal the provided message."""
        assert str(ConfigError(_MSG_BASE)) == _MSG_BASE


class TestFileLoadError:
    """Tests for FileLoadError."""

    def test_path_attribute_set_when_provided(self) -> None:
        """Path attribute must be stored when constructor receives it."""
        err = FileLoadError(_MSG_NOT_FOUND, path="/some/file.txt")
        assert err.path == "/some/file.txt"

    def test_path_is_none_when_not_provided(self) -> None:
        """Path attribute must default to None when omitted."""
        err = FileLoadError(_MSG_NOT_FOUND)
        assert err.path is None

    def test_inherits_from_tailor_error(self) -> None:
        """FileLoadError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_FILE_MISSING):
            raise FileLoadError(_MSG_FILE_MISSING)

    def test_message_stored(self) -> None:
        """FileLoadError must expose the message attribute."""
        err = FileLoadError(_MSG_MISSING_FILE, path="/tmp/x")
        assert err.message == _MSG_MISSING_FILE

    def test_can_be_raised_and_caught(self) -> None:
        """FileLoadError must be raise-able and catch-able by its own type."""
        with pytest.raises(FileLoadError, match=_MSG_LOAD_ERROR):
            raise FileLoadError(_MSG_LOAD_ERROR, path="/x")


class TestTemplateError:
    """Tests for TemplateError."""

    def test_inherits_from_tailor_error(self) -> None:
        """TemplateError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_BAD_TEMPLATE):
            raise TemplateError(_MSG_BAD_TEMPLATE)

    def test_message_stored(self) -> None:
        """TemplateError must expose the message attribute."""
        assert TemplateError(_MSG_BASE).message == _MSG_BASE


class TestSchemaError:
    """Tests for SchemaError."""

    def test_inherits_from_tailor_error(self) -> None:
        """SchemaError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_INVALID_SCHEMA):
            raise SchemaError(_MSG_INVALID_SCHEMA)

    def test_message_stored(self) -> None:
        """SchemaError must expose the message attribute."""
        assert SchemaError(_MSG_BASE).message == _MSG_BASE


class TestDataError:
    """Tests for DataError."""

    def test_inherits_from_tailor_error(self) -> None:
        """DataError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_BAD_DATA):
            raise DataError(_MSG_BAD_DATA)

    def test_message_stored(self) -> None:
        """DataError must expose the message attribute."""
        assert DataError(_MSG_BASE).message == _MSG_BASE


class TestGenerationError:
    """Tests for GenerationError."""

    def test_model_and_provider_stored_when_provided(self) -> None:
        """Model and provider attributes must be stored when provided."""
        err = GenerationError(_MSG_GEN_FAILED, model="gpt-4", provider="openai")
        assert err.model == "gpt-4"
        assert err.provider == "openai"

    def test_model_is_none_when_not_provided(self) -> None:
        """Model attribute must default to None when omitted."""
        err = GenerationError(_MSG_GEN_FAILED)
        assert err.model is None

    def test_provider_is_none_when_not_provided(self) -> None:
        """Provider attribute must default to None when omitted."""
        err = GenerationError(_MSG_GEN_FAILED)
        assert err.provider is None

    def test_inherits_from_tailor_error(self) -> None:
        """GenerationError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_GEN_ERROR):
            raise GenerationError(_MSG_GEN_ERROR)

    def test_message_stored(self) -> None:
        """GenerationError must expose the message attribute."""
        err = GenerationError(_MSG_GEN_FAILED_DETAIL, model="m", provider="p")
        assert err.message == _MSG_GEN_FAILED_DETAIL

    def test_can_be_raised_and_caught(self) -> None:
        """GenerationError must be raise-able and catch-able by its own type."""
        with pytest.raises(GenerationError, match=_MSG_GEN_SHORT):
            raise GenerationError(_MSG_GEN_SHORT, model="x", provider="y")


class TestRenderError:
    """Tests for RenderError."""

    def test_output_format_stored_when_provided(self) -> None:
        """Output_format attribute must be stored when provided."""
        err = RenderError(_MSG_RENDER_FAILED, output_format="pdf")
        assert err.output_format == "pdf"

    def test_output_format_is_none_when_not_provided(self) -> None:
        """Output_format attribute must default to None when omitted."""
        err = RenderError(_MSG_RENDER_FAILED)
        assert err.output_format is None

    def test_inherits_from_tailor_error(self) -> None:
        """RenderError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_RENDER_ERROR):
            raise RenderError(_MSG_RENDER_ERROR)

    def test_message_stored(self) -> None:
        """RenderError must expose the message attribute."""
        err = RenderError(_MSG_BAD_RENDER, output_format="html")
        assert err.message == _MSG_BAD_RENDER


class TestGotenbergError:
    """Tests for GotenbergError."""

    def test_status_code_stored_when_provided(self) -> None:
        """Status_code attribute must be stored when provided."""
        err = GotenbergError(_MSG_SERVER_ERROR, status_code=500)
        assert err.status_code == 500

    def test_status_code_is_none_when_not_provided(self) -> None:
        """Status_code attribute must default to None when omitted."""
        err = GotenbergError(_MSG_SERVER_ERROR)
        assert err.status_code is None

    def test_inherits_from_tailor_error(self) -> None:
        """GotenbergError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_GOTENBERG_ERROR):
            raise GotenbergError(_MSG_GOTENBERG_ERROR)

    def test_message_stored(self) -> None:
        """GotenbergError must expose the message attribute."""
        err = GotenbergError(_MSG_CONNECTION_REFUSED, status_code=503)
        assert err.message == _MSG_CONNECTION_REFUSED

    def test_can_be_raised_and_caught(self) -> None:
        """GotenbergError must be raise-able and catch-able by its own type."""
        with pytest.raises(GotenbergError, match=_MSG_BAD_STATUS):
            raise GotenbergError(_MSG_BAD_STATUS, status_code=502)


class TestLintConfigError:
    """Tests for LintConfigError."""

    def test_path_attribute_set_when_provided(self) -> None:
        """Path attribute must be stored when constructor receives it."""
        err = LintConfigError(_MSG_LINT_CONFIG, path="/config/resume.lint.yaml")
        assert err.path == "/config/resume.lint.yaml"

    def test_path_is_none_when_not_provided(self) -> None:
        """Path attribute must default to None when omitted."""
        err = LintConfigError(_MSG_LINT_CONFIG)
        assert err.path is None

    def test_path_is_keyword_only(self) -> None:
        """Path must be keyword-only -- verified via signature inspection."""
        import inspect

        sig = inspect.signature(LintConfigError.__init__)
        assert sig.parameters["path"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_inherits_from_tailor_error(self) -> None:
        """LintConfigError must be catch-able as TailorError."""
        with pytest.raises(TailorError, match=_MSG_LINT_BAD_YAML):
            raise LintConfigError(_MSG_LINT_BAD_YAML)

    def test_message_stored(self) -> None:
        """LintConfigError must expose the message attribute from TailorError."""
        err = LintConfigError(_MSG_LINT_CONFIG, path="/x")
        assert err.message == _MSG_LINT_CONFIG

    def test_str_equals_message(self) -> None:
        """Str of LintConfigError must equal the provided message."""
        err = LintConfigError(_MSG_LINT_TEST)
        assert str(err) == _MSG_LINT_TEST

    def test_can_be_raised_and_caught(self) -> None:
        """LintConfigError must be raise-able and catch-able by its own type."""
        with pytest.raises(LintConfigError, match=_MSG_LINT_CONFIG):
            raise LintConfigError(_MSG_LINT_CONFIG, path="/bad/config.yaml")


class TestInheritanceChain:
    """Tests verifying that all errors are catchable as TailorError."""

    @pytest.mark.parametrize(
        "exc",
        [
            ConfigError(_MSG_CONFIG),
            FileLoadError(_MSG_FILE_MISSING),
            TemplateError(_MSG_BAD_TEMPLATE),
            SchemaError(_MSG_INVALID_SCHEMA),
            DataError(_MSG_BAD_DATA),
            GenerationError(_MSG_GEN_FAILED),
            RenderError(_MSG_RENDER_FAILED),
            GotenbergError(_MSG_SERVER_ERROR),
            LintConfigError(_MSG_LINT_CONFIG),
        ],
    )
    def test_all_exceptions_caught_as_tailor_error(self, exc: TailorError) -> None:
        """Every tailor exception must be catch-able via the TailorError base class."""
        with pytest.raises(TailorError):
            raise exc
