"""Behavior-grade security regressions for document rendering boundaries."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from doc_template_service.core.seeder import SEED_TEMPLATES_DIR
from doc_template_service.core.templates.jinja_engine import render_template
from doc_template_service.events.render_handler import _render_and_store
from doc_template_service.services.gotenberg import GotenbergError, GotenbergService
from doc_template_service.services.render_storage import store_rendered_document
from jinja2 import TemplateAssertionError
from nohiki.common.v1 import RenderOutputFormat
from nohiki_common_exceptions import ValidationError
from nohiki_proto_google.protobuf import Struct


@asynccontextmanager
async def _streaming_response(chunks: list[bytes]) -> AsyncIterator[MagicMock]:
    response = MagicMock()

    async def iter_bytes(*, chunk_size: int) -> AsyncIterator[bytes]:
        assert chunk_size > 0
        for chunk in chunks:
            yield chunk

    response.aiter_bytes = iter_bytes
    yield response


@pytest.mark.asyncio
async def test_untrusted_template_values_are_html_escaped() -> None:
    rendered = await render_template(
        "<p>{{ value }}</p>",
        {"value": '<img src=x onerror="alert(1)">'},
    )

    assert rendered == "<p>&lt;img src=x onerror=&#34;alert(1)&#34;&gt;</p>"


@pytest.mark.asyncio
async def test_safe_filter_is_rejected() -> None:
    with pytest.raises(TemplateAssertionError, match="No filter named 'safe'"):
        await render_template(
            "<p>{{ value | safe }}</p>",
            {"value": '<img src=x onerror="alert(1)">'},
        )


@pytest.mark.asyncio
async def test_seeded_resume_escapes_html_in_education_credentials() -> None:
    template = (SEED_TEMPLATES_DIR / "default_resume_template.html").read_text()
    assert "| safe" not in template
    credential = '<img src=x onerror="alert(1)">'
    rendered = await render_template(
        template,
        {
            "full_name": "Test User",
            "professional_title": "Engineer",
            "contact": {
                "email": "test@example.com",
                "phone": "555-0100",
                "location": "Remote",
                "website": "",
            },
            "experience": {"label": "Experience", "entries": []},
            "projects": {"label": "Projects", "entries": []},
            "skills": {"label": "Skills", "categories": []},
            "education": {
                "label": "Education",
                "entries": [
                    {
                        "period": {"start": "2020", "end": "2024"},
                        "credential": credential,
                        "institution": "Example University",
                    }
                ],
            },
            "certifications": {
                "label": "Certifications",
                "entries": [{"name": "Example", "date": "2024"}],
            },
            "hobbies": {"label": "Hobbies", "entries": []},
        },
    )

    assert credential not in rendered
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in rendered


@pytest.mark.asyncio
async def test_remote_resources_are_disabled_in_gotenberg_render_input() -> None:
    service = GotenbergService(base_url="http://gotenberg.test")
    execute = AsyncMock(return_value=b"%PDF")

    with patch.object(GotenbergService, "_execute_gotenberg_request", execute):
        await service.convert_html_to_pdf(
            '<html><head><title>x</title></head><body><img src="http://169.254.169.254/latest/meta-data"></body></html>'
        )

    assert execute.await_args is not None
    protected_html = execute.await_args.kwargs["files"]["files"][1]
    assert isinstance(protected_html, bytes)
    assert b'http-equiv="Content-Security-Policy"' in protected_html
    assert b"default-src 'none'" in protected_html
    assert b"img-src data:" in protected_html


@pytest.mark.asyncio
async def test_non_streaming_gotenberg_response_over_limit_is_rejected() -> None:
    service = GotenbergService(base_url="http://gotenberg.test")
    response = MagicMock(spec=httpx.Response)
    response.content = b"12345"

    with patch("doc_template_service.services.gotenberg.AsyncClient") as client_class:
        client_class.return_value.__aenter__.return_value.post = AsyncMock(return_value=response)
        with (
            patch("doc_template_service.services.gotenberg.MAX_RESPONSE_SIZE_BYTES", 4),
            pytest.raises(GotenbergError, match="exceeds 4 bytes"),
        ):
            await service._execute_gotenberg_request("/convert", {}, "application/pdf")


@pytest.mark.asyncio
async def test_streaming_gotenberg_response_at_limit_is_fully_yielded() -> None:
    service = GotenbergService(base_url="http://gotenberg.test")
    client = MagicMock()
    client.stream.return_value = _streaming_response([b"12", b"345"])

    with (
        patch("doc_template_service.services.gotenberg.MAX_RESPONSE_SIZE_BYTES", 5),
        patch("doc_template_service.services.gotenberg.AsyncClient") as client_class,
    ):
        client_class.return_value.__aenter__.return_value = client
        chunks = [
            chunk async for chunk in service._execute_gotenberg_streaming_request("/convert", {}, "application/pdf")
        ]

    assert chunks == [b"12", b"345"]


@pytest.mark.asyncio
async def test_streaming_gotenberg_response_over_limit_stops_before_oversized_chunk() -> None:
    service = GotenbergService(base_url="http://gotenberg.test")
    client = MagicMock()
    client.stream.return_value = _streaming_response([b"123", b"456"])

    with (
        patch("doc_template_service.services.gotenberg.MAX_RESPONSE_SIZE_BYTES", 5),
        patch("doc_template_service.services.gotenberg.AsyncClient") as client_class,
    ):
        client_class.return_value.__aenter__.return_value = client
        stream = service._execute_gotenberg_streaming_request("/convert", {}, "application/pdf")
        assert await anext(stream) == b"123"
        with pytest.raises(GotenbergError, match="exceeds 5 bytes"):
            await anext(stream)


@pytest.mark.parametrize(
    ("correlation_id", "template_id"),
    [
        pytest.param("../outside", "template", id="correlation-traversal"),
        pytest.param("correlation", "../../outside", id="template-traversal"),
    ],
)
@pytest.mark.asyncio
async def test_storage_key_traversal_is_rejected_before_upload(correlation_id: str, template_id: str) -> None:
    s3 = AsyncMock()

    with pytest.raises(ValueError, match="Invalid"):
        await store_rendered_document(
            b"rendered",
            correlation_id,
            template_id,
            "application/pdf",
            s3_client=s3,
        )

    s3.put_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversized_render_data_is_rejected_before_generation_or_upload() -> None:
    message = MagicMock()
    message.output_format = RenderOutputFormat.HTML
    message.include_text_alt = False
    message.template_content = "<html>{{ payload }}</html>"
    message.data = Struct.from_dict({"payload": "x" * (1024 * 1024)})

    generate = AsyncMock()
    store = AsyncMock()
    with (
        patch("doc_template_service.events.render_handler.generate_document", generate),
        patch("doc_template_service.events.render_handler.store_rendered_document", store),
        pytest.raises(ValidationError, match="render data exceeds"),
    ):
        await _render_and_store(AsyncMock(), message, "correlation", "template")

    generate.assert_not_awaited()
    store.assert_not_awaited()
