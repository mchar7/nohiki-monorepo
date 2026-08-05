#!/usr/bin/env python3
"""Compatibility entry point for the packaged live-cluster CDC proof."""

from __future__ import annotations

from health_check.acceptance.live_cluster_cdc import main

if __name__ == "__main__":
    raise SystemExit(main())
