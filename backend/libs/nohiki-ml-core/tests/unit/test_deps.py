"""Tests for optional dependency checking module."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from nohiki_ml_core import _deps
from nohiki_ml_core._deps import (
    LocalDependency,
    MissingLocalDependencyError,
    check_fastembed_available,
    check_pylate_available,
    check_sklearn_available,
    get_minibatch_kmeans,
    require_fastembed,
    require_pylate,
    require_sklearn,
)


class TestLocalDependency:
    """Tests for LocalDependency enum."""

    def test_enum_values(self) -> None:
        """Test enum has expected values."""
        assert LocalDependency.PYLATE == "pylate"
        assert LocalDependency.FASTEMBED == "fastembed"
        assert LocalDependency.ONNXRUNTIME == "onnxruntime"
        assert LocalDependency.SKLEARN == "sklearn"
        assert LocalDependency.SENTENCE_TRANSFORMERS == "sentence-transformers"
        assert LocalDependency.TORCH == "torch"
        assert LocalDependency.TRITON == "triton"

    def test_enum_is_str(self) -> None:
        """Test enum values are strings."""
        assert isinstance(LocalDependency.PYLATE.value, str)
        assert str(LocalDependency.PYLATE) == "pylate"


class TestMissingLocalDependencyError:
    """Tests for MissingLocalDependencyError exception."""

    def test_error_message_contains_dependency(self) -> None:
        """Test error message includes dependency name."""
        error = MissingLocalDependencyError(LocalDependency.PYLATE, "ColBERT encoder")
        assert "pylate" in str(error)

    def test_error_message_contains_feature(self) -> None:
        """Test error message includes feature description."""
        error = MissingLocalDependencyError(LocalDependency.PYLATE, "ColBERT encoder")
        assert "ColBERT encoder" in str(error)

    def test_error_message_contains_install_instructions(self) -> None:
        """Test error message includes installation instructions."""
        error = MissingLocalDependencyError(LocalDependency.FASTEMBED, "sparse encoder")
        assert "nohiki-ml-core[inference]" in str(error)

    def test_error_message_mentions_gateway_alternative(self) -> None:
        """Test error message points to the remote inference route."""
        error = MissingLocalDependencyError(LocalDependency.PYLATE, "test feature")
        assert "ml-gateway" in str(error).lower()

    def test_error_attributes(self) -> None:
        """Test error has expected attributes."""
        error = MissingLocalDependencyError(LocalDependency.ONNXRUNTIME, "test")
        assert error.dependency == LocalDependency.ONNXRUNTIME
        assert error.feature == "test"

    def test_is_import_error_subclass(self) -> None:
        """Missing dependencies retain Python import semantics."""
        error = MissingLocalDependencyError(LocalDependency.PYLATE, "test")
        assert isinstance(error, ImportError)


class TestImportOptionalModule:
    """Tests for the single lazy optional-import seam."""

    def test_imports_an_available_module(self) -> None:
        """Available modules are returned through the owned seam."""
        module = _deps.import_optional_module("sys", LocalDependency.PYLATE, "test feature")
        assert module is sys

    def test_missing_module_raises_dependency_error(self) -> None:
        """Missing modules do not leak raw import machinery to callers."""
        with pytest.raises(MissingLocalDependencyError) as error:
            _deps.import_optional_module(
                "_nohiki_missing_optional_dependency",
                LocalDependency.PYLATE,
                "test feature",
            )

        assert error.value.dependency is LocalDependency.PYLATE
        assert isinstance(error.value, ImportError)
        assert isinstance(error.value.__cause__, ModuleNotFoundError)


class TestCheckPylateAvailable:
    """Tests for check_pylate_available function."""

    def test_returns_true_when_installed(self) -> None:
        """Test returns True when pylate is installed."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
            assert check_pylate_available() is True

    def test_returns_false_when_not_installed(self) -> None:
        """Test returns False when pylate import fails."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False):
            assert check_pylate_available() is False


class TestCheckFastembedAvailable:
    """Tests for check_fastembed_available function."""

    def test_returns_true_when_installed(self) -> None:
        """Test returns True when fastembed is installed."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
            assert check_fastembed_available() is True

    def test_returns_false_when_not_installed(self) -> None:
        """Test returns False when fastembed import fails."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False):
            assert check_fastembed_available() is False


class TestRequirePylate:
    """Tests for require_pylate function."""

    def test_does_not_raise_when_available(self) -> None:
        """Test no exception when pylate is available."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
            require_pylate("test feature")

    def test_raises_when_not_available(self) -> None:
        """Test raises MissingLocalDependencyError when pylate not available."""
        with (
            patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False),
            pytest.raises(MissingLocalDependencyError) as exc_info,
        ):
            require_pylate("ColBERT DIRECT backend")

        assert exc_info.value.dependency == LocalDependency.PYLATE
        assert exc_info.value.feature == "ColBERT DIRECT backend"


