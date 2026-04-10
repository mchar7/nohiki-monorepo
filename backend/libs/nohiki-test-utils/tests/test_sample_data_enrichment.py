"""Tests for sample_data._enrichment and RawJobPosting simulation pipeline."""

from __future__ import annotations

from nohiki_test_utils.sample_data._enrichment import (
    STRIP_EEO,
    fix_unicode_artifacts,
    replace_text,
    strip_html_tags,
    strip_paragraphs_containing,
)
from nohiki_test_utils.sample_data._types import RawJobPosting
from nohiki_test_utils.sample_data.raw_postings.healthcare import (
    NURSE_ICU_ONSITE_POSTING,
    PHARMACIST_HYBRID_POSTING,
    PHYSICAL_THERAPIST_POSTING,
)
from nohiki_test_utils.sample_data.raw_postings.software import (
    SENIOR_PYTHON_REMOTE_POSTING,
    STAFF_PLATFORM_HYBRID_POSTING,
)

_ALL_POSTINGS = [
    SENIOR_PYTHON_REMOTE_POSTING,
    STAFF_PLATFORM_HYBRID_POSTING,
    NURSE_ICU_ONSITE_POSTING,
    PHYSICAL_THERAPIST_POSTING,
    PHARMACIST_HYBRID_POSTING,
]


class TestStripParagraphsContaining:
    """Tests for strip_paragraphs_containing transform factory."""

    def test_strips_matching_paragraph(self) -> None:
        """Paragraphs containing the marker are removed."""
        text = "First paragraph.\n\nContains keyword here.\n\nThird paragraph."
        result = strip_paragraphs_containing("keyword")(text)
        assert result == "First paragraph.\n\nThird paragraph."

    def test_preserves_non_matching_paragraphs(self) -> None:
        """Paragraphs without the marker are preserved unchanged."""
        text = "One.\n\nTwo.\n\nThree."
        assert strip_paragraphs_containing("missing")(text) == text

    def test_case_insensitive_match(self) -> None:
        """Matching is case-insensitive."""
        text = "Keep this.\n\nEqual Opportunity Employer.\n\nKeep this too."
        result = strip_paragraphs_containing("equal opportunity")(text)
        assert "equal opportunity" not in result.lower()
        assert "Keep this." in result

    def test_multiple_markers_any_triggers_removal(self) -> None:
        """A paragraph containing any marker is removed."""
        text = "Good.\n\nHas keyword1.\n\nHas keyword2.\n\nGood again."
        result = strip_paragraphs_containing("keyword1", "keyword2")(text)
        assert "keyword1" not in result
        assert "keyword2" not in result
        assert "Good." in result

    def test_single_matching_paragraph_returns_empty(self) -> None:
        """A single paragraph that matches results in empty string."""
        result = strip_paragraphs_containing("equal opportunity")("We are an equal opportunity employer.")
        assert result == ""

    def test_triple_newlines_treated_as_paragraph_break(self) -> None:
        """3+ consecutive newlines are treated as paragraph separators."""
        text = "First.\n\n\nHas marker.\n\n\nThird."
        result = strip_paragraphs_containing("marker")(text)
        assert "First." in result
        assert "Third." in result
        assert "Has marker" not in result


class TestStripHtmlTags:
    """Tests for strip_html_tags transform factory."""

    def test_strips_block_tags(self) -> None:
        """Block-level HTML tags are removed."""
        assert strip_html_tags()("<p>Hello world</p>") == "Hello world"

    def test_strips_nested_tags(self) -> None:
        """Nested tags are all removed."""
        assert strip_html_tags()("<ul><li>One</li><li>Two</li></ul>") == "OneTwo"

    def test_decodes_amp(self) -> None:
        """&amp; is decoded to &."""
        assert strip_html_tags()("A &amp; B") == "A & B"

    def test_decodes_lt_gt(self) -> None:
        """&lt; and &gt; are decoded."""
        assert strip_html_tags()("a &lt; b &gt; c") == "a < b > c"

    def test_decodes_nbsp(self) -> None:
        """&nbsp; is decoded to a space."""
        assert strip_html_tags()("word&nbsp;word") == "word word"

    def test_decodes_numeric_39(self) -> None:
        """&#39; is decoded to apostrophe."""
        assert strip_html_tags()("it&#39;s") == "it's"

    def test_decodes_numeric_43(self) -> None:
        """&#43; is decoded to plus."""
        assert strip_html_tags()("5&#43;3") == "5+3"

    def test_decodes_quot(self) -> None:
        """&quot; is decoded to double quote."""
        assert strip_html_tags()("&quot;hi&quot;") == '"hi"'

    def test_decodes_hex_x27(self) -> None:
        """&#x27; hex entity is decoded to apostrophe."""
        assert strip_html_tags()("it&#x27;s") == "it's"

    def test_preserves_plain_text(self) -> None:
        """Plain text without markup is returned unchanged."""
        text = "Just plain text."
        assert strip_html_tags()(text) == text

    def test_strips_then_decodes(self) -> None:
        """Tags are stripped first, entities decoded after."""
        assert strip_html_tags()("<b>Bold &amp; clear</b>") == "Bold & clear"


