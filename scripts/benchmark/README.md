# LLM Benchmark Tool

This package compares independent model treatments against Nohiki's production job-extraction contract.
Deterministic gold metrics are the primary quality evidence. Optional LLM judges score only residual qualities
that cannot be checked against source-grounded labels.

## Measurement contract

Each experiment records and fingerprints:

- the production system prompt, bounded user prompt, output schema, and gold contract;
- every fixture and critical-branch tag;
- model, endpoint identity, reasoning effort, provider order, fallback policy, token limit, retries, timeout, and temperature;
- generation and evaluation budget policy;
- benchmark source and evaluation-policy versions.

The runner resumes an existing output only when it belongs to the same experiment. It rejects the file when any
treatment setting, the fixture set, the run count, or a contract/policy version differs. Choose a fresh
`--output` or pass `--fresh`. A fixture whose content changed since the saved run (its gold, prompt, or schema)
is not treated as a different experiment: the runner reruns only that fixture's cells and preserves every
unrelated and unchanged result, including across an interrupted resume. Automatic resume treats every persisted
attempted cell as final, including successes and failures, so it never silently re-runs a failed provider or
schema cell.

The default fixture suite contains 21 source-grounded curated cases. It covers the 15 job personas plus prompt
injection, French-language extraction, sparse input, no explicit compensation, remote ambiguity, and the
prompt-length boundary. These cases have not been human-adjudicated and must not be presented as a release-grade
gold corpus until that review occurs.

## Architecture

- `engine/runner.py`: independent treatment execution, immutable identities, and deterministic gold scoring
- `engine/budget.py`: atomic pre-dispatch cost reservation and global provider concurrency
- `engine/judge.py`: blinded residual judging with model-family independence
- `engine/checkpoint.py`: atomic checkpoint persistence and exact evaluation resume
- `schemas/gold.py`: field-level gold labels and deterministic scoring
- `schemas/metrics.py`: run, treatment, and experiment result models
- `schemas/judge.py`: residual subjective scoring schema
- `schemas/aggregation.py`: weighted judge consensus, reliability, and inter-rater agreement

## Model configuration

The benchmark does not define model defaults. Use either repeated `--model` arguments or a serialized standard
`nohiki-llm-client` `LLMSettings` document. `--llm-settings` and `--chain` reuse the provider, endpoint, routing,
and model-chain configuration used by services. The runner evaluates each model in the selected chain
independently, so fallback behavior cannot hide a candidate failure.

Keep credentials out of the settings document. The CLI loads provider keys from:

```text
infra/shared/secrets/llm/provider/api_keys/<provider>
```

The loader rejects `api_key` and `api_keys` fields in the settings document.

Keys are loaded only when a treatment or judge actually needs one. A pure-local (llama.cpp/Ollama) model, an
OpenAI-compatible endpoint pinned with an explicit `base_url`, or a run given an explicit `--api-key` requires no
secret directory. With `--llm-settings`, only the selected chain's providers decide this, so a cloud default
chain paired with a pure-local selected chain still needs no secrets. A cloud treatment whose key is unavailable
fails clearly before any model call.

For OpenRouter treatments, set `provider_order` and set `provider_allow_fallbacks` to `false` when provider and
quantization must remain fixed. For a local llama.cpp server, use the canonical `llamacpp:` provider with an
explicit per-model `base_url`.

Set `provider_zdr` to require OpenRouter Zero Data Retention routing. Provider order, fallback policy, and ZDR are
carried identically into judge dispatch, route-aware pricing, and the evaluation fingerprint, so routing never
silently widens on resume.

## Run an experiment

Set `BENCHMARK_OUTPUT_FILE` to the chosen result JSON file and `LLM_SETTINGS_FILE` to the settings file. Keep
generated results in an ignored local output directory.

```bash
: "${BENCHMARK_OUTPUT_FILE:?Set BENCHMARK_OUTPUT_FILE to the result JSON file}"
: "${LLM_SETTINGS_FILE:?Set LLM_SETTINGS_FILE to the settings file}"
uv run --package llm-benchmark llm-benchmark run \
  --output "$BENCHMARK_OUTPUT_FILE" \
  --llm-settings "$LLM_SETTINGS_FILE" \
  --chain benchmark_job_extraction \
  --cost-cap 100 \
  --unknown-price-max 1 \
  --concurrency 8
```

