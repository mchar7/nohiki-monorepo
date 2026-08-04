# Calibrate Skill Thresholds

Empirically calibrate Jaccard similarity thresholds for skill normalization.

## Purpose

Analyzes Tabiya ESCO taxonomy data to find optimal thresholds for:

- Auto-canonicalization of skill names
- Distinguishing true synonyms from distinct-but-similar skills
- Minimizing false positives in skill matching

## Usage

```bash
# Install dependencies
cd scripts/ml/calibrate_skill_thresholds
uv sync

# Run full calibration analysis
uv run calibrate-skill-thresholds analyze

# Quick check without full analysis
uv run calibrate-skill-thresholds quick

# View previously generated report
uv run calibrate-skill-thresholds report calibration_report.json
```

## Commands

| Command | Description |
| --------- | ------------- |
| `analyze` | Run full Jaccard similarity threshold analysis |
| `quick` | Quick check: load data and show basic statistics |
| `report` | Display a previously generated calibration report |

## Output

Generates `calibration_report.json` with:

- Distribution statistics for synonym and distinct pairs
- Threshold analysis at multiple levels (0.65-0.99)
- Zero false-positive threshold recommendation
- Example false positives/negatives for review

## Architecture

```text
calibrate_skill_thresholds/
├── cli.py               # Typer CLI entry point
├── analysis/analysis.py # Jaccard similarity analysis
├── data.py              # Dataset loading and bounded pair generation
├── display.py           # Rich console output formatting
└── synthetic_tests.py   # Curated threshold smoke checks
```

## Data Source

Uses the Tabiya ESCO taxonomy from `data/tabiya/skills.csv`. The CSV must contain
`ID` and `PREFERREDLABEL` columns; `ALTLABELS`, `SKILLTYPE`, and `DESCRIPTION`
are consumed when present. Pair sampling is deterministic for a given seed and
bounded by the CLI limits.
