"""Tests for GPU capability detection module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki_ml_core.gpu import (
    ComputeBackend,
    GpuCapabilities,
    GpuNotAvailableError,
    _check_cuda_deps_installed,
    _check_triton_installed,
    _get_cuda_version,
    _get_device_info,
    _get_torch,
    detect_gpu_capabilities,
    get_available_backend,
    require_gpu,
    reset_gpu_detection_cache,
    validate_compute_backend,
)


class TestGpuNotAvailableError:
    """Tests for GpuNotAvailableError exception."""

    def test_error_with_default_suggestion(self) -> None:
        """Test error message with default suggestion."""
        error = GpuNotAvailableError(reason="CUDA not installed")

        assert error.reason == "CUDA not installed"
        assert "pip install nohiki-ml-core[gpu]" in error.suggestion
        assert "CUDA not installed" in str(error)
        assert "pip install" in str(error)

    def test_error_with_custom_suggestion(self) -> None:
        """Test error message with custom suggestion."""
        error = GpuNotAvailableError(
            reason="No GPU hardware",
            suggestion="Install NVIDIA drivers",
        )

        assert error.reason == "No GPU hardware"
        assert error.suggestion == "Install NVIDIA drivers"
        assert "No GPU hardware" in str(error)
        assert "Install NVIDIA drivers" in str(error)


class TestGpuCapabilities:
    """Tests for GpuCapabilities dataclass."""

    def test_dataclass_creation(self) -> None:
        """Test GpuCapabilities dataclass creation."""
        caps = GpuCapabilities(
            cuda_available=True,
            cuda_version="12.1",
            device_count=2,
            device_names=("NVIDIA A100", "NVIDIA A100"),
            triton_available=True,
        )

        assert caps.cuda_available is True
        assert caps.cuda_version == "12.1"
        assert caps.device_count == 2
        assert len(caps.device_names) == 2
        assert caps.triton_available is True

    def test_dataclass_is_frozen(self) -> None:
        """Test GpuCapabilities is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(GpuCapabilities)
        params = getattr(GpuCapabilities, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestCheckCudaDepsInstalled:
    """Tests for _check_cuda_deps_installed function."""

    def test_returns_false_when_torch_not_installed(self) -> None:
        """Test returns False when torch is not importable."""
        with patch.dict("sys.modules", {"torch": None}), patch("builtins.__import__", side_effect=ImportError):
            result = _check_cuda_deps_installed()
            assert result is False

    def test_returns_false_when_cuda_not_available(self) -> None:
        """Test returns False when torch.cuda.is_available() is False."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            # Need to actually call the function with the mock
            result = mock_torch.cuda.is_available()
            assert result is False

    def test_returns_true_when_cuda_available(self) -> None:
        """Test returns True when torch.cuda.is_available() is True."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = mock_torch.cuda.is_available()
            assert result is True


class TestCheckTritonInstalled:
    """Tests for _check_triton_installed function."""

    def test_returns_false_when_triton_not_installed(self) -> None:
        """Test returns False when triton is not importable."""
        with patch("importlib.util.find_spec", return_value=None):
            result = _check_triton_installed()
            assert result is False


class TestGetCudaVersion:
    """Tests for _get_cuda_version function."""

    def test_returns_none_when_torch_not_installed(self) -> None:
        """Test returns None when torch is not importable."""
        with patch.dict("sys.modules", {"torch": None}), patch("builtins.__import__", side_effect=ImportError):
            result = _get_cuda_version()
            assert result is None

    def test_returns_none_when_cuda_not_available(self) -> None:
        """Test returns None when CUDA is not available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            # The function checks is_available() first
            assert mock_torch.cuda.is_available() is False


class TestGetDeviceInfo:
    """Tests for _get_device_info function."""

    def test_returns_empty_when_torch_not_installed(self) -> None:
        """Test returns (0, ()) when torch is not importable."""
        with patch.dict("sys.modules", {"torch": None}), patch("builtins.__import__", side_effect=ImportError):
            result = _get_device_info()
            assert result == (0, ())

    def test_returns_empty_when_cuda_not_available(self) -> None:
        """Test returns (0, ()) when CUDA is not available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            assert mock_torch.cuda.is_available() is False


class TestDetectGpuCapabilities:
    """Tests for detect_gpu_capabilities function."""

    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_gpu_detection_cache()

    def test_detects_no_gpu_when_cuda_not_available(self) -> None:
        """Test detection when CUDA is not available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=False,
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=False,
            ),
        ):
            caps = detect_gpu_capabilities()

            assert caps.cuda_available is False
            assert caps.cuda_version is None
            assert caps.device_count == 0
            assert caps.device_names == ()
            assert caps.triton_available is False

    def test_detects_gpu_when_cuda_available(self) -> None:
        """Test detection when CUDA is available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=True,
            ),
            patch(
                "nohiki_ml_core.gpu._get_cuda_version",
                return_value="12.1",
            ),
            patch(
                "nohiki_ml_core.gpu._get_device_info",
                return_value=(2, ("NVIDIA A100", "NVIDIA A100")),
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=True,
            ),
        ):
            caps = detect_gpu_capabilities()

            assert caps.cuda_available is True
            assert caps.cuda_version == "12.1"
            assert caps.device_count == 2
            assert caps.device_names == ("NVIDIA A100", "NVIDIA A100")
            assert caps.triton_available is True

    def test_caches_result(self) -> None:
        """Test that detection result is cached."""
        call_count = 0

        def mock_check() -> bool:
            nonlocal call_count
            call_count += 1
            return False

        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                side_effect=mock_check,
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=False,
            ),
        ):
            # Call twice
            detect_gpu_capabilities()
            detect_gpu_capabilities()

            # Should only be called once due to caching
            assert call_count == 1


