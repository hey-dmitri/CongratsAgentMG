from __future__ import annotations

from collections import defaultdict
from app.models import Finisher

TOP_N = 3


def _fill_missing_places(finishers: list[Finisher]) -> list[Finisher]:
    """
    MarathonGuide exports often omit gender_place and age_group_place for most
    runners. Derive them from overall_place ordering within each group.
    """
    # Gender place
    by_gender: dict[str, list[Finisher]] = defaultdict(list)
    for f in finishers:
        by_gender[f.gender].append(f)

    for gender_finishers in by_gender.values():
        sorted_group = sorted(gender_finishers, key=lambda f: f.overall_place)
        for rank, f in enumerate(sorted_group, start=1):
            f.gender_place = rank

    # Age group place
    by_ag: dict[str, list[Finisher]] = defaultdict(list)
    for f in finishers:
        by_ag[f.age_group].append(f)

    for ag_finishers in by_ag.values():
        sorted_group = sorted(ag_finishers, key=lambda f: f.overall_place)
        for rank, f in enumerate(sorted_group, start=1):
            f.age_group_place = rank

    return finishers


def extract_top_finishers(finishers: list[Finisher]) -> list[tuple[str, int, Finisher]]:
    """
    Extract top finishers across categories.

    Returns a list of (category, place, Finisher) tuples.

    Categories:
    - "Overall Male" / "Overall Female": top 3 by gender_place
    - "Age Group <group>": top 3 per age_group
    """
    finishers = _fill_missing_places(finishers)

    results: list[tuple[str, int, Finisher]] = []
    seen_ids: set[tuple[str, str]] = set()

    def _add(category: str, place: int, f: Finisher) -> None:
        key = (category, f.bib)
        if key not in seen_ids:
            seen_ids.add(key)
            results.append((category, place, f))

    # Overall top 3 Male + top 3 Female only
    for label, gender_code in [("Overall Male", "M"), ("Overall Female", "F")]:
        group = sorted(
            [f for f in finishers if f.gender == gender_code],
            key=lambda f: f.gender_place,
        )
        for place, f in enumerate(group[:TOP_N], start=1):
            _add(label, place, f)

    return results
