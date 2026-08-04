# Skill Semantic Analysis

Semantic similarity threshold analysis for skill matching.

## Purpose

Tests many skill pairs to find optimal embedding similarity thresholds:

- Analyzes true positive pairs (synonyms, abbreviations)
- Analyzes true negative pairs (distinct skills)
- Finds optimal F1-score threshold
- Identifies problematic edge cases

## Usage

```bash
# Install dependencies
cd scripts/ml/skill_semantic_analysis
uv sync

# Run full threshold analysis
uv run skill-semantic analyze

# Quick check with key skill pairs
uv run skill-semantic quick

# View previously generated report
uv run skill-semantic report threshold_analysis_results.json
```

## Commands

| Command | Description |
| --------- | ------------- |
| `analyze` | Run full semantic similarity threshold analysis |
| `quick` | Quick check with a few key skill pairs |
| `report` | Display a previously generated analysis report |

## Output

Generates `threshold_analysis_results.json` with:

- Total pairs tested and classification counts
- Separation gap between true positives and true negatives
- Threshold analysis at multiple levels
- Best F1-score threshold recommendation
- Missed matches and false positives for review

## Architecture

```text
skill_semantic_analysis/
├── cli.py                    # Typer CLI entry point
└── analysis/
    ├── analysis.py           # Threshold analysis logic
    └── test_pairs.py         # Curated test pair definitions
```

## Model

Uses `TechWolf/JobBERT-v2` sentence transformer for computing semantic similarity between skill names.
