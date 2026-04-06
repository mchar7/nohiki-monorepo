# Nohiki ML Manifest

Defines the canonical configuration for all ML semantic representations in Nohiki: a versioned,
JSON-serializable manifest that specifies which encoder models are active, what their parameters are,
which Qdrant collection version each entity type uses, and the normalization constants derived from
empirical calibration. Six services depend on it: `job-correlation-evaluation-service`,
`ml-compute-service`, `skill-graph-service`, `user-pref-service`, `job-ingest-enrichment-service`,
and `ml-gateway-service`. Without a shared manifest, each service would independently hardcode model
IDs, vector dimensions, and collection names, making coordinated model upgrades impossible and
embedding staleness checks unreliable.

## Quick Start

```python
from nohiki_ml_manifest import ManifestCache, ManifestMixin, SemanticRepresentationManifest
from nohiki_core_settings import NohikiBaseSettings
from pydantic_settings import SettingsConfigDict

# 1. Add ManifestMixin to your service settings
class Settings(ManifestMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")

# ManifestMixin validates that the file exists at startup (fail-fast).
# Default path: data/config/semantic_representation_manifest.json

# 2. Expose a get_manifest() helper in your config module
def get_manifest() -> SemanticRepresentationManifest:
    return ManifestCache.get(get_settings().manifest_path)

# 3. Use the manifest in handlers
manifest = get_manifest()

# Resolve collection name for Qdrant queries
collection_name = manifest.get_collection_name("job")   # → "jobs_v1"

# Check which encoder version is expected
version = manifest.get_entity_version("job")             # → "v1"

# Access encoder configuration
colbert_dim = manifest.late_interaction.token_dim        # → 48
muvera_dim  = manifest.muvera_output_dimension           # → 8192 (computed)
dense_model = manifest.dense.model_id                    # → "TechWolf/JobBERT-v2"
```

## Core Concepts

### The Manifest as Configuration Source of Truth

`SemanticRepresentationManifest` is a Pydantic model loaded from a JSON file at
`data/config/semantic_representation_manifest.json`. It contains all ML parameters that services
need to agree on: which models are in use, their dimensions, normalization constants, and which
Qdrant collection version each entity type targets. Nothing is hardcoded in service code. Every
parameter that affects embedding compatibility lives in the manifest file.

A model upgrade means editing the manifest JSON and incrementing the relevant collection version.
Services that load the manifest at startup will automatically use the new configuration on their
next deployment, with no code changes required.

### Collection Versioning and Embedding Staleness

Each entity type (`jobs`, `profiles`, `skills`, `occupations`) carries an independent version string
in the manifest. The Qdrant collection name is derived as `{entity}_{version}` -- for example,
`jobs_v1` or `skills_v3`. Incrementing the version for one entity type has no effect on the others.

This versioning is central to **embedding staleness detection**. An embedding stored alongside a
job listing is stale if *either* of these conditions is true:

1. **Content changed**: the `content_hash` of the source text no longer matches.
2. **Model changed**: the `collection_version` embedded with the vector no longer matches what the
   manifest declares for that entity type.

Checking only `content_hash` misses the second case because the text could be identical while the encoder
model could have been replaced with a new version that produces incompatible vectors. Services must
check both.

`EmbeddingValidator.validate_collection_version()` encodes this check: it raises `StaleDataError`
(from `nohiki-common-exceptions`) when a stored `collection_version` diverges from the manifest.

### Experimentation and Parallel Collections

The experimentation platform may assign a user or request to an experimental retrieval variant, but the
manifest remains the source of truth for embedding-model and semantic-representation compatibility. Every
retrieval variant must map to a concrete manifest `collection_version` and therefore to a separate Qdrant
collection.

Do not mix vectors from incompatible encoder versions in one collection. The safe rollout ladder is:

1. run offline held-out evaluation;
2. build a shadow collection such as `jobs_v2` alongside `jobs_v1`;
3. route internal/test cohort queries to the matching query encoder + collection version;
4. expose a small private cohort only after shadow validation and cost approval;
5. promote by changing the manifest default collection version;
6. retire the old collection after the retention/backfill window.

Events and commands affected by a user-facing embedding experiment carry experiment assignment context plus
the concrete `collection_version`. Entity lifecycle backfills do not need user experiment context; they are
governed by the manifest version they are rebuilding.

### ManifestCache: Process-Wide Singleton

`ManifestCache` holds a single loaded `SemanticRepresentationManifest` instance per process.
The first call to `ManifestCache.get(path)` loads and validates the JSON file; every subsequent
call returns the cached instance regardless of the path argument. This avoids redundant disk reads
across handlers that run concurrently within the same service process.

