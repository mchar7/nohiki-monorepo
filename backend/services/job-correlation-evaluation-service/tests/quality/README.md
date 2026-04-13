# Data Analyst ranking quality gate

This directory contains two permanent regression controls: a sanitized 48-listing candidate universe judged against a
synthetic Senior Data Analyst intent, and a nonsense-query profile as a negative control. This is one adversarial
slice, not a claim of general ranking quality.

## Fixture and provenance

`fixtures/data_analyst_48.v1.json` preserves the 48 persisted listing inputs, but does **not** claim the live profile
was a Data Analyst profile. It was named `Jeffe`, contained the gibberish keyword `hyfr`, and had no skills. Database
IDs, URLs, employer names, and contact details were removed; stable `DA-01` through `DA-48` IDs replace source IDs.
Human judgments use a clearly labeled synthetic Senior Data Analyst intent. `DA-11` is the Virtual K-5th Grade
Principal sentinel. The fixture contains corrected QUERY-mode semantic inputs for the synthetic intent. Legacy
DOCUMENT-mode values remain separately named for the nonsense-query negative control and are never used as analyst
relevance evidence.

`provenance.ranking_inputs_sha256` covers the canonical profile and candidate ranking inputs, excluding judgment text
and descriptions. The loader rejects count, ID, label, semantic-input, support, or checksum corruption. A candidate
replacement requires a new schema/version and review; judgments must never be edited merely to make the ranker pass.

The fixture is regression data only. It must never be imported, copied, or generated into training data. The
repository's synthetic L2R data and feedback exports are not relevance ground truth. Current feedback events are
incomplete and selection-biased: `VIEWED` is exposure; saved, applied, liked, and disliked actions are weak outcomes
without a complete impression set and position data.

## Immutable relevance rubric

Reviewers see the target role, title, and sanitized description, but no semantic score, fit score, rank, feature
vector, or other review.

- **3 (direct):** the occupation and core duties directly match Data Analyst, with no hard contradiction.
- **2 (adjacent):** a credible adjacent occupation or transfer with substantive analytical duties.
- **1 (superficial):** shared skills or technology, but the occupation or material level is wrong.
- **0 (unrelated):** unrelated occupation or a hard contradiction. K-5 Principal is always grade 0.

Two independent blind reviewers graded all 48 candidates. Agreements were accepted; ten disagreements were
independently adjudicated. The fixture records reviewer aliases, both grades, final grade, review status, rubric
version, capture date, collection version, ranker-at-capture, and input checksum. Aliases identify review roles, not
people.

## Release gates

The test runs the real deterministic Stage 4 ranker against normal generated snapshots and the recorded semantic
inputs; it does not mock scoring or load a network, LightGBM, calibrator, or joblib artifact. Ranking uses the
unrounded ranking index. The corrected QUERY-mode ID-to-MaxSim map and reviewed checksum make this an active release
gate; the test fails on any violated quality floor.

Required floors:

- NDCG@5 ≥ 0.90 and NDCG@10 ≥ 0.85, with gains $2^{grade}-1$.
- MRR of grade-3 candidates = 1.
- Precision@5 for grade ≥2 ≥ 0.80.
- No grade-0 candidate in the top five; every grade 3 above every grade 0.
- `DA-11` outside the top ten and below every grade ≥2 candidate.
- Displayed-score range ≥15, P90 minus P10 ≥10, at least 10 integer buckets, largest bucket ≤12.
- Best grade-3 score minus best grade-0 score ≥10.

The evaluator prints the violated gates, complete metric values, score histogram, and diagnostic top ten on failure.
Metric-oracle tests independently cover perfect, reversed, and non-first relevant rankings plus percentile
boundaries.

Run only the focused gate:

```sh
uv run --project backend/services/job-correlation-evaluation-service pytest backend/services/job-correlation-evaluation-service/tests/quality/test_data_analyst_ranking_quality.py
```

The public integer score is a relative fit ranking index on 0-100, not a probability, calibrated confidence, or
cross-profile quality claim.