A small explicit-model smoke test can use the convenience form:

```bash
: "${BENCHMARK_SMOKE_OUTPUT_FILE:?Set BENCHMARK_SMOKE_OUTPUT_FILE to the smoke-test result JSON file}"
uv run --package llm-benchmark llm-benchmark run \
  --output "$BENCHMARK_SMOKE_OUTPUT_FILE" \
  --model openrouter:vendor/model \
  --fixture senior_python_remote \
  --max-tokens 4096 \
  --cost-cap 5 \
  --unknown-price-max 1
```

A local convenience run uses `--model ollama:<model>`; its endpoint comes from `--ollama-base-url` (defaulting to
the standard local Ollama URL) and needs no secret directory. Pass `--api-key` to point every treatment at a
custom OpenAI-compatible endpoint without a secrets file.

Use `--estimate-only` to inspect call volume and known pricing without contacting a model provider. Unknown prices
display `?`, but execution still requires a positive `--unknown-price-max` before any request is scheduled.

## Evaluate residual quality

The evaluator requires an explicit result file and at least one explicit judge. Candidate identity is absent from
the judge prompt. A judge is excluded from treatments in its own underlying model family, even when both models
use the same proxy transport.

The result file must be a benchmark result (`*.json`); the evaluator refuses an existing `*.eval.json` artifact
rather than overwrite it. Each judge must resolve to a distinct `provider:model` identity. A repeated model,
including the same model routed or configured differently, is rejected before dispatch because per-judge results,
checkpoints, and consensus weights are keyed by model.

```bash
: "${BENCHMARK_OUTPUT_FILE:?Set BENCHMARK_OUTPUT_FILE to the result JSON file}"
uv run --package llm-benchmark llm-benchmark evaluate \
  "$BENCHMARK_OUTPUT_FILE" \
  --judge-model openai:judge-a:high \
  --judge-model openai:judge-b:high \
  --judge-weight 1 \
  --judge-weight 1 \
  --base-url http://localhost:8000/v1 \
  --cost-cap 100 \
  --unknown-price-max 1
```

Judges score only:

1. inference reasonableness;
2. description quality;
3. downstream usefulness.

Deterministic schema, field, compensation, experience, location, skill, coverage, and hallucination checks remain
separate. A subjective judge cannot override a deterministic critical failure.

## Persistence and budgets

The generation and judge schedulers reserve worst-case call cost before entering the provider concurrency
semaphore. Unknown-price treatments require an explicit positive per-call maximum; a pure-local (llama.cpp or
Ollama) run is zero-cost and may omit `max_tokens`. Budget-rejected non-dispatches are never persisted, so a
later run can resume them exactly. Every attempted cell persists a budget-charged cost: the actual cost for known-price
successes and the worst-case reservation for unknown-price successes and dispatched failures. A resumed run
seeds its budget from that total charged cost. Repeated resume therefore cannot exceed the cap or forget a
failure's fail-closed charge, while realized provider spend is reported separately.

Generation results are written atomically after each completion. Evaluation checkpoints preserve the full
`(fixture, treatment, run, judge)` unit, including dispatched failures, and use keyed duplicate detection, so a
resumed run skips every attempted unit and seeds its budget from the persisted charged cost. Final evaluation
output is written durably (temp file, fsync, atomic replace, parent-directory fsync) to `<result>.eval.json` after
successful completion, and never overwrites the source result.

Generated results belong under the ignored local output directory chosen by the operator. Historical artifacts
should remain immutable and separate from active experiments.

## Other commands

```bash
# List fixture IDs
uv run --package llm-benchmark llm-benchmark fixtures

# Display one result
: "${BENCHMARK_OUTPUT_FILE:?Set BENCHMARK_OUTPUT_FILE to the result JSON file}"
uv run --package llm-benchmark llm-benchmark results "$BENCHMARK_OUTPUT_FILE"
```

## Verification

```bash
uv run --package llm-benchmark pytest scripts/benchmark/tests --tb=short
uv run ty check scripts/benchmark/src
uv run ruff check scripts/benchmark/src scripts/benchmark/tests
```

The package targets Python 3.14. Test counts change with the suite, so use the command output as the authority.
