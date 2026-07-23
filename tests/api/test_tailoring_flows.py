"""E2E tests for the complete document tailoring pipeline via BFF.

Covers the full tailoring lifecycle:
1. Schema and template projections (read-only)
2. Template CRUD via ECST command events
3. Template content validation
4. Document generation (HTML, PDF, PNG)
5. Document status tracking and retrieval
6. Complete user journeys

Run with:
    uv run python tests/utils/health_check.py all

Prerequisites:
    just compose-up
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Generator

import pytest
from requests.exceptions import HTTPError

from .client import NohikiClient

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-e2e-tailoring")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
TEST_PASSWORD = "NohikiE2E2024!"

DOCUMENT_GENERATION_TIMEOUT = 60
PDF_RENDER_TIMEOUT = 30


def unique_email() -> str:
    """Generate unique email for test isolation."""
    return f"e2e-tailor-{uuid.uuid4().hex[:8]}@test.nohiki.com"


def unique_name(prefix: str) -> str:
    """Generate unique name for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# Sample Templates and Data

SIMPLE_TEMPLATE = """<!DOCTYPE html>
<!-- TEMPL_META {"name": "E2E Resume", "version": "1.0.0",
"description": "E2E test template", "access_scope": "PRIVATE"} -->
<html>
<head><title>{{ name }} - Resume</title></head>
<body>
<h1>{{ name }}</h1>
<p>{{ title }}</p>
{% if skills %}
<ul>
{% for skill in skills %}
<li>{{ skill }}</li>
{% endfor %}
</ul>
{% endif %}
</body>
</html>
"""

PROFESSIONAL_TEMPLATE = """<!DOCTYPE html>
<!-- TEMPL_META {"name": "Professional Resume", "version": "1.0.0",
"description": "Professional resume template", "access_scope": "PRIVATE"} -->
<html>
<head>
    <title>{{ name }} - Resume</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        h2 { color: #34495e; margin-top: 20px; }
        .contact { color: #7f8c8d; margin-bottom: 20px; }
        .section { margin-bottom: 25px; }
        ul { padding-left: 20px; }
        li { margin-bottom: 5px; }
    </style>
</head>
<body>
    <h1>{{ name }}</h1>
    <p class="contact">{{ email }} | {{ phone }}</p>

    <div class="section">
        <h2>Professional Summary</h2>
        <p>{{ summary }}</p>
    </div>

    {% if experience %}
    <div class="section">
        <h2>Experience</h2>
        {% for job in experience %}
        <div>
            <strong>{{ job.title }}</strong> at {{ job.company }}
            <br><em>{{ job.dates }}</em>
            <p>{{ job.description }}</p>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    {% if skills %}
    <div class="section">
        <h2>Skills</h2>
        <ul>
        {% for skill in skills %}
            <li>{{ skill }}</li>
        {% endfor %}
        </ul>
    </div>
    {% endif %}

    {% if education %}
    <div class="section">
        <h2>Education</h2>
        {% for edu in education %}
        <div>
            <strong>{{ edu.degree }}</strong> - {{ edu.institution }}
            <br><em>{{ edu.year }}</em>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

INVALID_TEMPLATE_MISSING_STRUCTURE = "<p>Just a paragraph {{ name }}</p>"

INVALID_TEMPLATE_UNCLOSED_EXPR = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<h1>{{ name</h1>
</body>
</html>
"""

SIMPLE_RESUME_DATA = {
    "name": "Jane Developer",
    "title": "Senior Software Engineer",
    "email": "jane.developer@example.com",
    "phone": "+1 (555) 123-4567",
    "summary": "Experienced software engineer with 10+ years building scalable distributed systems.",
    "skills": ["Python", "FastAPI", "PostgreSQL", "Kubernetes", "Kafka", "Redis"],
}