class TestRequireFastembed:
    """Tests for require_fastembed function."""

    def test_does_not_raise_when_available(self) -> None:
        """Test no exception when fastembed is available."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
            require_fastembed("test feature")

    def test_raises_when_not_available(self) -> None:
        """Test raises MissingLocalDependencyError when fastembed not available."""
        with (
            patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False),
            pytest.raises(MissingLocalDependencyError) as exc_info,
        ):
            require_fastembed("sparse encoder")

        assert exc_info.value.dependency == LocalDependency.FASTEMBED
        assert exc_info.value.feature == "sparse encoder"


class TestCheckSklearnAvailable:
    """Tests for check_sklearn_available function."""

    def test_returns_true_when_installed(self) -> None:
        """Test returns True when sklearn is installed."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
            assert check_sklearn_available() is True

    def test_returns_false_when_not_installed(self) -> None:
        """Test returns False when sklearn import fails."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False):
            assert check_sklearn_available() is False


class TestRequireSklearn:
    """Tests for require_sklearn function."""

    def test_does_not_raise_when_available(self) -> None:
        """Test no exception when sklearn is available."""
        with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
            require_sklearn("cluster threshold computation")

    def test_raises_when_not_available(self) -> None:
        """Test raises MissingLocalDependencyError when sklearn not available."""
        with (
            patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False),
            pytest.raises(MissingLocalDependencyError) as exc_info,
        ):
            require_sklearn("cluster threshold computation")

        assert exc_info.value.dependency == LocalDependency.SKLEARN
        assert exc_info.value.feature == "cluster threshold computation"

    def test_error_message_contains_sklearn(self) -> None:
        """Test error message includes sklearn dependency name."""
        with (
            patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False),
            pytest.raises(MissingLocalDependencyError) as exc_info,
        ):
            require_sklearn("test feature")

        assert "sklearn" in str(exc_info.value)
        assert "nohiki-ml-core[inference]" in str(exc_info.value)
        assert "test feature" in str(exc_info.value)


class TestGetMinibatchKmeans:
    """Tests for get_minibatch_kmeans function."""

    def test_returns_minibatch_kmeans_class_when_available(self) -> None:
        """Test returns MiniBatchKMeans class when sklearn is available."""
        result = get_minibatch_kmeans("cluster threshold")

        assert result.__name__ == "MiniBatchKMeans"

    def test_raises_when_sklearn_not_available(self) -> None:
        """Test raises MissingLocalDependencyError when sklearn is unavailable."""
        with (
            patch.dict(sys.modules, {"sklearn": None, "sklearn.cluster": None}),
            pytest.raises(MissingLocalDependencyError) as exc_info,
        ):
            get_minibatch_kmeans("PLAID cluster threshold")

        assert exc_info.value.dependency == LocalDependency.SKLEARN
        assert exc_info.value.feature == "PLAID cluster threshold"

    def test_preserves_sklearn_import_error_as_cause(self) -> None:
        """The typed dependency error keeps the underlying import failure."""
        with (
            patch.dict(sys.modules, {"sklearn": None, "sklearn.cluster": None}),
            pytest.raises(MissingLocalDependencyError) as exc_info,
        ):
            get_minibatch_kmeans("test feature")

        assert isinstance(exc_info.value.__cause__, ImportError)
