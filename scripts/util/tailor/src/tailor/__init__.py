"""Nohiki Document Tailoring CLI.

IMPORTANT: Environment configuration MUST happen before any other imports.
Importing doc-template-service triggers module-level ``get_settings()`` calls
(e.g. in ``gotenberg.py``) which instantiate ``Settings(DatabaseMixin, RedisMixin,
KafkaMixin, S3Mixin, ...)``. These mixins require env vars for fields with no
defaults (``database.dsn``, ``database.schema_name``, ``s3.bucket``). The dummy
values below satisfy Pydantic validation so the CLI can import rendering utilities
without running full service infrastructure.
"""

from __future__ import annotations

import os

from nohiki_test_utils.paths import get_repo_root

_MONOREPO_ROOT = get_repo_root()
_SECRETS_DIR = _MONOREPO_ROOT / "infra" / "shared" / "secrets"

# Env var names MUST match the field paths in each mixin's settings model
# (e.g. ``RedisSettings.dsn`` → ``DOC_TEMPLATE_REDIS__DSN``).
_DOC_TEMPLATE_DEFAULTS = {
    "DOC_TEMPLATE_DATABASE__DSN": "postgresql://dummy:dummy@localhost:5432/dummy",
    "DOC_TEMPLATE_DATABASE__SCHEMA_NAME": "doc_template_schema",
    "DOC_TEMPLATE_REDIS__DSN": "redis://localhost:6379/0",
    "DOC_TEMPLATE_KAFKA__DSN": "kafka://localhost:29092",
    "DOC_TEMPLATE_S3__ENDPOINT": "http://localhost:9000",
    "DOC_TEMPLATE_S3__ACCESS_KEY": "dummy",
    "DOC_TEMPLATE_S3__SECRET_KEY": "dummy",
    "DOC_TEMPLATE_S3__BUCKET": "dummy",
    "DOC_TEMPLATE_GOTENBERG__BASE_URL": "http://localhost:3000",
    "DOC_TEMPLATE_GOTENBERG__REQUEST_TIMEOUT_S": "30",
    "SECRETS_DIR": str(_SECRETS_DIR),
}

for _key, _value in _DOC_TEMPLATE_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

__version__ = "0.1.0"
__all__ = ["__version__"]
