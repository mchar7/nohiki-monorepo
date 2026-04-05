"""Test configuration for nohiki-ml-core."""

import pytest


@pytest.fixture
def sample_manifest_data() -> dict[str, object]:
    """Sample manifest data for testing with per-collection versioning."""
    return {
        "collections": {
            "jobs": {
                "version": "v1",
                "description": "Test jobs collection",
                "qdrant": {
                    "vectors": {
                        "muvera": {"size": 8192, "distance": "Dot"},
                        "colbert": {
                            "size": 128,
                            "distance": "Cosine",
                            "multivector_config": {"comparator": "max_sim"},
                        },
                    },
                    "sparse": {},
                    "primary_dense_name": "muvera",
                    "colbert_name": "colbert",
                },
            },
            "profiles": {
                "version": "v1",
                "description": "Test profiles collection",
                "qdrant": {
                    "vectors": {
                        "muvera": {"size": 8192, "distance": "Dot"},
                        "colbert": {
                            "size": 128,
                            "distance": "Cosine",
                            "multivector_config": {"comparator": "max_sim"},
                        },
                    },
                    "sparse": {},
                    "primary_dense_name": "muvera",
                    "colbert_name": "colbert",
                },
            },
            "skills": {
                "version": "v1",
                "description": "Test skills collection",
                "qdrant": {
                    "vectors": {
                        "default": {"size": 1024, "distance": "Cosine"},
                        "colbert": {
                            "size": 128,
                            "distance": "Cosine",
                            "multivector_config": {"comparator": "max_sim"},
                        },
                    },
                    "primary_dense_name": "default",
                    "colbert_name": "colbert",
                },
            },
            "occupations": {
                "version": "v1",
                "description": "Test occupations collection",
                "qdrant": {
                    "vectors": {
                        "default": {"size": 1024, "distance": "Cosine"},
                    },
                    "primary_dense_name": "default",
                },
            },
        },
        "late_interaction": {
            "model_id": "mixedbread-ai/mxbai-edge-colbert-v0-17m",
            "token_dim": 48,
            "max_length": 32000,
        },
        "muvera": {
            "dim": 48,
            "k_sim": 6,
            "dim_proj": 16,
            "r_reps": 8,
            "random_seed": 42,
        },
        "sparse": {
            "enabled": True,
            "model_id": "Qdrant/minicoil-v1",
            "normalization": {
                "score_p10": 1.5,
                "score_p90": 5.5,
            },
        },
        "dense": {
            "enabled": True,
            "model_id": "TechWolf/JobBERT-v2",
            "normalization": {
                "auto_match_threshold": 0.83,
                "uncertain_min_threshold": 0.50,
                "calibration": {
                    "calibration_model_id": "TechWolf/JobBERT-v2",
                    "calibration_pairs_count": 85,
                    "calibration_date": "2025-01-07",
                    "max_fp_similarity": 0.8266,
                },
            },
        },
    }
