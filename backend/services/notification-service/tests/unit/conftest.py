"""Unit test configuration - minimal conftest without service imports."""

from __future__ import annotations

import os

# Set testing environment BEFORE any imports
os.environ["TESTING"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
