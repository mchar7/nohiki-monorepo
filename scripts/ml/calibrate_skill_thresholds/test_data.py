"""Regression tests for bounded calibration pair sampling."""

from __future__ import annotations

import csv
from pathlib import Path

from calibrate_skill_thresholds.data import generate_calibration_dataset


def test_substring_pairs_survive_bounded_distinct_sampling(tmp_path: Path) -> None:
    """Keep required substring negatives when the distinct-pair budget is bounded."""
    csv_path = tmp_path / "skills.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["ID", "PREFERREDLABEL", "ALTLABELS", "SKILLTYPE", "DESCRIPTION"],
        )
        writer.writeheader()
        writer.writerows(
            [
                {"ID": "bio", "PREFERREDLABEL": "Bio", "ALTLABELS": "", "SKILLTYPE": "skill", "DESCRIPTION": ""},
                {
                    "ID": "biochemistry",
                    "PREFERREDLABEL": "Biochemistry",
                    "ALTLABELS": "",
                    "SKILLTYPE": "skill",
                    "DESCRIPTION": "",
                },
                {"ID": "cloud", "PREFERREDLABEL": "Cloud", "ALTLABELS": "", "SKILLTYPE": "skill", "DESCRIPTION": ""},
                {
                    "ID": "cloud-computing",
                    "PREFERREDLABEL": "Cloud computing",
                    "ALTLABELS": "",
                    "SKILLTYPE": "skill",
                    "DESCRIPTION": "",
                },
                {
                    "ID": "data-analysis",
                    "PREFERREDLABEL": "Data analysis",
                    "ALTLABELS": "",
                    "SKILLTYPE": "skill",
                    "DESCRIPTION": "",
                },
                {
                    "ID": "data-science",
                    "PREFERREDLABEL": "Data science",
                    "ALTLABELS": "",
                    "SKILLTYPE": "skill",
                    "DESCRIPTION": "",
                },
            ]
        )

    dataset = generate_calibration_dataset(
        csv_path,
        max_synonym_pairs=1,
        max_distinct_pairs=2,
        max_substring_pairs=2,
        seed=7,
    )

    actual_pairs = {(pair.skill_a, pair.skill_b) for pair in dataset.distinct_similar}
    assert actual_pairs == {("Bio", "Biochemistry"), ("Cloud", "Cloud computing")}  # noqa: S101

    assert all(pair.pair_type.value == "distinct_similar" for pair in dataset.distinct_similar)  # noqa: S101
