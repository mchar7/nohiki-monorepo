"""Privacy and drift contracts for document qualification fixtures."""

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import pytest

import llm_benchmark.document_fixtures as fixture_module
from llm_benchmark.document_fixtures import (
    DOCUMENT_FIXTURES,
    DocumentKind,
    DocumentQualificationFixture,
    FactualAtom,
    build_prompt_boundary_control,
    compute_document_fixture_checksum,
    get_document_fixture,
)

_EXPECTED_IDS = (
    "unicode_complete_resume",
    "complete_cover_letter",
    "sparse_evidence_resume",
    "adversarial_cover_letter",
)
_EXPECTED_TAGS = {
    "resume",
    "cover_letter",
    "complete",
    "unicode",
    "sparse_evidence",
    "job_only_skill_canary",
    "job_only_numeric_canary",
    "adversarial",
    "job_injection",
    "attachment_injection",
    "preferences_injection",
    "conflicting_identity",
    "conflicting_contact",
}
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+)\b")
_URL = re.compile(r"https?://[^\s\"'<>]+")
_PHONE = re.compile(r"\+1\s+\d{3}-\d{3}-\d{4}")
_SECRET = re.compile(
    r"(?i)(?:sk|pk|rk|api)[-_][A-Za-z0-9]{16,}|"
    r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}"
)


def _fixture_text() -> str:
    chunks: list[str] = []
    for fixture in DOCUMENT_FIXTURES:
        chunks.extend((fixture.job_data_json, fixture.user_preferences_json))
        chunks.extend(content for _, content in fixture.attachments)
        for fact in (
            *fixture.ledger.locked_paths,
            *fixture.ledger.required_atoms,
            *fixture.ledger.allowed_atoms,
            *fixture.ledger.forbidden_atoms,
        ):
            chunks.extend((fact.value, fact.source))
        chunks.extend(fixture.ledger.rendered_literals)
    return "\n".join(chunks)


def test_paid_fixture_ids_and_case_count_are_stable() -> None:
    assert tuple(fixture.fixture_id for fixture in DOCUMENT_FIXTURES) == _EXPECTED_IDS
    assert len(DOCUMENT_FIXTURES) == 4
    assert tuple(get_document_fixture(identifier).fixture_id for identifier in _EXPECTED_IDS) == _EXPECTED_IDS
    with pytest.raises(KeyError, match="Unknown document fixture"):
        get_document_fixture("not-a-paid-case")


def test_paid_corpus_covers_both_document_kinds_and_all_branch_tags() -> None:
    assert {fixture.document_kind for fixture in DOCUMENT_FIXTURES} == set(DocumentKind)
    assert {kind: sum(f.document_kind is kind for f in DOCUMENT_FIXTURES) for kind in DocumentKind} == {
        DocumentKind.RESUME: 2,
        DocumentKind.COVER_LETTER: 2,
    }
    actual_tags = set().union(*(fixture.branch_tags for fixture in DOCUMENT_FIXTURES))
    assert actual_tags == _EXPECTED_TAGS


def test_all_factual_atoms_are_declared_and_source_annotated() -> None:
    for fixture in DOCUMENT_FIXTURES:
        ledger = fixture.ledger
        assert ledger.locked_paths
        assert ledger.required_atoms
        assert ledger.allowed_atoms
        assert ledger.rendered_literals
        allowed = {atom.value for atom in ledger.allowed_atoms}
        assert {fact.value for fact in ledger.locked_paths} <= allowed
        assert {atom.value for atom in ledger.required_atoms} <= allowed
        for fact in (
            *ledger.locked_paths,
            *ledger.required_atoms,
            *ledger.allowed_atoms,
            *ledger.forbidden_atoms,
        ):
            assert fact.value.strip(), fixture.fixture_id
            assert fact.source.strip(), (fixture.fixture_id, fact.value)
        assert len({fact.path for fact in ledger.locked_paths}) == len(ledger.locked_paths)


def test_every_contact_uses_reserved_domains_and_555_test_numbers() -> None:
    text = _fixture_text()
    emails = _EMAIL.findall(text)
    urls = _URL.findall(text)
    phones = _PHONE.findall(text)
    assert emails
    assert urls
    assert phones
    assert all(domain.casefold().endswith(".invalid") for domain in emails)
    assert all((urlparse(url.rstrip(".,)")).hostname or "").casefold().endswith(".invalid") for url in urls)
    assert all(re.fullmatch(r"\+1 202-555-01\d{2}", phone) for phone in phones)


def test_fixture_corpus_contains_no_real_looking_secrets() -> None:
    assert _SECRET.search(_fixture_text()) is None


