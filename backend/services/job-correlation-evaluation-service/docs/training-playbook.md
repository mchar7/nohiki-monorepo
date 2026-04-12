# L2R Model Training Playbook

This document provides operational guidance for training, evaluating, and deploying
Learning-to-Rank (L2R) models for the job correlation evaluation service.

## Overview

The L2R model is a LightGBM LambdaMART ranker that produces final correlation scores
from a 32-feature input vector. The model is trained on user feedback data collected
through the feedback service.

### Model Components

| Component | Format | Purpose |
|-----------|--------|---------|
| L2R Model | `.txt` (LightGBM) | LambdaMART ranking model |
| Calibrator | `.joblib` (sklearn) | Isotonic regression for score calibration |
| Metadata | `.json` | Version history and deployment info |

### Training Pipeline Steps

```text
1. DATA EXPORT       → Export labeled feedback from correlations table
2. DATA PREPARATION  → Convert to LightGBM Dataset, group by user
3. MODEL TRAINING    → LightGBM LambdaMART with early stopping
4. CALIBRATION       → Fit isotonic regression on validation set
5. EVALUATION        → Compute NDCG metrics
6. DEPLOYMENT        → Save versioned files, update metadata
```

## Prerequisites

- Access to the PostgreSQL database with job_correlation_schema
- Python environment with dependencies installed (`uv sync`)
- At least 1000 training samples with feedback (recommended: 5000+)

## Scripts

All scripts are located in `backend/job-correlation-evaluation-service/scripts/`:

| Script | Purpose |
|--------|---------|
| `train_l2r_model.py` | Train new model from feedback data |
| `evaluate_model.py` | Evaluate model performance |
| `deploy_model.py` | Deploy model version to production |

## Training Workflow

### Step 1: Check Training Data Availability

Before training, verify sufficient feedback data exists:

```bash
cd backend/job-correlation-evaluation-service

# Check feedback statistics via API
curl http://localhost:8000/api/v1/feedback/stats

# Or export training data to verify
uv run python scripts/train_l2r_model.py --min-samples 100 --dry-run
```

### Step 2: Train New Model

```bash
cd backend/job-correlation-evaluation-service

# Standard training (minimum 1000 samples)
uv run python scripts/train_l2r_model.py \
  --min-samples 1000 \
  --output-dir models/

# With custom parameters
uv run python scripts/train_l2r_model.py \
  --min-samples 5000 \
  --max-samples 50000 \
  --output-dir models/ \
  --version v2.0.0

# Training from exported JSON file
uv run python scripts/train_l2r_model.py \
  --data-file exported_training_data.json \
  --output-dir models/
```

### Step 3: Evaluate Model

Compare the new model against the production model:

```bash
# Export test data (hold out from training)
# ... export to test_data.json

# Evaluate new model
uv run python scripts/evaluate_model.py \
  --model-path models/l2r_lightgbm_v20251221.txt \
  --test-data test_data.json \
  --show-importance

# Compare models
uv run python scripts/evaluate_model.py \
  --compare models/l2r_lightgbm_bootstrap.txt models/l2r_lightgbm_v20251221.txt \
  --test-data test_data.json
```

### Step 4: Deploy Model

Once satisfied with the new model's performance:

```bash
# List available versions
uv run python scripts/deploy_model.py --list

# Deploy new version (dry run first)
uv run python scripts/deploy_model.py \
  --version v20251221_120000 \
  --dry-run

# Deploy for real
uv run python scripts/deploy_model.py \
  --version v20251221_120000

# Copy to deployment directory
uv run python scripts/deploy_model.py \
  --version v20251221_120000 \
  --deploy-dir /app/models
```

### Step 5: Verify Deployment

```bash
# Verify files exist and load correctly
uv run python scripts/deploy_model.py --verify

# Trigger rolling restart of services
kubectl rollout restart deployment job-correlation-evaluation-service
```

## Rollback Procedure

If the new model performs poorly in production:

```bash
# Rollback to previous version
uv run python scripts/deploy_model.py --rollback

# Or deploy a specific version
uv run python scripts/deploy_model.py --version v20251220_100000

# Restart services
kubectl rollout restart deployment job-correlation-evaluation-service
```

## Evaluation Metrics

### Primary Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **NDCG@10** | Normalized Discounted Cumulative Gain at 10 | > 0.80 |
| **NDCG@5** | NDCG at 5 | > 0.75 |
| **MRR** | Mean Reciprocal Rank | > 0.70 |

### Secondary Metrics

| Metric | Description |
|--------|-------------|
| Precision@5 | Relevant items in top 5 |
| Precision@10 | Relevant items in top 10 |

### Quality Gates

Before deploying a new model, verify:

