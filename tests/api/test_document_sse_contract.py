import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = REPOSITORY_ROOT / "docs" / "api" / "nohiki.openapi.json"
SSE_PATH = "/api/documents/{request_id}/events"


@pytest.fixture(scope="module")
def openapi_contract() -> dict[str, object]:
    contract = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert isinstance(contract, dict)
    return contract


@pytest.mark.unit
def test_document_sse_contract_is_exact_request_scoped(
    openapi_contract: dict[str, object],
) -> None:
    paths = openapi_contract["paths"]
    assert isinstance(paths, dict)

    assert SSE_PATH in paths
    assert "/api/v1/documents/events" not in paths
    assert "/api/documents/events" not in paths

    operation_path = paths[SSE_PATH]
    assert isinstance(operation_path, dict)
    operation = operation_path["get"]
    assert isinstance(operation, dict)
    parameters = operation["parameters"]
    assert isinstance(parameters, list)

    assert parameters[0] == {
        "name": "request_id",
        "in": "path",
        "required": True,
        "schema": {
            "type": "string",
            "format": "uuid",
            "title": "Request Id",
        },
    }


@pytest.mark.unit
def test_document_sse_contract_accepts_cursor_only_in_last_event_id_header(
    openapi_contract: dict[str, object],
) -> None:
    paths = openapi_contract["paths"]
    assert isinstance(paths, dict)
    operation_path = paths[SSE_PATH]
    assert isinstance(operation_path, dict)
    operation = operation_path["get"]
    assert isinstance(operation, dict)
    parameters = operation["parameters"]
    assert isinstance(parameters, list)

    cursor_parameters = [
        parameter
        for parameter in parameters
        if isinstance(parameter, dict) and parameter.get("name") == "Last-Event-ID"
    ]
    assert len(cursor_parameters) == 1
    assert cursor_parameters[0]["in"] == "header"
    assert cursor_parameters[0]["required"] is False
    assert not any(isinstance(parameter, dict) and parameter.get("in") == "query" for parameter in parameters)
