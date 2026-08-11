"""Mechanical declared-vs-written coverage for ECST snapshot builders.

A snapshot builder that never assigns a field its snapshot type declares
publishes the betterproto default and silently disables the capability behind
the field. This gate fails on any such omission unless an explicit per-field
exemption names the activation condition that will make the write possible.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class BuilderSpec:
    """One ECST snapshot builder under examination."""

    relative_path: str
    function_name: str
    snapshot_type_import: str  # "module:ClassName"
    line_hint: int


@dataclass(frozen=True, slots=True)
class FieldExemption:
    """Deliberate omission: only valid with a named activation condition."""

    field_name: str
    activation_condition: str


# Population census (11 sites). Keep in sync when adding builders.
_BUILDERS: tuple[BuilderSpec, ...] = (
    BuilderSpec(
        "backend/services/user-pref-service/src/user_pref_service/services/profile_service.py",
        "build_profile_snapshot",
        "nohiki.user.pref.v1:SearchPrefSnapshot",
        121,
    ),
    BuilderSpec(
        "backend/services/job-storage-service/src/job_storage_service/events/publishers.py",
        "build_listing_snapshot",
        "nohiki.job.listing.v1:ListingSnapshot",
        123,
    ),
    BuilderSpec(
        "backend/services/doc-template-service/src/doc_template_service/events/publishers.py",
        "build_template_snapshot",
        "nohiki.doc.template.v1:DocumentTemplateSnapshot",
        40,
    ),
    BuilderSpec(
        "backend/services/skill-graph-service/src/skill_graph_service/events/publishers.py",
        "build_canonical_skill_snapshot",
        "nohiki.skill.v1:CanonicalSkill",
        149,
    ),
    BuilderSpec(
        "backend/services/user-pref-service/src/user_pref_service/services/settings_service.py",
        "build_settings_snapshot",
        "nohiki.user.pref.v1:UserPrefSettings",
        26,
    ),
    BuilderSpec(
        "backend/services/doc-process-service/src/doc_process_service/providers/docling/client.py",
        "_parse_result",
        "nohiki.doc.process.v1:ProcessedDocumentSnapshot",
        316,
    ),
    BuilderSpec(
        "backend/services/job-correlation-evaluation-service/src/job_correlation_evaluation_service/events/publishers.py",
        "_build_listing_notification_snapshot",
        "nohiki.job.listing.v1:ListingNotificationSnapshot",
        66,
    ),
    BuilderSpec(
        "backend/services/user-entitlement-service/src/user_entitlement_service/events/publishers.py",
        "_build_entitlement_snapshot",
        "nohiki.common.v1:EntitlementSnapshot",
        19,
    ),
    BuilderSpec(
        "backend/services/user-upload-service/src/user_upload_service/events/publishers.py",
        "_build_upload_snapshot",
        "nohiki.user.upload.v1:UploadSnapshot",
        41,
    ),
)

# Explicit exemptions: each must name the wiring that unlocks the write.
_EXEMPTIONS: dict[tuple[str, str], frozenset[FieldExemption]] = {
    (
        "backend/services/user-pref-service/src/user_pref_service/services/profile_service.py",
        "build_profile_snapshot",
    ): frozenset(
        {
            FieldExemption(
                "scrape_sources",
                "entitlement ECST projection lands in user-pref so allowed_sources "
                "is available to compute scrape_sources = allowed - excluded",
            ),
        }
    ),
    (
        "backend/services/skill-graph-service/src/skill_graph_service/events/publishers.py",
        "build_canonical_skill_snapshot",
    ): frozenset(
        {
            FieldExemption(
                "tabiya_concept_id",
                "SkillNode gains tabiya concept columns or provenance.external_id "
                "is mapped into the builder for TABIYA-sourced skills",
            ),
            FieldExemption(
                "tabiya_version",
                "SkillNode gains tabiya version columns or provenance.source_version "
                "is mapped into the builder for TABIYA-sourced skills",
            ),
            FieldExemption(
                "esco_uri",
                "SkillNode gains esco URI columns or provenance.external_uri "
                "is mapped into the builder for ESCO-sourced skills",
            ),
            FieldExemption(
                "isco_group",
                "SkillNode gains isco group columns or occupation relation isco_group_code is mapped into the builder",
            ),
        }
    ),
    (
        "backend/services/doc-process-service/src/doc_process_service/providers/docling/client.py",
        "_parse_result",
    ): frozenset(
        {
            FieldExemption(
                "processed_storage_key",
                "DoclingClient._parse_result receives the persisted processed object "
                "storage key from the caller that wrote the blob",
            ),
        }
    ),
}


def _load_snapshot_type(spec: BuilderSpec) -> type[Any]:
    module_name, class_name = spec.snapshot_type_import.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def _declared_fields(snapshot_type: type[Any]) -> frozenset[str]:
    """Betterproto2 message fields from annotations (excludes ClassVar noise)."""
    annotations = getattr(snapshot_type, "__annotations__", {})
    return frozenset(name for name in annotations if not name.startswith("_"))


def _function_def(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    msg = f"function {name!r} not found"
    raise AssertionError(msg)


def _direct_writes(func: ast.AST) -> set[str]:
    """Fields assigned via constructor kwargs, attr writes, or repeated.extend."""
    written: set[str] = set()

    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg is not None:
                    written.add(keyword.arg)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    written.add(target.attr)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
            written.add(node.target.attr)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"extend", "append", "update"}
            and isinstance(node.func.value, ast.Attribute)
        ):
            written.add(node.func.value.attr)

    return written


def _module_functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    if not isinstance(tree, ast.Module):
        msg = f"expected ast.Module, got {type(tree).__name__}"
        raise TypeError(msg)
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _helper_writes_on_snapshot_arg(
    builder: ast.FunctionDef | ast.AsyncFunctionDef,
    module_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> set[str]:
    """Follow same-module helpers that receive the snapshot and mutate it.

    Matches the census rule that counted ``_set_snapshot_timestamps(snapshot, job)``.
    """
    written: set[str] = set()
    for node in ast.walk(builder):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        helper = module_funcs.get(node.func.id)
        if helper is None or not helper.args.args:
            continue
        snapshot_param = helper.args.args[0].arg
        for sub in ast.walk(helper):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == snapshot_param
                    ):
                        written.add(target.attr)
            if (
                isinstance(sub, ast.AugAssign)
                and isinstance(sub.target, ast.Attribute)
                and isinstance(sub.target.value, ast.Name)
                and sub.target.value.id == snapshot_param
            ):
                written.add(sub.target.attr)
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in {"extend", "append", "update"}
                and isinstance(sub.func.value, ast.Attribute)
                and isinstance(sub.func.value.value, ast.Name)
                and sub.func.value.value.id == snapshot_param
            ):
                written.add(sub.func.value.attr)
    return written


def _written_fields(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.AST,
) -> frozenset[str]:
    module_funcs = _module_functions(tree)
    return frozenset(_direct_writes(func) | _helper_writes_on_snapshot_arg(func, module_funcs))


def _omissions_for(spec: BuilderSpec, source: str | None = None) -> frozenset[str]:
    path = _ROOT / spec.relative_path
    text = source if source is not None else path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    if not isinstance(tree, ast.Module):
        # Fail the gate — never skip a builder whose source did not parse as a module.
        msg = f"{spec.relative_path}: expected ast.Module from ast.parse, got {type(tree).__name__}"
        raise TypeError(msg)
    func = _function_def(tree, spec.function_name)
    declared = _declared_fields(_load_snapshot_type(spec))
    written = _written_fields(func, tree)
    return declared - written


def _exempted_fields(spec: BuilderSpec) -> frozenset[str]:
    exemptions = _EXEMPTIONS.get((spec.relative_path, spec.function_name), frozenset())
    for exemption in exemptions:
        assert exemption.activation_condition.strip(), (
            f"exemption for {spec.function_name}.{exemption.field_name} lacks activation condition"
        )
    return frozenset(e.field_name for e in exemptions)


def test_census_covers_known_builder_population() -> None:
    """Guard against silently shrinking the examined population."""
    assert len(_BUILDERS) >= 9, f"census regressed: only {len(_BUILDERS)} builders registered"
    names = {b.function_name for b in _BUILDERS}
    assert "build_profile_snapshot" in names
    assert "build_listing_snapshot" in names


def test_every_builder_writes_all_non_exempt_declared_fields() -> None:
    """Fail when any builder omits a declared field without an exemption."""
    failures: list[str] = []
    for spec in _BUILDERS:
        omissions = _omissions_for(spec)
        unexpected = omissions - _exempted_fields(spec)
        if unexpected:
            failures.append(
                f"{spec.relative_path}:{spec.function_name} omits {sorted(unexpected)} "
                f"(all omissions={sorted(omissions)})"
            )
    assert not failures, "Snapshot builders omit declared fields:\n" + "\n".join(failures)


def test_exemptions_are_subset_of_actual_omissions() -> None:
    """Dead exemptions must not accumulate the way deptry ignores did."""
    failures: list[str] = []
    for spec in _BUILDERS:
        omissions = _omissions_for(spec)
        exempted = _exempted_fields(spec)
        stale = exempted - omissions
        if stale:
            failures.append(
                f"{spec.function_name}: exemption for {sorted(stale)} but field is now written; remove the exemption"
            )
    assert not failures, "Stale exemptions:\n" + "\n".join(failures)


def test_gate_detects_known_omission_shape_on_synthetic_builder() -> None:
    """Reproduce the D1/D3 shape: declared field absent from constructor kwargs."""
    synthetic = """
