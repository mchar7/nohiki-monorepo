r"""Instruction prefix mapping for Qwen3-Embedding task-specific training.

Qwen3-Embedding uses ``Instruct: {task}\\nQuery: {text}`` on query-side (anchor)
inputs. Positives (document-side) receive no prefix. This asymmetry teaches the
model to differentiate between "what to search for" and "what to search in."

See: Qwen3 Embedding paper (arXiv:2506.05176), Section 3.2.
"""

from __future__ import annotations

from typing import Final

from job_embedding_finetuning.dataset_adapters.base import TrainingPair

INSTRUCTION_MAP: Final[dict[str, str]] = {
    "occupation_skill": "Instruct: Retrieve required skills for this job title\nQuery: ",
    "skill_synonym": "Instruct: Find semantically equivalent skill names\nQuery: ",
    "occupation_synonym": "Instruct: Find alternative job titles for this role\nQuery: ",
    "skill_relationship": "Instruct: Find related technical skills\nQuery: ",
    "career_transition": "Instruct: Find the logical next career step\nQuery: ",
    "sentence_skill": "Instruct: Extract the core skill from this sentence\nQuery: ",
    "label_description": "Instruct: Match this job title to its description\nQuery: ",
    "skill_description": "Instruct: Match this skill name to its definition\nQuery: ",
    "occupation_description": "Instruct: Match this occupation to its description\nQuery: ",
    "job_description": "Instruct: Match this job title to its description\nQuery: ",
    "career_progression": "Instruct: Find the logical next career step\nQuery: ",
}

DEFAULT_INSTRUCTION: Final[str] = "Instruct: Retrieve semantically similar job titles and skills\nQuery: "


def apply_instruction_prefix(pair: TrainingPair) -> TrainingPair:
    """Apply task-specific instruction prefix to the anchor.

    Positives NEVER receive instruction prefix — this is how Qwen3
    differentiates between query and document.

    Args:
        pair: Training pair with anchor, positive, and pair_type.

    Returns:
        New TrainingPair with instruction-prefixed anchor.
    """
    prefix = INSTRUCTION_MAP.get(pair.pair_type, DEFAULT_INSTRUCTION)
    return TrainingPair(
        anchor=f"{prefix}{pair.anchor}",
        positive=pair.positive,
        negative=pair.negative,
        label=pair.label,
        source_dataset=pair.source_dataset,
        pair_type=pair.pair_type,
    )
