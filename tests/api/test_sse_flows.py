"""E2E tests for the SSE streaming endpoint via BFF.

Covers the full SSE lifecycle:
1. Endpoint authentication and connectivity
2. Content-type and heartbeat behavior
3. Document status events via SSE streaming
4. Initial dump and multi-generation scenarios

Run the full API suite through the canonical entrypoint:
    K8S_GATEWAY_URL=https://gateway.example K8S_NAMESPACE=nohiki K8S_RELEASE=nohiki just k8s-test

Gateway runtime prerequisite: a fresh Kubernetes deployment. ``K8S_GATEWAY_URL``
must name its public Gateway and resolve through system DNS or ``/etc/hosts``.

Compose remains supported for the non-Gateway SSE tests in this module. Start it
with ``just compose-up``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

if TYPE_CHECKING:
    from requests import Response
from requests.exceptions import HTTPError

from .client import NohikiClient

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-e2e-sse")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
TEST_PASSWORD = "NohikiE2E2024!"

DOCUMENT_GENERATION_TIMEOUT = 60
SSE_TIMEOUT = 60
DOCUMENT_EVENTS_PATTERN = (
    r"^/api/documents/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/events$"
)


def unique_email() -> str:
    """Generate unique email for test isolation."""
    return f"e2e-sse-{uuid.uuid4().hex[:8]}@test.nohiki.com"


def unique_name(prefix: str) -> str:
    """Generate unique name for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _kubectl_json(namespace: str, kind: str, name: str) -> dict:
    result = subprocess.run(
        ["kubectl", "-n", namespace, "get", kind, name, "-o", "json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    resource = json.loads(result.stdout)
    assert isinstance(resource, dict)
    return resource


def _require_current_condition(resource: dict, condition_type: str) -> None:
    generation = resource["metadata"]["generation"]
    matching = [
        condition
        for condition in resource.get("status", {}).get("conditions", [])
        if condition.get("type") == condition_type
    ]
    assert len(matching) == 1
    assert matching[0]["status"] == "True"
    assert matching[0]["observedGeneration"] == generation


def _normalized_gateway_url(value: str) -> str:
    parsed = urlsplit(value)
    assert parsed.scheme in {"http", "https"}
    assert parsed.hostname
    assert parsed.username is None
    assert parsed.password is None
    assert parsed.path in {"", "/"}
    assert not parsed.query
    assert not parsed.fragment
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


@contextmanager
def _owned_gateway_clients(
    gateway_url: str,
) -> Generator[tuple[NohikiClient, NohikiClient]]:
    fresh_client: NohikiClient | None = None
    authenticated_client: NohikiClient | None = None
    try:
        fresh_client = NohikiClient(gateway_url)
        fresh_client.session.trust_env = False
        authenticated_client = NohikiClient(gateway_url)
        authenticated_client.session.trust_env = False
        yield fresh_client, authenticated_client
    finally:
        if authenticated_client is not None:
            authenticated_client.session.close()
        if fresh_client is not None:
            fresh_client.session.close()


def _resolved_addresses(host: str, port: int) -> set[str]:
    return {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}


def _require_gateway_address(gateway: dict, gateway_url: str) -> None:
    parsed = urlsplit(gateway_url)
    assert parsed.scheme in {"http", "https"}
    assert parsed.hostname
    assert parsed.hostname not in {"localhost", "localhost.localdomain"}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    resolved_url = _resolved_addresses(parsed.hostname, port)
    addresses = gateway.get("status", {}).get("addresses", [])
    assert addresses, "Gateway status has no addresses"
    matches = False
    for address in addresses:
        value = address.get("value", "")
        if address.get("type") == "IPAddress":
            matches |= value in resolved_url
        elif address.get("type") == "Hostname" and value:
            matches |= (
                value == parsed.hostname
                or value in resolved_url
                or bool(resolved_url & _resolved_addresses(value, port))
            )
    assert matches, f"{parsed.hostname} does not resolve to Gateway status addresses {addresses}"


def _require_live_gateway_listener(gateway: dict, gateway_url: str) -> str:
    _require_current_condition(gateway, "Programmed")
    parsed = urlsplit(gateway_url)
    assert parsed.hostname is not None
    expected_protocol = "HTTPS" if parsed.scheme == "https" else "HTTP"
    expected_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    assert (expected_protocol, expected_port) in {("HTTPS", 443), ("HTTP", 80)}, (
        "Gateway URL must use its standard listener port, never the BFF service port"
    )
    matching_specs = [
        listener
        for listener in gateway["spec"]["listeners"]
        if listener.get("hostname") == parsed.hostname
        and listener["protocol"] == expected_protocol
        and listener["port"] == expected_port
    ]
    assert len(matching_specs) == 1
    listener_name = matching_specs[0]["name"]
    matching_statuses = [listener for listener in gateway["status"]["listeners"] if listener["name"] == listener_name]
    assert len(matching_statuses) == 1
    gateway_generation = gateway["metadata"]["generation"]
    for condition_type in ("Accepted", "Programmed"):
        conditions = [
            condition for condition in matching_statuses[0]["conditions"] if condition["type"] == condition_type
        ]
        assert len(conditions) == 1
        assert conditions[0]["status"] == "True"
        assert conditions[0]["observedGeneration"] == gateway_generation
    _require_gateway_address(gateway, gateway_url)
    return parsed.hostname


def _require_live_gateway_route(gateway_url: str) -> None:
    namespace = os.environ["K8S_NAMESPACE"]
    release = os.getenv("K8S_RELEASE", "nohiki")
    gateway_name = f"{release}-gateway"
    route_name = f"{release}-sse-route"
    backend_name = f"{release}-bff-service"
    policy_name = f"{release}-sse-response"
    gateway = _kubectl_json(namespace, "gateway.gateway.networking.k8s.io", gateway_name)
    route = _kubectl_json(namespace, "httproute.gateway.networking.k8s.io", route_name)
    response_policy = _kubectl_json(namespace, "trafficpolicy.gateway.kgateway.dev", policy_name)
    backend = _kubectl_json(namespace, "service", backend_name)
    endpoints = _kubectl_json(namespace, "endpoints", backend_name)
    deployment = _kubectl_json(namespace, "deployment.apps", backend_name)
    network_policy = _kubectl_json(namespace, "networkpolicy.networking.k8s.io", backend_name)

    hostname = _require_live_gateway_listener(gateway, gateway_url)

    expected_parent = {
        "group": "gateway.networking.k8s.io",
        "kind": "Gateway",
        "name": gateway_name,
        "namespace": namespace,
    }
    assert route["spec"]["parentRefs"] == [expected_parent]
    route_parent = next(parent for parent in route["status"]["parents"] if parent["parentRef"] == expected_parent)
    route_generation = route["metadata"]["generation"]
    for condition_type in ("Accepted", "ResolvedRefs"):
        conditions = [condition for condition in route_parent["conditions"] if condition["type"] == condition_type]
        assert len(conditions) == 1
        assert conditions[0]["status"] == "True"
        assert conditions[0]["observedGeneration"] == route_generation

    assert route["spec"]["hostnames"] == [hostname]
    rules = route["spec"]["rules"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule["name"] == "document-events"
    assert rule["matches"] == [
        {
            "method": "GET",
            "path": {"type": "RegularExpression", "value": DOCUMENT_EVENTS_PATTERN},
        }
    ]
    assert rule["timeouts"] == {"request": "0s", "backendRequest": "0s"}
    assert "filters" not in rule
    assert rule["backendRefs"] == [
        {
            "group": "",
            "kind": "Service",
            "name": backend_name,
            "port": 8000,
            "weight": 1,
        }
    ]
    assert response_policy["spec"] == {
        "buffer": {"disable": {}},
        "compression": {"responseCompression": {"disable": {}}},
        "targetRefs": [
            {
                "group": "gateway.networking.k8s.io",
                "kind": "HTTPRoute",
                "name": route_name,
                "sectionName": "document-events",
            }
        ],
    }
    assert "urlRewrite" not in response_policy["spec"]
    endpoint_labels = {
        "app.kubernetes.io/name": "bff-service",
        "app.kubernetes.io/instance": release,
    }
    assert backend["spec"]["type"] == "ClusterIP"
    assert backend["spec"]["selector"] == endpoint_labels
    ready_subsets = [subset for subset in endpoints.get("subsets", []) if subset.get("addresses")]
    assert ready_subsets, f"{backend_name} has no ready endpoint addresses"
    assert any(
        port.get("name") == "http" and port.get("port") == 8000 and port.get("protocol", "TCP") == "TCP"
        for subset in ready_subsets
        for port in subset.get("ports", [])
    ), f"{backend_name} has no ready HTTP endpoint on TCP/8000"
    assert deployment["spec"]["selector"]["matchLabels"] == endpoint_labels
    assert deployment["spec"]["template"]["metadata"]["labels"].items() >= endpoint_labels.items()
    assert network_policy["spec"]["podSelector"]["matchLabels"] == endpoint_labels
    assert {
        "from": [{"podSelector": {"matchLabels": {"gateway.networking.k8s.io/gateway-name": gateway_name}}}],
        "ports": [{"port": 8000, "protocol": "TCP"}],
    } in network_policy["spec"]["ingress"]


@pytest.mark.unit
def test_gateway_address_rejects_direct_dns_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("203.0.113.10", 443),
            )
        ],
    )
    gateway = {"status": {"addresses": [{"type": "IPAddress", "value": "198.51.100.20"}]}}
    with pytest.raises(AssertionError, match="does not resolve to Gateway status"):
        _require_gateway_address(gateway, "https://gateway.example")