Every service that uses the manifest exposes a `get_manifest()` function in its `config.py` that
delegates to `ManifestCache.get(get_settings().manifest_path)`. This is the canonical access
pattern across all consumer services.

### Encoder Configurations

The manifest holds one configuration block per encoder type:

- **`late_interaction`** (`LateInteractionConfig`): ColBERT late-interaction model. Specifies
  `model_id`, `token_dim` (48), `max_length`, and `normalization` constants for MaxSim score
  scaling. Supports `DIRECT`, `TEI`, and `ONNX` inference backends.

- **`muvera`** (`MuveraConfig`): MUVERA Fixed-Dimensional Encoding parameters. The output
  dimension is computed as `2^k_sim * dim_proj * r_reps` (default: `2^6 * 16 * 8 = 8192`) and
  exposed as `manifest.muvera_output_dimension`. This is the dimension used for Stage 1 ANN
  retrieval in Qdrant.

- **`sparse`** (`SparseConfig`): MiniCOIL-style learned sparse embeddings. Carries normalization
  percentiles (`score_p10`, `score_p90`) for linear score scaling.

- **`dense`** (`DenseConfig`): Sentence-transformer dense embeddings (default: `TechWolf/JobBERT-v2`,
  1024 dimensions). Carries `auto_match_threshold` and `uncertain_min_threshold` used by
  `skill-graph-service` for skill canonicalization decisions.

### Qdrant Collection Schema

Each entity's `CollectionConfig` contains a `QdrantCollectionSchema` that declares the named
vectors for that collection. Role fields -- `primary_dense_name` and `colbert_name` -- explicitly
identify which named vector serves each purpose. This removes magic string matching from service
code: `nohiki-qdrant-client` reads the schema to know which vector to query for ANN vs. ColBERT
reranking.

`QdrantCollectionSchema` validates at construction time that role names reference existing entries
in `vectors`, and that any vector named as `colbert_name` declares `multivector_config`.

### L2R Feature Schema

> **Ownership note:** The L2R feature-schema constants live in `nohiki-ml-manifest`; the
> architectural target owner is `nohiki-l2r-core`. Any relocation must be atomic: export
> equivalent feature symbols from `nohiki-l2r-core`, update imports, and remove this feature
> module in one implementation change. `nohiki-ml-manifest` is the source of truth for L2R
> feature-schema constants consumed by the correlation service and offline training tooling.

`FeatureIndex`, `FEATURE_NAMES`, `FEATURE_DESCRIPTIONS`, `MONOTONE_CONSTRAINTS`, and
`CRITICAL_FEATURES` define the canonical 32-feature vector layout for the LightGBM L2R model.
These constants live in the manifest library so that both `job-correlation-evaluation-service`
(which builds feature vectors) and any MLOps tooling (which trains the model) reference the same
schema. The `FEATURE_COUNT` constant is the single authoritative value used by the service to
validate that a loaded model file has the expected feature count.

`MONOTONE_CONSTRAINTS` encodes domain knowledge directly into training: `DISTANCE_KM` is
constrained to `-1` (closer is always better), `SKILL_MATCH_COUNT` to `+1` (more matches always
better), `JOB_AGE_HOURS` to `-1` (fresher is better).

### Calibration Provenance

Normalization constants embedded in `MaxSimNormalizationConfig` and `DenseNormalizationConfig`
carry an optional `calibration` block (`MaxSimCalibrationConfig` / `DenseCalibrationConfig`) that
records the model used during calibration, sample count, and date. This tracks the empirical basis
for each threshold, which is essential for auditing when thresholds are updated after recalibration.

## API Reference

### Manifest

- **`SemanticRepresentationManifest`** -- Top-level Pydantic model. Load via
  `SemanticRepresentationManifest.load_from_path(path)` or construct directly for tests.
  - **`get_collection_name(entity_type)`** -- Returns the Qdrant collection name, e.g. `"jobs_v1"`.
    Accepts `EntityType` enum or strings `"job"` / `"jobs"`.
  - **`get_entity_version(entity_type)`** -- Returns the version string, e.g. `"v1"`.
  - **`get_collection_config(entity_type)`** -- Returns the full `CollectionConfig` for an entity.
  - **`muvera_output_dimension`** -- Computed property: `2^k_sim * dim_proj * r_reps`.
  - Raises `ValueError` for unknown entity types; `FileNotFoundError` / `ValueError` from
    `load_from_path` if the file is missing or malformed.

### Cache

- **`ManifestCache`** -- Process-wide singleton. Call `ManifestCache.get(path)` to retrieve the
  manifest; call `ManifestCache.reset()` in test teardown to clear state between tests.