FULL_RESUME_DATA = {
    "name": "Alex Johnson",
    "email": "alex.johnson@example.com",
    "phone": "+1 (555) 987-6543",
    "summary": (
        "Results-driven Software Engineer with 8+ years of experience "
        "building scalable distributed systems. Expert in Python, Kubernetes, "
        "and event-driven architectures. Passionate about clean code and mentoring."
    ),
    "experience": [
        {
            "title": "Senior Software Engineer",
            "company": "TechCorp Inc",
            "dates": "2020 - Present",
            "description": (
                "Led development of microservices platform serving 10M+ users. "
                "Reduced deployment time by 70% through CI/CD improvements."
            ),
        },
        {
            "title": "Software Engineer",
            "company": "StartupXYZ",
            "dates": "2016 - 2020",
            "description": (
                "Built real-time data processing pipeline handling 1M events/second. "
                "Mentored junior developers and conducted code reviews."
            ),
        },
    ],
    "skills": [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Kubernetes",
        "Apache Kafka",
        "Redis",
        "Docker",
        "AWS",
        "CI/CD",
        "System Design",
    ],
    "education": [
        {
            "degree": "M.S. Computer Science",
            "institution": "Stanford University",
            "year": "2016",
        },
        {
            "degree": "B.S. Computer Science",
            "institution": "MIT",
            "year": "2014",
        },
    ],
}


@pytest.fixture(scope="module")
def client(healthy_base_url: str) -> NohikiClient:
    """Create E2E client."""
    c = NohikiClient(healthy_base_url)
    return c


@pytest.fixture
def fresh_client(healthy_base_url: str) -> Generator[NohikiClient]:
    """Create a fresh client with its own session for test isolation."""
    c = NohikiClient(healthy_base_url)
    yield c
    c.clear_session()


@pytest.fixture
def authenticated_client(fresh_client: NohikiClient) -> NohikiClient:
    """Create client with authenticated user via cookies."""
    email = unique_email()
    fresh_client.register(email, TEST_PASSWORD, "E2E Tailoring")
    return fresh_client


@pytest.fixture
def template_version(authenticated_client: NohikiClient) -> dict:
    """Create a template and return version info for document tests."""
    template_name = unique_name("fixture-template")
    authenticated_client.create_template(
        name=template_name,
        display_name="Tailoring Fixture Template",
        template_content=PROFESSIONAL_TEMPLATE,
    )
    template = authenticated_client.poll_for_template(template_name, timeout=30)
    assert template is not None, "Template did not appear in projection"
    assert template["latest_version"] is not None, "Template has no version"
    return template["latest_version"]


# Schema Projection Tests


class TestSchemaProjections:
    """Test schema read-only projection access via BFF."""

    def test_list_schema_families(self, authenticated_client: NohikiClient) -> None:
        """Test listing schema families from projection."""
        result = authenticated_client.list_schema_families()

        assert "items" in result
        assert "total" in result
        assert isinstance(result["items"], list)
        logger.info("Listed %d schema families", result["total"])

    def test_get_nonexistent_schema_family_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test getting non-existent schema family returns 404."""
        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_schema_family(str(uuid.uuid4()))

    def test_get_nonexistent_schema_version_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test getting non-existent schema version returns 404."""
        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_schema_version(str(uuid.uuid4()), 1)


# Template Projection Tests


class TestTemplateProjections:
    """Test template read-only projection access via BFF."""

    def test_list_template_families(self, authenticated_client: NohikiClient) -> None:
        """Test listing template families from projection."""
        result = authenticated_client.list_template_families()

        assert "items" in result
        assert "total" in result
        assert isinstance(result["items"], list)
        logger.info("Listed %d template families", result["total"])

    def test_get_nonexistent_template_family_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test getting non-existent template family returns 404."""
        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_template_family(str(uuid.uuid4()))

    def test_get_nonexistent_template_version_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test getting non-existent template version returns 404."""
        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_template_version("nonexistent-ns", "nonexistent-name", 1)


# Template CRUD Tests