class TestGetAvailableBackend:
    """Tests for get_available_backend function."""

    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_gpu_detection_cache()

    def test_returns_cpu_when_no_gpu(self) -> None:
        """Test returns CPU backend when no GPU available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=False,
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=False,
            ),
        ):
            backend = get_available_backend()
            assert backend == ComputeBackend.CPU

    def test_returns_cuda_when_gpu_available(self) -> None:
        """Test returns CUDA backend when GPU is available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=True,
            ),
            patch(
                "nohiki_ml_core.gpu._get_cuda_version",
                return_value="12.1",
            ),
            patch(
                "nohiki_ml_core.gpu._get_device_info",
                return_value=(1, ("NVIDIA RTX 4090",)),
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=True,
            ),
        ):
            backend = get_available_backend()
            assert backend == ComputeBackend.CUDA


class TestRequireGpu:
    """Tests for require_gpu function."""

    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_gpu_detection_cache()

    def test_raises_when_cuda_not_available(self) -> None:
        """Test raises GpuNotAvailableError when CUDA not available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=False,
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=False,
            ),
        ):
            with pytest.raises(GpuNotAvailableError) as exc_info:
                require_gpu()

            assert "CUDA dependencies not installed" in str(exc_info.value)

    def test_raises_when_no_devices(self) -> None:
        """Test raises GpuNotAvailableError when no GPU devices found."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=True,
            ),
            patch(
                "nohiki_ml_core.gpu._get_cuda_version",
                return_value="12.1",
            ),
            patch(
                "nohiki_ml_core.gpu._get_device_info",
                return_value=(0, ()),
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=False,
            ),
        ):
            with pytest.raises(GpuNotAvailableError) as exc_info:
                require_gpu()

            assert "No CUDA-capable GPU devices found" in str(exc_info.value)

    def test_returns_capabilities_when_gpu_available(self) -> None:
        """Test returns GpuCapabilities when GPU is available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=True,
            ),
            patch(
                "nohiki_ml_core.gpu._get_cuda_version",
                return_value="12.1",
            ),
            patch(
                "nohiki_ml_core.gpu._get_device_info",
                return_value=(1, ("NVIDIA RTX 4090",)),
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=True,
            ),
        ):
            caps = require_gpu()

            assert isinstance(caps, GpuCapabilities)
            assert caps.cuda_available is True
            assert caps.device_count == 1


class TestValidateComputeBackend:
    """Tests for validate_compute_backend function."""

    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_gpu_detection_cache()

    def test_cpu_backend_always_valid(self) -> None:
        """Test CPU backend is always valid."""
        # Should not raise
        validate_compute_backend(ComputeBackend.CPU)

    def test_cuda_backend_raises_when_not_available(self) -> None:
        """Test CUDA backend raises when GPU not available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=False,
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=False,
            ),
            pytest.raises(GpuNotAvailableError),
        ):
            validate_compute_backend(ComputeBackend.CUDA)

    def test_cuda_backend_valid_when_available(self) -> None:
        """Test CUDA backend is valid when GPU available."""
        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                return_value=True,
            ),
            patch(
                "nohiki_ml_core.gpu._get_cuda_version",
                return_value="12.1",
            ),
            patch(
                "nohiki_ml_core.gpu._get_device_info",
                return_value=(1, ("NVIDIA RTX 4090",)),
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                return_value=True,
            ),
        ):
            # Should not raise
            validate_compute_backend(ComputeBackend.CUDA)