- **`DEFAULT_MANIFEST_PATH`** -- `Path("data/config/semantic_representation_manifest.json")`.
  Used as the default for `ManifestMixin.manifest_path`.

### Validation

- **`EmbeddingValidator`** -- Validates embedding dimensions and collection versions against the
  manifest. Construct with a `SemanticRepresentationManifest` instance.
  - **`validate_collection_version(entity_type, collection_version, *, raise_on_mismatch=True)`** --
    Raises `StaleDataError` on mismatch (when `raise_on_mismatch=True`), returns `False` otherwise.
  - **`validate_muvera_dimension(actual_dimension, *, raise_on_mismatch=True)`** -- Raises
    `ValidationError` if the MUVERA vector length differs from `muvera_output_dimension`.
  - **`validate_dense_dimension(actual_dimension, *, raise_on_mismatch=True)`** -- Raises
    `ValidationError` if the dense vector length differs from `dense.embedding_dim`.
  - **`validate_colbert_token_dimension(actual_dimension, *, raise_on_mismatch=True)`** -- Raises
    `ValidationError` if the ColBERT token dimension differs from `late_interaction.token_dim`.
  - **`validate_embedding(values, entity_type, collection_version, embedding_type, *, raise_on_error=True)`** --
    Runs collection version + dimension checks in one call. Returns `EmbeddingValidationResult`.

- **`EmbeddingValidationResult`** -- Frozen dataclass with fields: `is_valid`, `expected_dimension`,
  `actual_dimension`, `entity_type`, `collection_version`.

### Settings

- **`ManifestMixin`** -- Pydantic settings mixin. Adds `manifest_path: Path` (default:
  `DEFAULT_MANIFEST_PATH`). Validates the file exists at settings construction time. Services fail
  immediately on startup rather than at first use if the manifest is missing.

### Collections

- **`CollectionsConfig`** -- Container for all four entity `CollectionConfig` instances: `jobs`,
  `profiles`, `skills`, `occupations`.
- **`CollectionConfig`** -- Per-entity config with `version` (pattern `^v\d+$`) and a
  `QdrantCollectionSchema`.
- **`QdrantCollectionSchema`** -- Named vector definitions with role fields `primary_dense_name`
  and optional `colbert_name`. Validates role references at construction time.
- **`QdrantVectorDefinition`** -- Single named vector: `size`, `distance` (`Dot`/`Cosine`/`Euclid`),
  optional `multivector_config` (required for ColBERT named vectors).

### Encoding

- **`LateInteractionConfig`** -- ColBERT config: `model_id`, `token_dim`, `max_length`,
  `normalization` (`MaxSimNormalizationConfig`), `inference_backend`.
- **`MuveraConfig`** -- MUVERA FDE config: `dim`, `k_sim`, `dim_proj`, `r_reps`, `random_seed`.
- **`SparseConfig`** -- Sparse config: `enabled`, `model_id`, `normalization`
  (`SparseNormalizationConfig` with `score_p10`, `score_p90`, computed `score_range`).
- **`DenseConfig`** -- Dense sentence embedding config: `model_id`, `embedding_dim`, `max_length`,
  `inference_backend`, `normalization` (`DenseNormalizationConfig` with thresholds and optional
  calibration provenance).
- **`InferenceBackend`** -- `StrEnum`: `DIRECT`, `TEI`, `ONNX`.

### Calibration

- **`BaseCalibrationConfig`** -- Base provenance: `calibration_model_id`, `calibration_pairs_count`,
  `calibration_date`.
- **`MaxSimCalibrationConfig`** -- Extends base; records empirical basis for ColBERT MaxSim
  normalization constants.
- **`DenseCalibrationConfig`** -- Extends base; adds `max_fp_similarity` (highest similarity
  observed on a false-positive pair, the empirical basis for `auto_match_threshold`).

### L2R Feature Schema

- **`FeatureIndex`** -- `IntEnum` with 32 members defining the canonical feature vector layout.
  Index positions are stable, so changing them breaks trained model files.
- **`FEATURE_COUNT`** -- `32` (authoritative constant for validation).
- **`FEATURE_NAMES`** -- `dict[FeatureIndex, str]` mapping each index to its snake_case name.
- **`FEATURE_NAME_LIST`** -- `list[str]` ordered by `FeatureIndex` value; used for DataFrame column
  headers in drift detection and logging.
- **`FEATURE_DESCRIPTIONS`** -- `dict[FeatureIndex, str]` human-readable descriptions.
- **`MONOTONE_CONSTRAINTS`** -- `list[int]` of `-1`, `0`, or `1` for LightGBM training constraints,
  indexed by `FeatureIndex` value.