@pytest.mark.unit
def test_owned_gateway_clients_disable_environment_transport() -> None:
    with _owned_gateway_clients("https://gateway.example") as (
        fresh_client,
        authenticated_client,
    ):
        assert fresh_client.session.trust_env is False
        assert authenticated_client.session.trust_env is False


@pytest.mark.unit
def test_owned_gateway_clients_close_first_when_second_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeClient:
        session = FakeSession()

    first_client = FakeClient()
    constructions = 0

    def construct(_gateway_url: str) -> FakeClient:
        nonlocal constructions
        constructions += 1
        if constructions == 1:
            return first_client
        message = "second client failed"
        raise RuntimeError(message)

    monkeypatch.setitem(globals(), "NohikiClient", construct)
    with (
        pytest.raises(RuntimeError, match="second client failed"),
        _owned_gateway_clients("https://gateway.example"),
    ):
        pytest.fail("context must not yield when the second client fails")
    assert first_client.session.trust_env is False
    assert first_client.session.closed


# Sample Templates and Data

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
    return NohikiClient(healthy_base_url)


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
    fresh_client.register(email, TEST_PASSWORD, "E2E SSE")
    return fresh_client


@pytest.fixture
def template_version(authenticated_client: NohikiClient) -> dict:
    """Create a template and return version info for document tests."""
    template_name = unique_name("sse-template")
    authenticated_client.create_template(
        name=template_name,
        display_name="SSE Test Template",
        template_content=PROFESSIONAL_TEMPLATE,
    )
    template = authenticated_client.poll_for_template(template_name, timeout=30)
    assert template is not None, "Template did not appear in projection"
    assert template["latest_version"] is not None, "Template has no version"
    return template["latest_version"]