class TestTemplateCommands:
    """Test template write operations via ECST command events."""

    def test_create_template_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test creating a template returns 202 with request_id."""
        result = authenticated_client.create_template(
            name=unique_name("e2e-template"),
            display_name="E2E Template",
            template_content=SIMPLE_TEMPLATE,
            description="E2E test template",
        )

        assert "request_id" in result
        assert result["status"] == "accepted"
        logger.info("Template create accepted: %s", result["request_id"])

    def test_create_professional_template(self, authenticated_client: NohikiClient) -> None:
        """Test creating a professional resume template with full HTML structure."""
        result = authenticated_client.create_template(
            name=unique_name("pro-resume"),
            display_name="Professional Résumé",
            template_content=PROFESSIONAL_TEMPLATE,
            description="Professional resume template",
        )

        assert "request_id" in result
        assert result["status"] == "accepted"
        logger.info("Professional template create accepted: %s", result["request_id"])

    def test_create_template_validates_content(self, authenticated_client: NohikiClient) -> None:
        """Test that invalid template content is rejected."""
        with pytest.raises(HTTPError, match=r"422"):
            authenticated_client.create_template(
                name=unique_name("invalid"),
                display_name="Invalid Template",
                template_content=INVALID_TEMPLATE_UNCLOSED_EXPR,
            )

    def test_delete_template_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test deleting a template returns 202 with request_id."""
        result = authenticated_client.delete_template(str(uuid.uuid4()))

        assert "request_id" in result
        assert result["status"] == "accepted"
        logger.info("Template delete accepted: %s", result["request_id"])


# Template Validation Tests


class TestTemplateValidation:
    """Test template content validation via BFF."""

    def test_validate_simple_template(self, authenticated_client: NohikiClient) -> None:
        """Test validating a simple Jinja2/HTML template."""
        result = authenticated_client.validate_template(SIMPLE_TEMPLATE)

        assert result["valid"] is True
        assert result["issues"] == []
        logger.info("Simple template validation passed")

    def test_validate_professional_template(self, authenticated_client: NohikiClient) -> None:
        """Test validating a professional resume template."""
        result = authenticated_client.validate_template(PROFESSIONAL_TEMPLATE)

        assert result["valid"] is True
        assert result["issues"] == []
        logger.info("Professional template validation passed")

    def test_validate_template_missing_html_structure(self, authenticated_client: NohikiClient) -> None:
        """Test validating template missing HTML structure."""
        result = authenticated_client.validate_template(INVALID_TEMPLATE_MISSING_STRUCTURE)

        assert result["valid"] is False
        assert len(result["issues"]) > 0
        keywords = [issue["keyword"] for issue in result["issues"]]
        assert any("missing" in kw for kw in keywords)
        logger.info("Missing structure correctly detected: %s", keywords)

    def test_validate_template_unclosed_expression(self, authenticated_client: NohikiClient) -> None:
        """Test validating template with unclosed Jinja2 expression."""
        result = authenticated_client.validate_template(INVALID_TEMPLATE_UNCLOSED_EXPR)

        assert result["valid"] is False
        assert len(result["issues"]) > 0
        logger.info("Unclosed expression correctly detected")


# Document Generation Tests


