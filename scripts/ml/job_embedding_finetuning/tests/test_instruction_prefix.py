"""Tests for instruction prefix application."""

from __future__ import annotations

from job_embedding_finetuning.dataset_adapters.base import TrainingPair
from job_embedding_finetuning.processing.instruction_prefix import (
    DEFAULT_INSTRUCTION,
    INSTRUCTION_MAP,
    apply_instruction_prefix,
)


class TestApplyInstructionPrefix:
    """Verify instruction prefix application to training pairs."""

    def test_occupation_skill_prefix(self) -> None:
        """Occupation-skill pairs get the correct task instruction."""
        pair = TrainingPair(
            anchor="Software Engineer",
            positive="python",
            pair_type="occupation_skill",
            source_dataset="test",
        )
        result = apply_instruction_prefix(pair)
        assert result.anchor.startswith("Instruct: Retrieve required skills")
        assert result.anchor.endswith("Software Engineer")
        assert result.positive == "python"  # Positive unchanged

    def test_skill_synonym_prefix(self) -> None:
        """Skill synonym pairs get synonym-specific instruction."""
        pair = TrainingPair(
            anchor="javascript",
            positive="js",
            pair_type="skill_synonym",
            source_dataset="test",
        )
        result = apply_instruction_prefix(pair)
        assert "semantically equivalent" in result.anchor
        assert result.positive == "js"

    def test_unknown_pair_type_gets_default(self) -> None:
        """Unknown pair types fall back to the default instruction."""
        pair = TrainingPair(
            anchor="test",
            positive="test",
            pair_type="unknown_type",
            source_dataset="test",
        )
        result = apply_instruction_prefix(pair)
        assert "Retrieve semantically similar" in result.anchor

    def test_positive_never_gets_prefix(self) -> None:
        """Positives must NEVER receive an instruction prefix."""
        for pair_type in INSTRUCTION_MAP:
            pair = TrainingPair(
                anchor="anchor text",
                positive="positive text",
                pair_type=pair_type,
                source_dataset="test",
            )
            result = apply_instruction_prefix(pair)
            assert not result.positive.startswith("Instruct:")
            assert result.positive == "positive text"

    def test_all_pair_types_covered(self) -> None:
        """Every mapped pair type produces a non-default prefix."""
        for pair_type, expected_prefix in INSTRUCTION_MAP.items():
            pair = TrainingPair(
                anchor="test",
                positive="test",
                pair_type=pair_type,
                source_dataset="test",
            )
            result = apply_instruction_prefix(pair)
            assert result.anchor.startswith(expected_prefix), f"Pair type {pair_type!r} didn't get expected prefix"

    def test_metadata_preserved(self) -> None:
        """Pair metadata (label, source_dataset, pair_type, negative) is preserved."""
        pair = TrainingPair(
            anchor="test anchor",
            positive="test positive",
            negative="test negative",
            label=0.5,
            source_dataset="my-dataset",
            pair_type="occupation_skill",
        )
        result = apply_instruction_prefix(pair)
        assert result.negative == "test negative"
        assert result.label == 0.5
        assert result.source_dataset == "my-dataset"
        assert result.pair_type == "occupation_skill"

    def test_default_instruction_not_empty(self) -> None:
        """Default instruction must be a non-empty string with the Qwen3 format."""
        assert DEFAULT_INSTRUCTION
        assert "Instruct:" in DEFAULT_INSTRUCTION
        assert "Query: " in DEFAULT_INSTRUCTION
