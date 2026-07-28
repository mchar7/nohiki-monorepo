"""Tests for nohiki_ml_core package initialization and lazy imports."""

from __future__ import annotations

import contextlib
import importlib
import sys
from unittest.mock import patch

import pytest


class TestLazyImports:
    """Tests for lazy import functionality in __init__.py."""

    def test_invalid_attribute_raises_error(self) -> None:
        """Test that accessing invalid attribute raises AttributeError."""
        import nohiki_ml_core

        with pytest.raises(AttributeError) as exc_info:
            _result = nohiki_ml_core.NonExistentClass

        assert "has no attribute 'NonExistentClass'" in str(exc_info.value)

    def test_all_exports_in_lazy_imports(self) -> None:
        """Test that all exports in __all__ are covered by lazy imports."""
        from nohiki_ml_core import _LAZY_IMPORTS, __all__

        lazy_import_names = set(_LAZY_IMPORTS.keys())
        expected_lazy = {
            "ColBERTEncoder",
            "DenseBatchEncodingResult",
            "DenseEncoder",
            "MUVERAEncoder",
            "SparseEncoder",
            "SparseVector",
            "DenseEncodingResult",
            "EncodingResult",
            "MLEncodingPipeline",
            "ModelCacheManager",
            "ModelArchive",
            "SourceDownloader",
        }

        assert lazy_import_names == expected_lazy

        # Verify all lazy imports are in __all__
        for name in lazy_import_names:
            assert name in __all__, f"{name} should be in __all__"

    def test_lazy_import_map_structure(self) -> None:
        """Test that _LAZY_IMPORTS has correct structure."""
        from nohiki_ml_core import _LAZY_IMPORTS

        for name, (module_path, attr_name) in _LAZY_IMPORTS.items():
            assert isinstance(name, str)
            assert isinstance(module_path, str)
            assert isinstance(attr_name, str)
            assert module_path.startswith("nohiki_ml_core.")
            assert attr_name == name


class TestModuleImports:
    """Tests for module-level imports."""

    def test_eager_imports_available(self) -> None:
        """Test that eagerly imported items are available."""
        import nohiki_ml_core

        eager_imports = [
            "ComputeBackend",
            "GpuCapabilities",
            "GpuNotAvailableError",
            "detect_gpu_capabilities",
            "get_available_backend",
            "require_gpu",
            "reset_gpu_detection_cache",
            "validate_compute_backend",
            "LocalDependency",
            "MissingLocalDependencyError",
            "check_pylate_available",
            "require_fastembed",
            "require_pylate",
        ]

        for name in eager_imports:
            assert hasattr(nohiki_ml_core, name), f"Missing eager import: {name}"

    def test_all_list_complete(self) -> None:
        """Test that __all__ contains all expected exports."""
        from nohiki_ml_core import __all__

        assert len(__all__) == 26

        key_items = [
            "ColBERTEncoder",
            "DenseEncoder",
            "MUVERAEncoder",
            "SparseEncoder",
            "MLEncodingPipeline",
            "ComputeBackend",
            "GpuCapabilities",
        ]

        for item in key_items:
            assert item in __all__, f"{item} should be in __all__"

    def test_lazy_loaded_modules_not_imported_initially(self) -> None:
        """Test that lazy-loaded modules are not imported on initial import."""
        lazy_modules = [
            "nohiki_ml_core.encoders.colbert",
            "nohiki_ml_core.encoders.dense",
            "nohiki_ml_core.encoders.muvera",
            "nohiki_ml_core.encoders.sparse",
            "nohiki_ml_core.pipeline",
        ]

        with patch.dict(sys.modules):
            for name in tuple(sys.modules):
                if name == "nohiki_ml_core" or name.startswith("nohiki_ml_core."):
                    del sys.modules[name]

            importlib.import_module("nohiki_ml_core")

            for mod in lazy_modules:
                assert mod not in sys.modules, f"{mod} should not be loaded yet"

    def test_accessing_lazy_import_loads_module(self) -> None:
        """Test that accessing a lazy import loads the module."""
        with patch.dict(sys.modules):
            for name in tuple(sys.modules):
                if name == "nohiki_ml_core" or name.startswith("nohiki_ml_core."):
                    del sys.modules[name]

            nohiki_ml_core = importlib.import_module("nohiki_ml_core")

            with contextlib.suppress(Exception):
                _ = nohiki_ml_core.ColBERTEncoder

            assert "nohiki_ml_core.encoders.colbert" in sys.modules