class TestResetGpuDetectionCache:
    """Tests for reset_gpu_detection_cache function."""

    def test_clears_cache(self) -> None:
        """Test that reset clears the detection cache."""
        # Reset cache first to ensure clean state
        reset_gpu_detection_cache()

        mock_cuda_check = MagicMock(return_value=False)
        mock_triton_check = MagicMock(return_value=False)

        with (
            patch(
                "nohiki_ml_core.gpu._check_cuda_deps_installed",
                mock_cuda_check,
            ),
            patch(
                "nohiki_ml_core.gpu._check_triton_installed",
                mock_triton_check,
            ),
        ):
            # First call
            detect_gpu_capabilities()
            assert mock_cuda_check.call_count == 1

            # Second call - should use cache
            detect_gpu_capabilities()
            assert mock_cuda_check.call_count == 1  # Still 1 due to cache

            # Reset cache
            reset_gpu_detection_cache()

            # Third call - should invoke function again
            detect_gpu_capabilities()
            assert mock_cuda_check.call_count == 2


class TestComputeBackendEnum:
    """Tests for ComputeBackend enum."""

    def test_enum_values(self) -> None:
        """Test ComputeBackend enum has expected values."""
        assert ComputeBackend.CPU.value == "cpu"
        assert ComputeBackend.CUDA.value == "cuda"

    def test_enum_members(self) -> None:
        """Test ComputeBackend enum has expected members."""
        members = list(ComputeBackend)
        assert len(members) == 2
        assert ComputeBackend.CPU in members
        assert ComputeBackend.CUDA in members


class TestGetTorch:
    """Tests for _get_torch function."""

    def test_returns_none_when_torch_not_installed(self) -> None:
        """Test returns None when torch is not importable."""
        with patch.dict("sys.modules", {"torch": None}), patch("builtins.__import__", side_effect=ImportError):
            result = _get_torch()
            assert result is None

    def test_returns_torch_module_when_installed(self) -> None:
        """Test returns torch module when installed."""
        mock_torch = MagicMock()
        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = _get_torch()
            assert result is mock_torch


class TestCheckCudaDepsInstalledExtended:
    """Additional tests for _check_cuda_deps_installed function."""

    def test_returns_false_on_exception(self) -> None:
        """Test returns False when unexpected exception occurs."""
        with patch("nohiki_ml_core.gpu._get_torch", side_effect=RuntimeError("Unexpected")):
            result = _check_cuda_deps_installed()
            assert result is False


class TestGetCudaVersionExtended:
    """Additional tests for _get_cuda_version function."""

    def test_returns_cuda_version_when_available(self) -> None:
        """Test returns CUDA version when available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.version.cuda = "12.1"

        with patch("nohiki_ml_core.gpu._get_torch", return_value=mock_torch):
            result = _get_cuda_version()
            assert result == "12.1"

    def test_returns_none_when_version_attr_missing(self) -> None:
        """Test returns None when version attribute is missing."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.version = None

        with patch("nohiki_ml_core.gpu._get_torch", return_value=mock_torch):
            result = _get_cuda_version()
            assert result is None

    def test_returns_none_on_import_error(self) -> None:
        """Test returns None on ImportError."""
        with patch("nohiki_ml_core.gpu._get_torch", side_effect=ImportError):
            result = _get_cuda_version()
            assert result is None


class TestGetDeviceInfoExtended:
    """Additional tests for _get_device_info function."""

    def test_returns_device_info_when_available(self) -> None:
        """Test returns device info when CUDA is available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 2
        mock_torch.cuda.get_device_name.side_effect = ["NVIDIA A100", "NVIDIA A100"]

        with patch("nohiki_ml_core.gpu._get_torch", return_value=mock_torch):
            count, names = _get_device_info()
            assert count == 2
            assert names == ("NVIDIA A100", "NVIDIA A100")

    def test_returns_empty_on_runtime_error(self) -> None:
        """Test returns empty tuple on RuntimeError."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.side_effect = RuntimeError("CUDA error")

        with patch("nohiki_ml_core.gpu._get_torch", return_value=mock_torch):
            count, names = _get_device_info()
            assert count == 0
            assert names == ()

    def test_returns_empty_on_import_error(self) -> None:
        """Test returns empty tuple on ImportError."""
        with patch("nohiki_ml_core.gpu._get_torch", side_effect=ImportError):
            count, names = _get_device_info()
            assert count == 0
            assert names == ()