class TestFixUnicodeArtifacts:
    """Tests for fix_unicode_artifacts transform factory."""

    def test_replaces_right_single_quote(self) -> None:
        r"""\u2019 is replaced with ASCII apostrophe."""
        assert fix_unicode_artifacts()("it\u2019s") == "it's"

    def test_replaces_left_single_quote(self) -> None:
        r"""\u2018 is replaced with ASCII apostrophe."""
        assert fix_unicode_artifacts()("\u2018text\u2019") == "'text'"

    def test_replaces_left_double_quote(self) -> None:
        r"""\u201c is replaced with ASCII double quote."""
        assert fix_unicode_artifacts()("\u201chello\u201d") == '"hello"'

    def test_replaces_en_dash(self) -> None:
        r"""\u2013 (en dash) is replaced with hyphen."""
        assert fix_unicode_artifacts()("2013\u20132025") == "2013-2025"

    def test_replaces_em_dash(self) -> None:
        r"""\u2014 (em dash) is replaced with double hyphen."""
        assert fix_unicode_artifacts()("word\u2014word") == "word--word"

    def test_replaces_non_breaking_space(self) -> None:
        r"""\u00a0 (non-breaking space) is replaced with regular space."""
        assert fix_unicode_artifacts()("a\u00a0b") == "a b"

    def test_preserves_plain_ascii(self) -> None:
        """Plain ASCII text is returned unchanged."""
        text = "Normal text with 'apostrophes' and \"quotes\"."
        assert fix_unicode_artifacts()(text) == text

    def test_multiple_replacements_in_sequence(self) -> None:
        """Multiple different unicode chars are all replaced in one pass."""
        text = "It\u2019s \u2013 a \u201cgood\u201d day."
        result = fix_unicode_artifacts()(text)
        assert "\u2019" not in result
        assert "\u2013" not in result
        assert "\u201c" not in result
        assert "\u201d" not in result


class TestReplaceText:
    """Tests for replace_text transform factory (covers lines 103-106)."""

    def test_replaces_single_occurrence(self) -> None:
        """A single occurrence is replaced."""
        assert replace_text("old", "new")("text with old value") == "text with new value"

    def test_replaces_multiple_occurrences(self) -> None:
        """All occurrences are replaced."""
        assert replace_text("x", "y")("x and x and x") == "y and y and y"

    def test_default_replacement_is_empty_string(self) -> None:
        """Default replacement removes the substring."""
        assert replace_text("remove ")("please remove this") == "please this"

    def test_no_match_returns_original(self) -> None:
        """Text with no match is returned unchanged."""
        text = "no match here"
        assert replace_text("xyz")(text) == text

    def test_replace_with_empty_string_explicit(self) -> None:
        """Explicit empty string replacement removes the substring."""
        assert replace_text("bad", "")("bad content bad") == " content "


class TestStripEEO:
    """Tests for the STRIP_EEO pre-built transform constant."""

    def test_strips_equal_opportunity_paragraph(self) -> None:
        """Paragraph containing 'equal opportunity' is removed."""
        text = "Job description.\n\nWe are an equal opportunity employer."
        result = STRIP_EEO(text)
        assert "equal opportunity" not in result.lower()
        assert "Job description." in result

    def test_preserves_company_culture_content(self) -> None:
        """Company culture and values content in other paragraphs is preserved."""
        text = (
            "About Us\n\n"
            "We are a mission-driven team focused on innovation.\n\n"
            "We are an equal opportunity employer and do not discriminate.\n\n"
            "The Role\n\n"
            "You will build great things."
        )
        result = STRIP_EEO(text)
        assert "mission-driven" in result
        assert "You will build great things." in result
        assert "equal opportunity" not in result.lower()

    def test_case_insensitive_eeo_detection(self) -> None:
        """EEO paragraphs with uppercase are also stripped."""
        text = "Content.\n\nXYZ Corp Is An Equal Opportunity Employer."
        result = STRIP_EEO(text)
        assert "Equal Opportunity" not in result


