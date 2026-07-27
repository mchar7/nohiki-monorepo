"""Dataset adapters for various job-related datasets.

Import all adapters to register them with the global registry.
"""

from __future__ import annotations

from job_embedding_finetuning.dataset_adapters.adapters import (
    data_jobs,
    job_description,
    jobhop,
    lang_uk,
    linkedin_jobs,
    tabiya_local,
    techwolf,
)

__all__ = [
    "data_jobs",
    "job_description",
    "jobhop",
    "lang_uk",
    "linkedin_jobs",
    "tabiya_local",
    "techwolf",
]
