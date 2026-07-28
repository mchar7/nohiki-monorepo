"""Synthetic test pairs for validating threshold calibration.

These pairs are manually curated to test edge cases that Tabiya aliases don't cover:
1. Abbreviations (JavaScript vs JS)
2. Spelling variants (Sr. vs Senior)
3. Word order variations
4. Semantic equivalents that Jaccard can't detect

This validates whether Jaccard alone is sufficient or if we need additional metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypedDict

from calibrate_skill_thresholds.analysis import JaccardAnalyzer

_ABBREVIATION = "Common abbreviation"
_PLURAL_FORM = "Plural form"
_COL_PAIR_A = "Pair A"
_COL_PAIR_B = "Pair B"


class ExpectedResult(Enum):
    """Expected matching result for a test pair."""

    SHOULD_MATCH = "should_match"
    SHOULD_NOT_MATCH = "should_not_match"


@dataclass(frozen=True)
class SyntheticPair:
    """A manually curated test pair with expected result."""

    text_a: str
    text_b: str
    expected: ExpectedResult
    reason: str


# Pairs that SHOULD match but likely WON'T via Jaccard alone
SYNONYM_PAIRS_JACCARD_WILL_MISS: list[SyntheticPair] = [
    SyntheticPair("JavaScript", "JS", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair("TypeScript", "TS", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair("Python programming", "Python development", ExpectedResult.SHOULD_MATCH, "Semantic equivalent"),
    SyntheticPair("machine learning", "ML", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair("artificial intelligence", "AI", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair(
        "Senior Software Engineer", "Sr. Software Engineer", ExpectedResult.SHOULD_MATCH, "Title abbreviation"
    ),
    SyntheticPair("database management", "DB management", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair("user interface design", "UI design", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair("quality assurance", "QA", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
    SyntheticPair("continuous integration", "CI", ExpectedResult.SHOULD_MATCH, _ABBREVIATION),
]

# Pairs that SHOULD match and likely WILL via Jaccard
SYNONYM_PAIRS_JACCARD_SHOULD_CATCH: list[SyntheticPair] = [
    SyntheticPair("project management", "project managment", ExpectedResult.SHOULD_MATCH, "Common typo"),
    SyntheticPair("software development", "software developement", ExpectedResult.SHOULD_MATCH, "Common typo"),
    SyntheticPair("data analysis", "data analyses", ExpectedResult.SHOULD_MATCH, _PLURAL_FORM),
    SyntheticPair("create database", "create databases", ExpectedResult.SHOULD_MATCH, _PLURAL_FORM),
    SyntheticPair("manage team", "manage teams", ExpectedResult.SHOULD_MATCH, _PLURAL_FORM),
]

# Pairs that SHOULD NOT match (genuinely distinct)
DISTINCT_PAIRS: list[SyntheticPair] = [
    SyntheticPair("Java", "JavaScript", ExpectedResult.SHOULD_NOT_MATCH, "Different languages"),
    SyntheticPair("Python", "PyTorch", ExpectedResult.SHOULD_NOT_MATCH, "Language vs framework"),
    SyntheticPair("React", "React Native", ExpectedResult.SHOULD_NOT_MATCH, "Web vs mobile framework"),
    SyntheticPair("frontend development", "backend development", ExpectedResult.SHOULD_NOT_MATCH, "Different domains"),
    SyntheticPair("data science", "data entry", ExpectedResult.SHOULD_NOT_MATCH, "Different roles"),
    SyntheticPair("Romanian language", "Romani language", ExpectedResult.SHOULD_NOT_MATCH, "Different languages"),
    SyntheticPair(
        "Salt", "tools for software configuration", ExpectedResult.SHOULD_NOT_MATCH, "Specific tool vs category"
    ),
]


class PairTestResult(TypedDict):
    """Typed result entry for a single pair test."""

    pair: tuple[str, str]
    score: float
    would_auto_match: bool
    reason: str
    correct_behavior: bool


class SummaryResult(TypedDict):
    """Aggregated summary of synthetic test results."""

    jaccard_will_miss_count: int
    jaccard_should_catch_correct: str
    distinct_correct: str


class SyntheticTestResults(TypedDict):
    """Full results from run_synthetic_tests."""

    threshold: float
    jaccard_will_miss: list[PairTestResult]
    jaccard_should_catch: list[PairTestResult]
    distinct_pairs: list[PairTestResult]
    summary: SummaryResult


def run_synthetic_tests(threshold: float = 0.92) -> SyntheticTestResults:
    """Run all synthetic tests and return results."""
    analyzer = JaccardAnalyzer()

    jaccard_will_miss: list[PairTestResult] = []
    jaccard_should_catch: list[PairTestResult] = []
    distinct_pairs_results: list[PairTestResult] = []

    # Test pairs Jaccard will miss (expected: low scores, but SHOULD match semantically)
    for pair in SYNONYM_PAIRS_JACCARD_WILL_MISS:
        score = analyzer.compute_similarity(pair.text_a, pair.text_b)
        would_match = score >= threshold
        jaccard_will_miss.append(
            PairTestResult(
                pair=(pair.text_a, pair.text_b),
                score=round(score, 4),
                would_auto_match=would_match,
                reason=pair.reason,
                correct_behavior=not would_match,
            )
        )

    # Test pairs Jaccard should catch (expected: high scores)
    jaccard_catch_correct = 0
    for pair in SYNONYM_PAIRS_JACCARD_SHOULD_CATCH:
        score = analyzer.compute_similarity(pair.text_a, pair.text_b)
        would_match = score >= threshold
        correct = would_match
        if correct:
            jaccard_catch_correct += 1
        jaccard_should_catch.append(
            PairTestResult(
                pair=(pair.text_a, pair.text_b),
                score=round(score, 4),
                would_auto_match=would_match,
                reason=pair.reason,
                correct_behavior=correct,
            )
        )

    # Test distinct pairs (expected: should NOT match)
    distinct_correct = 0
    for pair in DISTINCT_PAIRS:
        score = analyzer.compute_similarity(pair.text_a, pair.text_b)
        would_match = score >= threshold
        correct = not would_match
        if correct:
            distinct_correct += 1
        distinct_pairs_results.append(
            PairTestResult(
                pair=(pair.text_a, pair.text_b),
                score=round(score, 4),
                would_auto_match=would_match,
                reason=pair.reason,
                correct_behavior=correct,
            )
        )

    return SyntheticTestResults(
        threshold=threshold,
        jaccard_will_miss=jaccard_will_miss,
        jaccard_should_catch=jaccard_should_catch,
        distinct_pairs=distinct_pairs_results,
        summary=SummaryResult(
            jaccard_will_miss_count=len(SYNONYM_PAIRS_JACCARD_WILL_MISS),
            jaccard_should_catch_correct=f"{jaccard_catch_correct}/{len(SYNONYM_PAIRS_JACCARD_SHOULD_CATCH)}",
            distinct_correct=f"{distinct_correct}/{len(DISTINCT_PAIRS)}",
        ),
    )


def print_synthetic_test_results(threshold: float = 0.92) -> None:
    """Print synthetic test results in a readable format."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    results = run_synthetic_tests(threshold)

    console.print(f"\n[bold cyan]Synthetic Tests at threshold {threshold}[/bold cyan]\n")

    # Pairs Jaccard will miss (by design - goes to semantic/LLM)
    table1 = Table(title="Synonym Pairs Jaccard Will Miss (goes to semantic/LLM)")
    table1.add_column(_COL_PAIR_A)
    table1.add_column(_COL_PAIR_B)
    table1.add_column("Score", justify="right")
    table1.add_column("Reason")
    for item in results["jaccard_will_miss"]:
        table1.add_row(
            item["pair"][0],
            item["pair"][1],
            f"{item['score']:.4f}",
            item["reason"],
        )
    console.print(table1)

    # Pairs Jaccard should catch
    table2 = Table(title="Synonym Pairs Jaccard Should Catch")
    table2.add_column(_COL_PAIR_A)
    table2.add_column(_COL_PAIR_B)
    table2.add_column("Score", justify="right")
    table2.add_column("Auto-Match?")
    table2.add_column("Correct?")
    for item in results["jaccard_should_catch"]:
        status = "[green]✓[/green]" if item["correct_behavior"] else "[red]✗[/red]"
        table2.add_row(
            item["pair"][0],
            item["pair"][1],
            f"{item['score']:.4f}",
            "Yes" if item["would_auto_match"] else "No",
            status,
        )
    console.print(table2)

    # Distinct pairs
    table3 = Table(title="Distinct Pairs (should NOT match)")
    table3.add_column(_COL_PAIR_A)
    table3.add_column(_COL_PAIR_B)
    table3.add_column("Score", justify="right")
    table3.add_column("Auto-Match?")
    table3.add_column("Correct?")
    for item in results["distinct_pairs"]:
        status = "[green]✓[/green]" if item["correct_behavior"] else "[red]✗[/red]"
        table3.add_row(
            item["pair"][0],
            item["pair"][1],
            f"{item['score']:.4f}",
            "Yes" if item["would_auto_match"] else "No",
            status,
        )
    console.print(table3)

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Jaccard catches: {results['summary']['jaccard_should_catch_correct']}")
    console.print(f"  Distinct correct: {results['summary']['distinct_correct']}")
    console.print(
        f"  Jaccard misses (by design): {results['summary']['jaccard_will_miss_count']} pairs → semantic/LLM\n"
    )


if __name__ == "__main__":
    print_synthetic_test_results()