- **`CRITICAL_FEATURES`** -- `frozenset[str]` of feature names that trigger elevated drift alerts.
  Currently `{"maxsim_score", "rerank_score"}`.

## Configuration

### ManifestMixin

Adds manifest path configuration to a service's Pydantic settings class:

- **`{PREFIX}MANIFEST_PATH`** -- Path to the manifest JSON file. Defaults to
  `data/config/semantic_representation_manifest.json`. The file must exist when settings are
  instantiated; the service fails at startup if it does not.

```python
class Settings(ManifestMixin, DatabaseMixin, KafkaMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
```

`ml-gateway-service` does not use `ManifestMixin` because it does not need fail-fast path
validation. It configures `manifest_path` directly as a `Path` field and calls
`ManifestCache.get()` manually.

## Testing

### Resetting the Cache

`ManifestCache` is a class-level singleton. Tests that load the manifest must reset the cache in
teardown to prevent cross-test contamination:

```python
import pytest
from nohiki_ml_manifest import ManifestCache

@pytest.fixture(autouse=True)
def reset_manifest_cache():
    ManifestCache.reset()
    yield
    ManifestCache.reset()
```

### Resolving the Manifest Path in Tests

Tests run from the package directory, not the repository root. Use `get_test_manifest_path()` from
the `testing` module to resolve the absolute path regardless of working directory:

```python
from nohiki_ml_manifest.testing import get_test_manifest_path
from nohiki_ml_manifest import ManifestCache

manifest = ManifestCache.get(get_test_manifest_path())
```

Service conftest files that need the manifest typically wire this into a session-scoped fixture:

```python
# In conftest.py
@pytest.fixture(autouse=True, scope="session")
def _load_manifest():
    from nohiki_ml_manifest import ManifestCache
    from nohiki_ml_manifest.testing import get_test_manifest_path
    ManifestCache.get(get_test_manifest_path())
    yield
    ManifestCache.reset()
```

### Building a Manifest in Tests

For unit tests that do not require the real manifest file:

```python
from nohiki_ml_manifest import (
    CollectionConfig,
    CollectionsConfig,
    QdrantCollectionSchema,
    QdrantVectorDefinition,
    SemanticRepresentationManifest,
)

qdrant_schema = QdrantCollectionSchema(
    vectors={"muvera": QdrantVectorDefinition(size=8192, distance="Dot")},
    has_sparse_vectors=True,
    primary_dense_name="muvera",
)
collections = CollectionsConfig(
    jobs=CollectionConfig(version="v1", qdrant=qdrant_schema),
    profiles=CollectionConfig(version="v1", qdrant=qdrant_schema),
    skills=CollectionConfig(
        version="v1",
        qdrant=QdrantCollectionSchema(
            vectors={"default": QdrantVectorDefinition(size=1024, distance="Cosine")},
            primary_dense_name="default",
        ),
    ),
    occupations=CollectionConfig(
        version="v1",
        qdrant=QdrantCollectionSchema(
            vectors={"default": QdrantVectorDefinition(size=1024, distance="Cosine")},
            primary_dense_name="default",
        ),
    ),
)
manifest = SemanticRepresentationManifest(collections=collections)
```

## Design Decisions

### Why a JSON file, not environment variables

Encoder configuration is structured, nested, and contains arrays and computed relationships
(e.g., MUVERA output dimension is derived from three parameters). Environment variables do not
model this well. The JSON manifest is version-controlled alongside code, diffed explicitly in
code review, and validated by Pydantic on load. The single file path exposed via `ManifestMixin`
is the only environment variable needed.

### Why per-entity collection versioning

Embedding models for different entity types evolve at different rates. Using a single global
version would force a full re-embedding of all entity types whenever any one model changes.
Per-entity versioning allows a skill model upgrade to proceed independently of the job embedding
model. Only `collections.skills.version` increments, and only the `skills_*` Qdrant collection
needs backfilling.

### Why `FeatureIndex` is moving out of the manifest library

The L2R feature schema must be shared between `job-correlation-evaluation-service` (which builds
the feature vectors) and any offline tooling that trains the LightGBM model. If `FeatureIndex`
lived inside the service, training scripts would have to depend on the service package or
duplicate the schema. `nohiki-ml-manifest` houses this schema because it is the shared home
available to both online and offline consumers. The architectural target owner is
`nohiki-l2r-core`, which keeps the L2R feature contract with scoring, training, artifact
validation, and hot-swap code while leaving this manifest library focused on semantic
representation and collection-version manifests.