from dataclasses import dataclass

@dataclass
class FakeSnapshot:
    id: str
    notification_config: object | None
    feature_importance: object | None
    scrape_sources: list

def build_fake_snapshot(profile):
    return FakeSnapshot(
        id=str(profile.id),
        # notification_config omitted — D1 shape
        # feature_importance omitted — D3 shape
        scrape_sources=[],
    )
"""
    tree = ast.parse(synthetic)
    func = _function_def(tree, "build_fake_snapshot")
    written = _written_fields(func, tree)
    declared = frozenset({"id", "notification_config", "feature_importance", "scrape_sources"})
    omissions = declared - written
    assert omissions == frozenset({"notification_config", "feature_importance"}), omissions


def test_gate_detects_listing_omission_shape_on_synthetic_builder() -> None:
    """Reproduce the D2/D6 shape: post-construction fields never assigned in builder."""
    synthetic = """
def build_fake_listing(job):
    snapshot = FakeListing(
        id=str(job.id),
        title=job.title,
    )
    snapshot.required_skills.extend(job.required_skills or [])
    # skill_requirements omitted — D2 shape
    # retrieval_embeddings omitted — D6 shape
    return snapshot
"""
    tree = ast.parse(synthetic)
    func = _function_def(tree, "build_fake_listing")
    written = _written_fields(func, tree)
    declared = frozenset({"id", "title", "required_skills", "skill_requirements", "retrieval_embeddings"})
    omissions = declared - written
    assert omissions == frozenset({"skill_requirements", "retrieval_embeddings"}), omissions


@pytest.mark.parametrize(
    "field_name",
    [
        "notification_config",
        "feature_importance",
        "skill_requirements",
        "retrieval_embeddings",
    ],
)
def test_known_register_fields_are_either_written_or_explicitly_exempt(field_name: str) -> None:
    """D1/D2/D3/D6 must not silently reappear; D7 stays only via named exemption."""
    profile = next(b for b in _BUILDERS if b.function_name == "build_profile_snapshot")
    listing = next(b for b in _BUILDERS if b.function_name == "build_listing_snapshot")

    if field_name in {"notification_config", "feature_importance"}:
        omissions = _omissions_for(profile)
        assert field_name not in omissions, f"{field_name} regressed to an unwritten omission"
    else:
        omissions = _omissions_for(listing)
        assert field_name not in omissions, f"{field_name} regressed to an unwritten omission"


def test_d7_scrape_sources_remains_exempt_until_entitlement_wiring() -> None:
    """D7 stays unpublished; exemption must remain until activation condition lands."""
    profile = next(b for b in _BUILDERS if b.function_name == "build_profile_snapshot")
    omissions = _omissions_for(profile)
    assert "scrape_sources" in omissions
    assert "scrape_sources" in _exempted_fields(profile)


def test_non_module_ast_fails_the_gate() -> None:
    """A source-parsing checker must fail closed on non-Module trees, never skip."""
    expression = ast.parse("1 + 1", mode="eval")
    assert not isinstance(expression, ast.Module)
    with pytest.raises(TypeError, match=r"expected ast\.Module"):
        _module_functions(expression)


def test_module_functions_accepts_module() -> None:
    """Happy path: Module trees expose top-level function defs."""
    module = ast.parse("def build_x():\n    return 1\n")
    funcs = _module_functions(module)
    assert set(funcs) == {"build_x"}