class TestRawJobPostingSimulateEnrichment:
    """Tests for RawJobPosting.simulate_enrichment() pipeline."""

    def test_no_transforms_returns_stripped_raw(self) -> None:
        """With no transforms, returns stripped raw text."""
        posting = RawJobPosting(raw="  hello world  ")
        assert posting.simulate_enrichment() == "hello world"

    def test_single_transform_applied(self) -> None:
        """A single transform is applied to the raw text."""
        posting = RawJobPosting(
            raw="text with equal opportunity paragraph\n\nKeep this.",
            enrichment_transforms=(strip_paragraphs_containing("equal opportunity"),),
        )
        result = posting.simulate_enrichment()
        assert "equal opportunity" not in result.lower()
        assert "Keep this." in result

    def test_multiple_transforms_applied_in_order(self) -> None:
        """Transforms are applied in sequence."""
        posting = RawJobPosting(
            raw="<b>it\u2019s</b> a test",
            enrichment_transforms=(strip_html_tags(), fix_unicode_artifacts()),
        )
        result = posting.simulate_enrichment()
        assert "<b>" not in result
        assert "\u2019" not in result
        assert result == "it's a test"

    def test_result_is_stripped(self) -> None:
        """Leading/trailing whitespace is stripped from the final result."""
        posting = RawJobPosting(raw="\n\n  text content  \n\n")
        assert posting.simulate_enrichment() == "text content"

    def test_transform_order_matters(self) -> None:
        """Transforms are applied in the order specified."""
        posting = RawJobPosting(
            raw="REMOVE_ME and keep",
            enrichment_transforms=(replace_text("REMOVE_ME and ", ""),),
        )
        assert posting.simulate_enrichment() == "keep"


class TestActualPostings:
    """Smoke tests for the actual posting constants."""

    def test_all_postings_have_non_empty_raw(self) -> None:
        """All posting constants have non-empty raw text."""
        for posting in _ALL_POSTINGS:
            assert len(posting.raw.strip()) > 100

    def test_all_postings_produce_enriched_string(self) -> None:
        """All posting constants produce a non-empty enriched string."""
        for posting in _ALL_POSTINGS:
            result = posting.simulate_enrichment()
            assert isinstance(result, str)
            assert len(result) > 50

    def test_eeo_not_in_any_enriched_description(self) -> None:
        """No enriched description contains 'equal opportunity' (all use STRIP_EEO)."""
        for posting in _ALL_POSTINGS:
            assert "equal opportunity" not in posting.simulate_enrichment().lower()

    def test_staff_platform_raw_contains_html_artifacts(self) -> None:
        """Staff platform hybrid posting raw text contains HTML markup."""
        raw = STAFF_PLATFORM_HYBRID_POSTING.raw
        assert "<" in raw or "&amp;" in raw or "&#" in raw

    def test_staff_platform_enriched_has_no_html_tags(self) -> None:
        """Staff platform hybrid posting enriched text has no HTML tags."""
        enriched = STAFF_PLATFORM_HYBRID_POSTING.simulate_enrichment()
        assert "<" not in enriched
        assert ">" not in enriched

    def test_staff_platform_enriched_has_no_html_entities(self) -> None:
        """Staff platform hybrid posting enriched text has no undecoded HTML entities."""
        enriched = STAFF_PLATFORM_HYBRID_POSTING.simulate_enrichment()
        assert "&amp;" not in enriched
        assert "&#39;" not in enriched
        assert "&#43;" not in enriched
        assert "&#x27;" not in enriched

    def test_pharmacist_raw_contains_unicode_artifacts(self) -> None:
        """Pharmacist hybrid posting raw text contains unicode artifacts."""
        raw = PHARMACIST_HYBRID_POSTING.raw
        assert any(char in raw for char in ("\u2014", "\u2019", "\u00a0"))

    def test_pharmacist_enriched_has_no_unicode_artifacts(self) -> None:
        """Pharmacist hybrid posting enriched text has no unicode artifacts."""
        enriched = PHARMACIST_HYBRID_POSTING.simulate_enrichment()
        for char in ("\u2014", "\u2019", "\u00a0", "\u2013", "\u201c", "\u201d"):
            assert char not in enriched, f"Unicode artifact {char!r} found in enriched text"

    def test_enriched_descriptions_preserve_compensation_content(self) -> None:
        """Enriched descriptions retain benefits/compensation section content."""
        for posting in _ALL_POSTINGS:
            enriched = posting.simulate_enrichment()
            assert any(
                kw in enriched.lower()
                for kw in ("salary", "compensation", "hourly", "annual", "$", "benefits", "401", "insurance")
            ), "No compensation content found in enriched description"