1. **NDCG@10 >= current production model** (no regression)
2. **At least 1000 training samples** used
3. **Feature importance is reasonable** (no single feature > 50%)
4. **Model loads without errors**

## Feature Reference

The model uses 32 features in the following order:

| Index | Feature | Description |
|-------|---------|-------------|
| 0 | maxsim_score | ColBERT MaxSim score (Stage 2) |
| 1 | rerank_score | LLM reranker score (Stage 3) |
| 2 | distance_km | Distance to job location in kilometers |
| 3 | is_same_city | Whether job is in same city as user |
| 4 | is_remote_job | Whether job is fully remote |
| 5 | user_open_to_relocation | User open to relocation |
| 6 | user_experience_years | User years of experience |
| 7 | job_experience_min | Job minimum years required |
| 8 | job_experience_max | Job maximum years required |
| 9 | user_seniority_level | User seniority level |
| 10 | job_seniority_level | Job seniority level |
| 11 | user_min_salary | User minimum salary expectation |
| 12 | user_target_salary | User target salary |
| 13 | job_salary | Job offered salary |
| 14 | skill_match_count | Number of matched skills |
| 15 | skill_missing_count | Number of missing required skills |
| 16 | skill_total_required | Total required skills count |
| 17 | skill_avg_proficiency | Average proficiency of matched skills |
| 18 | skill_avg_provenance | Average provenance score of matched skills |
| 19 | skill_relationship_count | Count of skill graph relationships |
| 20 | skills_cosine_sim | Cosine similarity of skill embeddings |
| 21 | job_age_hours | Hours since job was posted |
| 22 | listing_feedback_count | Number of feedback signals on listing |
| 23 | listing_quality_score | LLM-derived listing quality score |
| 24 | work_arrangement_match | Remote/hybrid/onsite preference match |
| 25 | has_location_data | Whether location data is available |
| 26 | has_experience_data | Whether experience data is available |
| 27 | has_salary_data | Whether salary data is available |
| 28 | has_skill_data | Whether skill data is available |
| 29 | has_listing_quality | Whether listing quality score is available |
| 30 | skill_graph_min_distance | Minimum distance in skill graph |
| 31 | skill_graph_mean_distance | Mean distance in skill graph |

**CRITICAL:** Feature order must match `FEATURE_NAMES` in `constants.py`.

## Label Mapping

Feedback types map to training labels as follows:

| Feedback | Label | Description |
|----------|-------|-------------|
| Applied | 5.0 | User applied to job |
| Liked | 4.0 | Explicit positive signal |
| Saved | 3.5 | Intent to revisit |
| Viewed | 2.0 | Implicit positive |
| Dismissed | 0.5 | Explicit negative |
| Disliked | 0.0 | Strong negative |

## Training Schedule

Recommended training cadence:

| Stage | Frequency | Min Samples |
|-------|-----------|-------------|
| Initial (bootstrap) | Once | 100 |
| Early (first users) | Weekly | 1000 |
| Growth | Bi-weekly | 5000 |
| Mature | Monthly | 10000 |

## Monitoring

After deploying a new model, monitor:

1. **Correlation score distribution** - Should not shift dramatically
2. **User feedback rates** - Applied/saved rates should improve
3. **API latency** - Scoring time should remain stable
4. **Error rates** - No increase in scoring failures

## Troubleshooting

### "Insufficient samples" Error

```text
❌ Insufficient samples: 500 < 1000
```

**Cause:** Not enough feedback data collected yet.

**Solution:** Wait for more user feedback or lower `--min-samples` threshold.

### "Feature count mismatch" Error

```text
Feature count mismatch: expected 32, got 31
```

**Cause:** Training data has wrong number of features.

**Solution:** Re-export training data. Ensure feature vectors match `FEATURE_COUNT`.

### Model Won't Load

```text
Model file not found: models/l2r_lightgbm_v20251221.txt
```

**Cause:** Model file missing or wrong path.

**Solution:** Check `model_metadata.json` for correct file paths.

### Poor NDCG Scores

**Possible causes:**

1. **Insufficient data** - Need more training samples
2. **Label imbalance** - Too few positive labels
3. **Feature issues** - Check feature importance for anomalies

**Solutions:**

1. Collect more feedback before retraining
2. Adjust minimum sample threshold
3. Review feature engineering pipeline

## File Locations

| Environment | Model Path | Config |
|-------------|------------|--------|
| Development | `./models/` | `SCORING_L2R_MODEL_PATH` |
| Docker | `/app/models/` | ENV in Dockerfile |
| Kubernetes | ConfigMap mount | Helm values |

## Contact

For issues with the training pipeline, contact the ML team or file an issue
in the repository.