# SSE Endpoint Basics


class TestSSEEndpointBasics:
    """Test SSE endpoint connectivity and auth."""

    def test_sse_endpoint_requires_authentication(self, fresh_client: NohikiClient) -> None:
        """Unauthenticated SSE request returns 401."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.connect_sse_raw(str(uuid.uuid4()), timeout=5)

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_endpoint_returns_event_stream_content_type(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """SSE endpoint returns Content-Type: text/event-stream."""
        request_id = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )["request_id"]
        resp = authenticated_client.connect_sse_raw(request_id, timeout=5)
        try:
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, f"Expected text/event-stream, got {content_type}"
            logger.info("SSE content-type verified: %s", content_type)
        finally:
            resp.close()

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_endpoint_streams_initial_status(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """SSE endpoint immediately streams the request's current status."""
        request_id = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )["request_id"]
        events = authenticated_client.collect_sse_events(
            request_id,
            timeout=15,
            stop_on_event_type="document_status",
        )

        status_events = [event for event in events if event.get("event") == "document_status"]
        assert status_events, f"Expected an initial document_status event, got events: {events}"
        assert request_id in status_events[0].get("data", "")

    @pytest.mark.e2e
    @pytest.mark.slow
    @pytest.mark.timeout(90)
    def test_gateway_preserves_native_sse_runtime_contract(self) -> None:
        """Prove native SSE behavior through a freshly deployed public Gateway."""
        if os.getenv("NOHIKI_TARGET") != "k8s":
            pytest.skip("gateway runtime contract applies only to Kubernetes API runs")
        gateway_url = _normalized_gateway_url(os.environ["NOHIKI_GATEWAY_URL"])
        assert _normalized_gateway_url(os.environ["E2E_BASE_URL"]) == gateway_url
        _require_live_gateway_route(gateway_url)

        streams: list[Response] = []
        with _owned_gateway_clients(gateway_url) as (
            fresh_client,
            authenticated_client,
        ):
            try:
                assert fresh_client.check_ping()
                registration = authenticated_client.register(unique_email(), TEST_PASSWORD, "Gateway SSE E2E")
                assert registration is not None

                template_name = unique_name("gateway-sse")
                authenticated_client.create_template(
                    name=template_name,
                    display_name="Gateway SSE Template",
                    template_content=PROFESSIONAL_TEMPLATE,
                )
                template = authenticated_client.poll_for_template(template_name, timeout=30)
                assert template is not None, "Gateway test template did not reach the BFF projection"
                template_version = template["latest_version"]
                assert template_version is not None
                generation = authenticated_client.generate_document(
                    template_version_id=template_version["id"],
                    data=FULL_RESUME_DATA,
                    output_format="html",
                )
                request_id = generation["request_id"]
                url = f"{gateway_url}/api/documents/{request_id}/events"
                assert urlsplit(url).query == ""
                headers = {"Accept": "text/event-stream"}

                with fresh_client.session.get(url, stream=True, timeout=(5, 5), headers=headers) as response:
                    assert response.status_code == 401

                legacy_url = f"{gateway_url}/api/v1/documents/events"
                with authenticated_client.session.get(
                    legacy_url, stream=True, timeout=(5, 5), headers=headers
                ) as response:
                    assert response.status_code == 404
                    assert not response.headers.get("Content-Type", "").startswith("text/event-stream")
                started_at = time.monotonic()
                for _ in range(3):
                    response = authenticated_client.session.get(
                        url,
                        stream=True,
                        timeout=(5, 15),
                        headers=headers,
                    )
                    streams.append(response)
                    assert response.status_code == 200

                first_stream = streams[0]
                assert "access_token=" in first_stream.request.headers.get("Cookie", "")
                assert first_stream.headers["Content-Type"].startswith("text/event-stream")
                assert first_stream.headers["Cache-Control"] == "no-store"
                assert first_stream.headers["X-Accel-Buffering"] == "no"

                with authenticated_client.session.get(
                    url,
                    stream=True,
                    timeout=(5, 5),
                    headers=headers,
                ) as response:
                    assert response.status_code == 429

                heartbeat = next(
                    line
                    for line in first_stream.iter_lines(chunk_size=1, decode_unicode=True)
                    if line is not None and line.startswith(":")
                )
                assert heartbeat.strip() == ": ping"
                assert time.monotonic() - started_at < 20, "Gateway buffered the first SSE heartbeat"
            finally:
                for stream in reversed(streams):
                    stream.close()

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_polling_endpoint_still_works(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """GET /{request_id}/status polling endpoint remains functional alongside SSE."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )
        request_id = gen_result["request_id"]

        status = authenticated_client.poll_for_document_completion(request_id, timeout=15)
        assert status["status"] == "completed"
        logger.info("Polling endpoint still functional: %s", request_id)


# SSE Document Lifecycle


class TestSSEDocumentLifecycle:
    """Test real document generation events via SSE."""

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_receives_document_status_event_on_generation(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Generate a document and verify SSE delivers the status event."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )
        request_id = gen_result["request_id"]
        events = authenticated_client.collect_sse_events(
            request_id,
            timeout=30,
            stop_on_event_type="document_status",
        )

        logger.info("Generated document %s, received %d SSE events", request_id, len(events))

        # Filter for document_status events matching our request
        status_events = [e for e in events if e.get("event") == "document_status" and request_id in e.get("data", "")]
        assert len(status_events) >= 1, (
            f"Expected at least 1 document_status event for {request_id}, got events: {events}"
        )
        logger.info("SSE delivered document_status event for %s", request_id)

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_event_contains_correct_fields(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """SSE document_status event has all required fields."""
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="html",
        )
        request_id = gen_result["request_id"]
        events = authenticated_client.collect_sse_events(
            request_id,
            timeout=30,
            stop_on_event_type="document_status",
        )

        # Find the document_status event for our request
        status_events = [e for e in events if e.get("event") == "document_status" and request_id in e.get("data", "")]
        assert len(status_events) >= 1, f"No document_status event found for {request_id}"

        # Parse the data field as JSON and verify required fields
        event_data = json.loads(status_events[0]["data"])
        assert "type" in event_data, f"Missing 'type' field in event data: {event_data}"
        assert event_data["type"] == "document_status"
        assert "request_id" in event_data, f"Missing 'request_id' field in event data: {event_data}"
        assert event_data["request_id"] == request_id
        assert "status" in event_data, f"Missing 'status' field in event data: {event_data}"
        assert event_data["status"] in ["pending", "processing", "completed", "failed"]
        logger.info(
            "SSE event fields verified for %s: status=%s",
            request_id,
            event_data["status"],
        )

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_initial_dump_includes_pending_documents(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Connecting to SSE after generating a document shows it in initial dump."""
        # Generate a document first (don't wait for completion)
        gen_result = authenticated_client.generate_document(
            template_version_id=template_version["id"],
            data=FULL_RESUME_DATA,
            output_format="pdf",
        )
        request_id = gen_result["request_id"]
        logger.info("Generated document %s, now connecting SSE for initial dump", request_id)

        # Connect SSE immediately, should include the document in initial state
        events = authenticated_client.collect_sse_events(
            request_id,
            timeout=15,
            max_events=20,
            stop_on_event_type="document_status",
        )

        # Look for any event referencing our request_id
        matching_events = [e for e in events if request_id in e.get("data", "")]
        assert len(matching_events) >= 1, f"Expected document {request_id} in SSE initial dump, got events: {events}"
        logger.info("Document %s found in SSE initial dump", request_id)


# SSE Stream Behavior


class TestSSEStreamBehavior:
    """Test SSE stream protocol behavior."""

    @pytest.mark.timeout(SSE_TIMEOUT)
    def test_sse_multiple_generations_produce_multiple_events(
        self,
        authenticated_client: NohikiClient,
        template_version: dict,
    ) -> None:
        """Each request-scoped stream reports its generated document."""
        streams: dict[str, list[dict[str, str]]] = {}
        for fmt in ("html", "pdf"):
            result = authenticated_client.generate_document(
                template_version_id=template_version["id"],
                data=FULL_RESUME_DATA,
                output_format=fmt,
            )
            request_id = result["request_id"]
            streams[request_id] = authenticated_client.collect_sse_events(
                request_id,
                timeout=30,
                stop_on_event_type="document_status",
            )

        logger.info(
            "Generated %d documents across request-scoped streams",
            len(streams),
        )

        for request_id, events in streams.items():
            matching = [
                event
                for event in events
                if event.get("event") == "document_status" and request_id in event.get("data", "")
            ]
            assert matching, f"Expected a document_status event for {request_id}, got events: {events}"

        logger.info("Both documents received SSE events")