def test_checksums_are_deterministic_unique_sha256_values() -> None:
    first = {fixture.fixture_id: compute_document_fixture_checksum(fixture) for fixture in DOCUMENT_FIXTURES}
    second = {identifier: compute_document_fixture_checksum(identifier) for identifier in _EXPECTED_IDS}
    assert first == second
    assert len(set(first.values())) == len(DOCUMENT_FIXTURES)
    assert all(re.fullmatch(r"[0-9a-f]{64}", checksum) for checksum in first.values())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fixture: replace(fixture, job_data_json=fixture.job_data_json + " "),
        lambda fixture: replace(fixture, attachments=(*fixture.attachments, ("extra.txt", "synthetic"))),
        lambda fixture: replace(fixture, user_preferences_json=fixture.user_preferences_json + " "),
        lambda fixture: replace(fixture, schema_name=fixture.schema_name + "Changed"),
        lambda fixture: replace(fixture, schema_version="9.9.9"),
        lambda fixture: replace(
            fixture,
            fact_ledger=replace(
                fixture.fact_ledger,
                locked_paths=(
                    replace(fixture.fact_ledger.locked_paths[0], source="changed-source"),
                    *fixture.fact_ledger.locked_paths[1:],
                ),
            ),
        ),
        lambda fixture: replace(
            fixture,
            fact_ledger=replace(
                fixture.fact_ledger,
                required_atoms=(
                    *fixture.fact_ledger.required_atoms,
                    FactualAtom("extra", "synthetic"),
                ),
            ),
        ),
        lambda fixture: replace(
            fixture,
            fact_ledger=replace(
                fixture.fact_ledger,
                allowed_atoms=(
                    *fixture.fact_ledger.allowed_atoms,
                    FactualAtom("extra", "synthetic"),
                ),
            ),
        ),
        lambda fixture: replace(
            fixture,
            fact_ledger=replace(
                fixture.fact_ledger,
                forbidden_atoms=(
                    *fixture.fact_ledger.forbidden_atoms,
                    FactualAtom("extra", "synthetic"),
                ),
            ),
        ),
        lambda fixture: replace(
            fixture,
            fact_ledger=replace(
                fixture.fact_ledger,
                rendered_literals=(*fixture.fact_ledger.rendered_literals, "extra"),
            ),
        ),
        lambda fixture: replace(fixture, branch_tags=fixture.branch_tags | {"changed-contract"}),
    ],
    ids=(
        "job-data",
        "attachments",
        "preferences",
        "schema-name",
        "schema-version",
        "locked-facts",
        "required-atoms",
        "allowed-atoms",
        "forbidden-atoms",
        "rendered-literals",
        "branch-tags",
    ),
)
def test_checksum_drifts_for_every_in_memory_contract_input(
    mutate: Callable[[DocumentQualificationFixture], DocumentQualificationFixture],
) -> None:
    fixture = get_document_fixture("adversarial_cover_letter")
    changed = mutate(fixture)
    assert compute_document_fixture_checksum(changed) != compute_document_fixture_checksum(fixture)


@pytest.mark.parametrize("contract_field", ["schema_identifier", "template_identifier", "lint_identifier"])
def test_checksum_drifts_when_any_shipped_contract_byte_changes(contract_field: str, tmp_path: Path) -> None:
    fixture = get_document_fixture("unicode_complete_resume")
    selected_identifier = getattr(fixture, contract_field)
    original_contract_path = fixture_module._contract_path
    changed = tmp_path / Path(selected_identifier).name
    changed.write_bytes(original_contract_path(selected_identifier).read_bytes() + b"\n ")

    def contract_path(identifier: str) -> Path:
        return changed if identifier == selected_identifier else original_contract_path(identifier)

    baseline = compute_document_fixture_checksum(fixture)
    with patch.object(fixture_module, "_contract_path", side_effect=contract_path):
        assert compute_document_fixture_checksum(fixture) != baseline


@pytest.mark.parametrize("prompt_builder", ["build_system_prompt", "build_user_prompt"])
def test_checksum_drifts_when_production_prompt_changes(prompt_builder: str) -> None:
    fixture = get_document_fixture("complete_cover_letter")
    original = getattr(fixture_module, prompt_builder)
    baseline = compute_document_fixture_checksum(fixture)
    with patch.object(
        fixture_module,
        prompt_builder,
        side_effect=lambda context: original(context) + " drift",
    ):
        assert compute_document_fixture_checksum(fixture) != baseline


def test_prompt_boundary_control_is_offline_and_dispatches_only_under_limit() -> None:
    limit = 50_000
    control = build_prompt_boundary_control(limit)
    assert control.under_limit_characters == limit - 1
    assert control.over_limit_characters == limit + 1
    assert len(control.under_limit_prompt) == control.under_limit_characters
    assert len(control.over_limit_prompt) == control.over_limit_characters
    assert control.would_dispatch_under is True
    assert control.would_dispatch_over is False
