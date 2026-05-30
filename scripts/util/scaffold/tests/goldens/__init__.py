"""Invariant tests for scaffolded package output.

These tests render canonical archetype specs through ``build_plan`` and
assert semantic invariants on the rendered content (mixin order, shutdown
sequence, required imports, canonical pyproject, etc).

We intentionally do NOT snapshot byte-for-byte output — that churns noisily
on every template edit. Invariant assertions capture the patterns that
actually matter while staying resilient to cosmetic changes.
"""
