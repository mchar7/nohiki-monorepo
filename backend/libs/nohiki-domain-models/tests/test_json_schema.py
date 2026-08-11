"""Tests for shared JSON Schema dialect selection."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError
from nohiki_domain_utils.json_schema import get_json_schema_validator
from referencing.exceptions import Unresolvable


def test_defaults_to_draft_2020_12() -> None:
    validator = get_json_schema_validator({"type": "object"})

    assert isinstance(validator, Draft202012Validator)


def test_selects_declared_draft_7() -> None:
    validator = get_json_schema_validator({"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"})

    assert isinstance(validator, Draft7Validator)


def test_resolves_local_definitions() -> None:
    validator = get_json_schema_validator(
        {
            "$defs": {"name": {"type": "string"}},
            "$ref": "#/$defs/name",
        }
    )

    assert validator.is_valid("Nohiki")
    assert not validator.is_valid(7)


def test_rejects_invalid_schema() -> None:
    with pytest.raises(SchemaError):
        get_json_schema_validator({"type": "nonsense"})


def test_remote_reference_never_performs_io() -> None:
    request_count = 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal request_count
            request_count += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/schema+json")
            self.end_headers()
            self.wfile.write(b'{"type":"object"}')

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        validator = get_json_schema_validator({"$ref": f"http://127.0.0.1:{server.server_port}/schema"})
        with pytest.raises(Unresolvable):
            list(validator.iter_errors({}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert request_count == 0