class TestDocumentGeneration:
    """Test document generation across all formats."""

    def test_generate_html_document(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test generating an HTML document."""
        result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )

        assert "request_id" in result
        assert result["status"] == "accepted"
        logger.info("HTML generation accepted: %s", result["request_id"])

    def test_generate_pdf_document(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test generating a PDF document."""
        result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="pdf",
        )

        assert "request_id" in result
        assert result["status"] == "accepted"
        logger.info("PDF generation accepted: %s", result["request_id"])

    def test_generate_png_document(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test generating a PNG document."""
        result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="png",
        )

        assert "request_id" in result
        assert result["status"] == "accepted"
        logger.info("PNG generation accepted: %s", result["request_id"])

    @pytest.mark.timeout(PDF_RENDER_TIMEOUT)
    def test_html_generation_completes(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test that HTML generation completes successfully."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )

        status = authenticated_client.poll_for_document_completion(gen_result["request_id"], timeout=15)

        assert status["status"] == "completed"
        logger.info("HTML generated")

    @pytest.mark.timeout(PDF_RENDER_TIMEOUT)
    def test_pdf_generation_completes(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test that PDF generation completes successfully."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="pdf",
        )

        status = authenticated_client.poll_for_document_completion(gen_result["request_id"], timeout=20)

        assert status["status"] == "completed"
        assert "download_url" in status
        assert status["download_url"].endswith(".pdf")
        logger.info("PDF generated: %s", status["download_url"])


# Document Status Tracking Tests


class TestDocumentStatusTracking:
    """Test document generation status tracking."""

    def test_get_document_status_immediately(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test getting document status immediately after request."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=SIMPLE_RESUME_DATA,
            output_format="html",
        )

        status = authenticated_client.get_document_status(gen_result["request_id"])

        assert "request_id" in status
        assert "status" in status
        assert status["status"] in ["pending", "processing", "completed", "failed"]
        logger.info("Immediate status: %s", status["status"])

    def test_document_appears_in_list(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test that generated document appears in list."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=SIMPLE_RESUME_DATA,
            output_format="html",
        )

        docs = authenticated_client.list_documents()

        doc_ids = [d["request_id"] for d in docs["items"]]
        assert gen_result["request_id"] in doc_ids
        logger.info("Document found in list")

    def test_list_documents(self, authenticated_client: NohikiClient) -> None:
        """Test listing document generation requests."""
        result = authenticated_client.list_documents()

        assert "items" in result
        assert "total" in result
        assert isinstance(result["items"], list)
        logger.info("Listed %d documents", result["total"])


# Complete User Journey Tests


class TestCompleteTailoringJourneys:
    """Test complete tailoring user journeys."""

    @pytest.mark.timeout(DOCUMENT_GENERATION_TIMEOUT)
    def test_template_creation_and_validation_flow(self, authenticated_client: NohikiClient) -> None:
        """Test complete template creation flow.

        1. Validate template content first
        2. Create template via ECST command
        3. Verify request_id returned
        """
        validation = authenticated_client.validate_template(PROFESSIONAL_TEMPLATE)
        assert validation["valid"] is True
        logger.info("Template validated")

        create_result = authenticated_client.create_template(
            name=unique_name("journey-template"),
            display_name="Journey Template",
            template_content=PROFESSIONAL_TEMPLATE,
            description="Complete journey test template",
            schema_compatibility=["resume-v1"],
        )

        assert "request_id" in create_result
        assert create_result["status"] == "accepted"
        logger.info("Template create command accepted: %s", create_result["request_id"])

    @pytest.mark.timeout(DOCUMENT_GENERATION_TIMEOUT)
    def test_document_generation_flow(self, authenticated_client: NohikiClient) -> None:
        """Test document generation flow with status polling.

        1. Create template
        2. Wait for template projection
        3. Generate document
        4. Poll for completion
        5. Verify document in list
        """
        template_name = unique_name("docflow")
        authenticated_client.create_template(
            name=template_name,
            display_name="Document Flow Template",
            template_content=PROFESSIONAL_TEMPLATE,
        )

        template = authenticated_client.poll_for_template(template_name, timeout=30)
        assert template is not None
        version_id = template["latest_version"]["id"]

        gen_result = authenticated_client.generate_document(
            template_version_id=version_id,
            data=FULL_RESUME_DATA,
            output_format="pdf",
        )
        request_id = gen_result["request_id"]
        logger.info("Document generation started: %s", request_id)

        status = authenticated_client.poll_for_document_completion(request_id, timeout=25)
        assert status["status"] == "completed"

        docs = authenticated_client.list_documents()
        doc_ids = [d["request_id"] for d in docs["items"]]
        assert request_id in doc_ids
        logger.info("Document flow completed")

    @pytest.mark.timeout(DOCUMENT_GENERATION_TIMEOUT)
    def test_full_tailoring_studio_workflow(self, fresh_client: NohikiClient) -> None:
        """Test complete Tailoring Studio workflow as a user would experience it.

        1. Register new user
        2. Browse existing templates
        3. Validate custom template
        4. Create custom template
        5. Generate PDF document
        6. Verify document storage
        """
        email = unique_email()
        reg = fresh_client.register(email, TEST_PASSWORD, "Studio User")
        assert reg is not None
        logger.info("User registered: %s", reg["id"])

        templates = fresh_client.list_template_families()
        logger.info("Found %d existing templates", templates["total"])

        validation = fresh_client.validate_template(PROFESSIONAL_TEMPLATE)
        assert validation["valid"] is True

        template_name = unique_name("studio-resume")
        create_result = fresh_client.create_template(
            name=template_name,
            display_name="My Professional Résumé",
            template_content=PROFESSIONAL_TEMPLATE,
            description="My professional resume",
        )
        assert create_result["status"] == "accepted"
        logger.info("Template creation requested: %s", create_result["request_id"])

        template = fresh_client.poll_for_template(template_name, timeout=30)
        assert template is not None, "Template did not appear in projection"
        version_id = template["latest_version"]["id"]
        logger.info("Template ready: %s", version_id)

        gen_result = fresh_client.generate_document(
            template_version_id=version_id,
            data=FULL_RESUME_DATA,
            output_format="pdf",
        )
        request_id = gen_result["request_id"]
        logger.info("PDF generation started: %s", request_id)

        status = fresh_client.poll_for_document_completion(request_id, timeout=25)
        assert status["status"] == "completed"
        assert "download_url" in status
        logger.info("PDF completed, stored at: %s", status["download_url"])

        docs = fresh_client.list_documents()
        doc_ids = [d["request_id"] for d in docs["items"]]
        assert request_id in doc_ids
        logger.info("Full Tailoring Studio workflow completed")

    @pytest.mark.timeout(DOCUMENT_GENERATION_TIMEOUT)
    def test_multiple_format_generation(self, authenticated_client: NohikiClient) -> None:
        """Test generating same document in multiple formats."""
        template_name = unique_name("multi-format")
        authenticated_client.create_template(
            name=template_name,
            display_name="Multi-Format Template",
            template_content=PROFESSIONAL_TEMPLATE,
        )

        template = authenticated_client.poll_for_template(template_name, timeout=30)
        assert template is not None
        version_id = template["latest_version"]["id"]

        formats = ["html", "pdf", "png"]
        request_ids = []

        for fmt in formats:
            result = authenticated_client.generate_document(
                template_version_id=version_id,
                data=FULL_RESUME_DATA,
                output_format=fmt,
            )
            request_ids.append(result["request_id"])
            logger.info("Generated %s: %s", fmt, result["request_id"])

        for request_id in request_ids:
            status = authenticated_client.poll_for_document_completion(request_id, timeout=20)
            assert status["status"] == "completed"

        logger.info("All formats generated")


# Error Handling Tests


class TestTailoringErrorHandling:
    """Test error handling for tailoring endpoints."""

    def test_unauthenticated_schema_access_fails(self, fresh_client: NohikiClient) -> None:
        """Test accessing schema endpoints without auth fails."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.list_schema_families()

    def test_unauthenticated_template_access_fails(self, fresh_client: NohikiClient) -> None:
        """Test accessing template endpoints without auth fails."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.list_template_families()

    def test_unauthenticated_document_generation_fails(self, fresh_client: NohikiClient) -> None:
        """Test document generation without auth fails."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.generate_document(
                template_version_id=str(uuid.uuid4()),
                data={"test": "data"},
            )

    def test_nonexistent_template_fails(self, authenticated_client: NohikiClient) -> None:
        """Test generating from nonexistent template version fails."""
        with pytest.raises(HTTPError, match=r"404|422"):
            authenticated_client.generate_document(
                template_version_id=str(uuid.uuid4()),
                data=SIMPLE_RESUME_DATA,
            )

    def test_invalid_output_format_fails(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Test generating with invalid output format fails."""
        with pytest.raises(HTTPError, match=r"422"):
            authenticated_client.generate_document(
                template_version_id=template_version["id"],
                data=SIMPLE_RESUME_DATA,
                output_format="invalid_format",
            )
