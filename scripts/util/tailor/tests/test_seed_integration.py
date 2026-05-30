"""End-to-end integration tests for the seed lint configs.

Exercises the full lint pipeline (YAML load → meta strip → runtime build →
engine.evaluate) against the two authoritative seed configs shipped with
``doc-template-service``. Each test either asserts a clean run or asserts
that a known class of bad content produces a specific rule's issue.

Fixtures live inline (plain dicts / JSON-on-disk for sibling documents) so
the tests are readable and stay next to the assertions they support.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tailor.lint import LintConfig, LintEngine, extract_tailor_meta, load_lint_config
from tailor.lint.meta import build_runtime

if TYPE_CHECKING:
    from tailor.lint import LintIssue, LintRuntimeContext

# Seed config loading

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SEED_DIR = _REPO_ROOT / "backend" / "services" / "doc-template-service" / "seed_templates"
_RESUME_SEED_HTML = _SEED_DIR / "default_resume_template.html"
_CL_SEED_HTML = _SEED_DIR / "default_cover_letter_template.html"


def _load_seed(name: str) -> LintConfig:
    html_path = _SEED_DIR / f"{name}.html"
    cfg = load_lint_config(html_path)
    assert cfg is not None, f"expected lint config for {name}"
    return cfg


@pytest.fixture(scope="module")
def resume_cfg() -> LintConfig:
    return _load_seed("default_resume_template")


@pytest.fixture(scope="module")
def cl_cfg() -> LintConfig:
    return _load_seed("default_cover_letter_template")


# Sample-data factories (kept inline for test-local readability)


def _canonical_resume() -> dict[str, Any]:
    """Resume content that should pass the seed lint cleanly (or near-cleanly)."""
    return {
        "skills": {
            "categories": [
                {"name": "Backend", "skills": ["Python", "Postgres", "Kafka"]},
                {"name": "Frontend", "skills": ["TypeScript", "React"]},
            ]
        },
        "experience": {
            "entries": [
                {
                    "bullets": [
                        "Shipped a billing pipeline handling 50k transactions per day.",
                        "Reduced p99 latency from 800ms to 120ms on the search path.",
                        "Led migration of the auth stack to OIDC across 3 services.",
                    ]
                },
                {
                    "bullets": [
                        "Wrote the data-access layer powering the customer dashboard.",
                        "Owned the release process for the mobile API from day one.",
                    ]
                },
            ]
        },
        "projects": {
            "entries": [
                {
                    "bullets": [
                        "Built a static-site generator used by a handful of side-projects.",
                        "Prototyped an OCR pipeline for scanned receipts over a weekend.",
                    ]
                }
            ]
        },
        "education": {
            "entries": [
                {"school": "Example University", "degree": "BS Computer Science"},
            ]
        },
    }


def _canonical_cover_letter() -> dict[str, Any]:
    """Cover letter content that should satisfy the seed lint without _tailor_meta gates."""
    return {
        "salutation": "Dear Hiring Manager,",
        "body_paragraphs": [
            (
                "Your posting for the Staff role caught my attention because "
                "the problem statement mirrors the backend migration I wrapped "
                "last summer. I've spent the last two years reshaping pipelines "
                "like the one described, and I'd welcome the chance to bring that "
                "experience into your environment without the usual ramp-up cost."
            ),
            (
                "At my current role I shepherded a billing pipeline through three "
                "major refactors. We moved from a single-writer Postgres setup to "
                "a Kafka-backed projection model, and I owned the data-integrity "
                "story end to end. Throughput tripled; customer-visible defects "
                "dropped by more than half; on-call pages stopped waking me up."
            ),
            (
                "I'm drawn to how your team talks about ownership. In my last two "
                "quarters I've been deliberately reaching for larger scopes of "
                "responsibility, and I'd rather work somewhere that treats that "
                "instinct as fuel than somewhere that treats it as noise. I can "
                "bring the same steadiness to whatever domain you point me at."
            ),
            (
                "I'd love to trade notes on how the team thinks about platform "
                "evolution. Thanks for the thoughtful write-up; it's the kind of "
                "posting that made me want to answer even on a Saturday."
            ),
        ],
    }


# Helpers


def _run_lint(cfg: LintConfig, data: dict[str, Any], *, runtime: LintRuntimeContext | None = None) -> list[LintIssue]:
    engine = LintEngine()
    result = engine.evaluate(data, cfg, runtime=runtime)
    return list(result.issues)


def _issues_by_rule(issues: list[LintIssue], rule_id: str) -> list[LintIssue]:
    return [i for i in issues if i.rule == rule_id]


# Seed config shape


class TestSeedConfigShape:
    """Sanity checks on the seed YAMLs so regressions are caught early."""

    def test_both_seed_htmls_present(self) -> None:
        assert _RESUME_SEED_HTML.exists(), f"expected {_RESUME_SEED_HTML}"
        assert _CL_SEED_HTML.exists(), f"expected {_CL_SEED_HTML}"

    def test_resume_has_all_families(self, resume_cfg: LintConfig) -> None:
        types = {r.type for r in resume_cfg.rules}
        # Foundational rule families
        assert "min_items" in types
        assert "max_items" in types
        assert "unique_opening_words" in types
        assert "verb_tense" in types
        assert "banned_openers" in types
        assert "banned_patterns" in types
        assert "banned_child_names" in types
        assert "first_item_capitalization" in types
        assert "max_child_items" in types
        assert "required_sections" in types
        assert "section_order" in types

    def test_cl_uses_all_phase_c_rule_types(self, cl_cfg: LintConfig) -> None:
        types = {r.type for r in cl_cfg.rules}
        # Rule types used in cover letter validation
        assert "max_structural_punctuation_per_sentence" in types
        assert "max_consecutive_opener" in types
        assert "rhythm_check" in types
        assert "ratio" in types
        assert "mention_count" in types
        assert "repeated_literal_across_paths" in types
        assert "repeated_phrase_across_paths" in types
        assert "orphan_final_word_heuristic" in types
        assert "banned_patterns" in types

    def test_resume_rules_all_have_severity(self, resume_cfg: LintConfig) -> None:
        for rule in resume_cfg.rules:
            assert rule.severity in {"error", "warning", "info"}

    def test_cl_rules_all_have_severity(self, cl_cfg: LintConfig) -> None:
        for rule in cl_cfg.rules:
            assert rule.severity in {"error", "warning", "info"}


# Resume seed behavior


class TestResumeSeedIntegration:
    def test_canonical_resume_has_no_errors(self, resume_cfg: LintConfig) -> None:
        issues = _run_lint(resume_cfg, _canonical_resume())
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], f"expected no error-severity issues, got {errors}"

    def test_missing_experience_triggers_required_sections(self, resume_cfg: LintConfig) -> None:
        data = _canonical_resume()
        data.pop("experience")
        data["education"] = {"entries": [{"school": "X"}]}
        # Need skills so section_order doesn't swamp the signal
        issues = _run_lint(resume_cfg, data)
        hits = _issues_by_rule(issues, "structure.required_sections")
        assert any("experience" in (i.message or "") for i in hits)

    def test_banned_opener_flags_ai_slop_verb(self, resume_cfg: LintConfig) -> None:
        data = _canonical_resume()
        data["experience"]["entries"][0]["bullets"][0] = "Architected a distributed consensus layer across 5 regions."
        issues = _run_lint(resume_cfg, data)
        hits = _issues_by_rule(issues, "content.experience_bullets.banned_openers")
        assert len(hits) == 1
        assert "Architected" in (hits[0].value or "")

    def test_banned_patterns_em_dash_flags_warning(self, resume_cfg: LintConfig) -> None:
        data = _canonical_resume()
        data["experience"]["entries"][0]["bullets"][0] = "Led billing migration — shipped it under budget."
        issues = _run_lint(resume_cfg, data)
        hits = _issues_by_rule(issues, "text.resume_bullets.banned_patterns_warning")
        assert any("—" in (i.value or "") for i in hits)

    def test_banned_patterns_info_flags_utilized(self, resume_cfg: LintConfig) -> None:
        data = _canonical_resume()
        data["experience"]["entries"][0]["bullets"][0] = "Utilized a distributed consensus layer across regions."
        issues = _run_lint(resume_cfg, data)
        info_hits = _issues_by_rule(issues, "text.resume_bullets.banned_patterns_info")
        # "utilized" also hits banned_openers (warning), so we specifically look for info
        assert any("utilized" in (i.value or "").lower() for i in info_hits)

    def test_missing_skills_section_applies_when_gates_skill_rules(self, resume_cfg: LintConfig) -> None:
        """schema_has_path('skills.categories') gates all skill_* rules."""
        data = _canonical_resume()
        del data["skills"]
        issues = _run_lint(resume_cfg, data)
        skill_rule_ids = {
            "content.skill_categories.min_items",
            "content.skill_categories.max_items",
            "content.skill_categories.max_child_items",
            "content.skill_categories.first_item_capitalization",
        }
        for rule_id in skill_rule_ids:
            assert _issues_by_rule(issues, rule_id) == [], f"skill rule {rule_id} fired despite missing skills section"

    def test_skills_category_banned_name_flags(self, resume_cfg: LintConfig) -> None:
        data = _canonical_resume()
        data["skills"]["categories"].append({"name": "Soft Skills", "skills": ["Empathy"]})
        issues = _run_lint(resume_cfg, data)
        hits = _issues_by_rule(issues, "content.skill_categories.banned_child_names")
        assert any("Soft Skills" in (i.value or "") for i in hits)


# Cover letter seed behavior


class TestCoverLetterSeedIntegration:
    def test_canonical_cl_runs_cleanly_enough(self, cl_cfg: LintConfig) -> None:
        """Canonical CL should produce no errors and at most info-severity suggestions."""
        issues = _run_lint(cl_cfg, _canonical_cover_letter())
        errors = [i for i in issues if i.severity == "error"]
        assert errors == []

    def test_semicolon_runon_flags_max_structural_punctuation(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        data["body_paragraphs"][0] = (
            "I've shipped services; I've owned on-call rotations; I've mentored juniors; "
            "and I've planned roadmap work across product, design, and infra for my team."
        )
        issues = _run_lint(cl_cfg, data)
        hits = _issues_by_rule(issues, "content.body_paragraphs.max_structural_punctuation")
        assert len(hits) >= 1

    def test_three_consecutive_i_openers_flag_max_consecutive_opener(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        data["body_paragraphs"][0] = "I shipped billing. I owned on-call. I mentored juniors. I planned roadmap work."
        issues = _run_lint(cl_cfg, data)
        hits = _issues_by_rule(issues, "content.body_paragraphs.max_consecutive_i")
        assert len(hits) >= 1

    def test_banned_em_dash_flags_cl_warning(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        data["body_paragraphs"][0] = (
            "Your posting caught my attention — it's the kind of problem I enjoy. "
            "I'd welcome the chance to dig into the migration work you describe in "
            "the announcement and trade notes on the platform evolution story."
        )
        issues = _run_lint(cl_cfg, data)
        hits = _issues_by_rule(issues, "text.cover_letter.banned_patterns_warning")
        assert any("—" in (i.value or "") for i in hits)

    def test_cliche_opener_flags_cl_info(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        data["body_paragraphs"][0] = (
            "I am writing to apply for the Staff role. I've spent two years reshaping "
            "pipelines and I'd welcome the chance to bring that experience into your team."
        )
        issues = _run_lint(cl_cfg, data)
        hits = _issues_by_rule(issues, "text.cover_letter.banned_patterns_info")
        assert any("writing to" in (i.value or "").lower() for i in hits)

    def test_school_mentions_max_flags_over_references(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        data["body_paragraphs"][0] = (
            "My school shaped how I think about problems. "
            "The university taught me to work in teams. "
            "At college I learned to write clearly. "
            "My alma mater still runs the seminar I took."
        )
        issues = _run_lint(cl_cfg, data)
        hits = _issues_by_rule(issues, "content.body_paragraphs.school_mentions_max")
        assert len(hits) == 1

    def test_employer_mentions_min_requires_has_employer_var_tag(self, cl_cfg: LintConfig) -> None:
        """Without the tag the rule is skipped even though {{ employer_name }} is unset."""
        data = _canonical_cover_letter()
        issues = _run_lint(cl_cfg, data)
        assert _issues_by_rule(issues, "content.body_paragraphs.employer_mentions_min") == []

    def test_employer_mentions_min_fires_with_tag_and_var(self, cl_cfg: LintConfig, tmp_path: Path) -> None:
        data = {
            "_tailor_meta": {
                "lint_tags": ["has_employer_var"],
                "lint_vars": {"employer_name": "Example Corp"},
            },
            **_canonical_cover_letter(),
        }
        stripped, meta = extract_tailor_meta(data)
        runtime = build_runtime(meta, base_dir=tmp_path)
        issues = _run_lint(cl_cfg, stripped, runtime=runtime)
        hits = _issues_by_rule(issues, "content.body_paragraphs.employer_mentions_min")
        assert len(hits) >= 1

    def test_employer_mentions_min_passes_when_mentioned_enough(self, cl_cfg: LintConfig, tmp_path: Path) -> None:
        data = {
            "_tailor_meta": {
                "lint_tags": ["has_employer_var"],
                "lint_vars": {"employer_name": "Example"},
            },
            "salutation": "Dear Hiring Manager,",
            "body_paragraphs": [
                (
                    "Example is building something I'd be proud to contribute to. "
                    "Before I applied I spent a week reading the engineering blog, "
                    "and the way Example frames reliability matches how I approach "
                    "the discipline in my current role."
                ),
                (
                    "Example's posting for the Staff role caught my attention "
                    "because the migration problem mirrors work I wrapped last "
                    "summer. I shepherded a billing pipeline through three major "
                    "refactors and the throughput tripled on the far side."
                ),
                (
                    "I'd love to trade notes with the team about how you see the "
                    "platform evolving over the next two years. Thanks for the "
                    "thoughtful posting; it made me want to answer even on a Saturday."
                ),
            ],
        }
        stripped, meta = extract_tailor_meta(data)
        runtime = build_runtime(meta, base_dir=tmp_path)
        issues = _run_lint(cl_cfg, stripped, runtime=runtime)
        assert _issues_by_rule(issues, "content.body_paragraphs.employer_mentions_min") == []

    def test_synthesis_re_enumeration_gated_by_four_paragraph_tag(self, cl_cfg: LintConfig) -> None:
        """Without the tag, synthesis_re_enumeration never fires."""
        data = {
            **_canonical_cover_letter(),
        }
        data["body_paragraphs"][2] = (
            "Throughput tripled from 50000 to 150000 events per minute on the "
            "critical path. The rewrite landed under budget and on schedule, "
            "which mattered more than any single metric to my team and peers."
        )
        issues = _run_lint(cl_cfg, data)
        assert _issues_by_rule(issues, "content.body_paragraphs.synthesis_re_enumeration") == []

    def test_synthesis_re_enumeration_fires_when_tagged(self, cl_cfg: LintConfig, tmp_path: Path) -> None:
        data = {
            "_tailor_meta": {"lint_tags": ["four_paragraph_structure"]},
            "salutation": "Dear Hiring Manager,",
            "body_paragraphs": [
                "Opening paragraph setting up the story I'm about to tell you.",
                "At my last job we shipped 50000 events per minute through the new stack.",
                "Throughput tripled to 150000 events per minute after the rewrite.",
                "Synthesis: I shipped 50000 events per minute before and 150000 after the migration landed.",
            ],
        }
        stripped, meta = extract_tailor_meta(data)
        runtime = build_runtime(meta, base_dir=tmp_path)
        issues = _run_lint(cl_cfg, stripped, runtime=runtime)
        hits = _issues_by_rule(issues, "content.body_paragraphs.synthesis_re_enumeration")
        assert len(hits) >= 1

    def test_orphan_final_word_flags_risky_terminator(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        # rewrite [0] so the final sentence terminates with a risky word ("team")
        data["body_paragraphs"][0] = (
            "Your posting for the Staff role caught my attention because the "
            "problem statement mirrors the backend migration I shipped last year. "
            "I'd welcome the chance to bring that experience into your team."
        )
        issues = _run_lint(cl_cfg, data)
        hits = _issues_by_rule(issues, "content.body_paragraphs.orphan_final_word")
        assert any("team" in (i.value or "").lower() for i in hits)


# Cross-document (sibling) behavior


class TestCoverLetterResumeEcho:
    def test_resume_echo_silent_without_sibling(self, cl_cfg: LintConfig) -> None:
        data = _canonical_cover_letter()
        issues = _run_lint(cl_cfg, data)
        assert _issues_by_rule(issues, "content.cover_letter.resume_echo_check") == []

    def test_resume_echo_fires_across_sibling(self, tmp_path: Path, cl_cfg: LintConfig) -> None:
        echo_phrase = "handled 50k transactions per day with zero downtime"

        resume_data = _canonical_resume()
        resume_data["experience"]["entries"][0]["bullets"][0] = (
            f"Shipped a billing pipeline that {echo_phrase} across three regions."
        )
        resume_path = tmp_path / "resume_data.json"
        resume_path.write_text(json.dumps(resume_data), encoding="utf-8")

        cl_path = tmp_path / "cover_letter.json"
        cl_data: dict[str, Any] = {
            "_tailor_meta": {"sibling_documents": {"resume": "resume_data.json"}},
            "salutation": "Dear Hiring Manager,",
            "body_paragraphs": [
                (
                    "Your posting caught my attention because it maps closely to "
                    "the billing migration I wrapped last summer, where I shipped "
                    f"a pipeline that {echo_phrase} in the new region."
                ),
                (
                    "I'd welcome a chance to talk about how that experience transfers. "
                    "My current scope has widened steadily over the last two quarters, "
                    "and I want to keep pushing into the platform-evolution space."
                ),
                (
                    "Thanks for the thoughtful writeup; I'd love to trade notes "
                    "even before a formal conversation about the team's platform "
                    "evolution thinking and the posting you put up."
                ),
            ],
        }
        cl_path.write_text(json.dumps(cl_data), encoding="utf-8")

        stripped, meta = extract_tailor_meta(cl_data)
        runtime = build_runtime(meta, base_dir=cl_path.parent)

        issues = _run_lint(cl_cfg, stripped, runtime=runtime)
        hits = _issues_by_rule(issues, "content.cover_letter.resume_echo_check")
        assert len(hits) >= 1, f"expected resume-echo hit, got {[i.message for i in issues]}"
