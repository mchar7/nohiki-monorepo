from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_OPENAPI = _ROOT / "docs" / "api" / "nohiki.openapi.json"
_TYPESCRIPT = _ROOT / "typescript" / "apps" / "frontend" / "src" / "api" / "schema.d.ts"


def test_upload_headers_match_canonical_openapi_and_generated_typescript() -> None:
    document = json.loads(_OPENAPI.read_text(encoding="utf-8"))
    response = document["components"]["schemas"]["InitiateUploadResponse"]
    headers = response["properties"]["upload_headers"]

    assert headers == {
        "additionalProperties": {"type": "string"},
        "type": "object",
        "title": "Upload Headers",
    }
    assert "upload_headers" in response["required"]

    generated = _TYPESCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"InitiateUploadResponse:\s*\{(?P<body>.*?)^\s{8}\};",
        generated,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "generated InitiateUploadResponse is missing"
    assert re.search(
        r"^\s*upload_headers:\s*\{\s*^\s*\[key: string\]: string;\s*^\s*\};$",
        match.group("body"),
        re.MULTILINE,
    )
