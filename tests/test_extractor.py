import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.ingestion.csv_reader import load_csv
from app.ingestion.extractor import extract_top_finishers, TOP_N


SAMPLE_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "sample_results.csv"
)


@pytest.fixture
def finishers():
    with open(SAMPLE_CSV_PATH, "rb") as f:
        return load_csv(f.read())


def test_load_csv_returns_correct_count(finishers):
    assert len(finishers) == 50


def test_all_finishers_have_required_fields(finishers):
    for f in finishers:
        assert f.full_name
        assert f.gender in ("M", "F")
        assert f.overall_place > 0
        assert f.age_group


def test_extract_top_finishers_categories(finishers):
    results = extract_top_finishers(finishers)
    categories = {cat for cat, _, _ in results}

    assert "Overall Male" in categories
    assert "Overall Female" in categories
    assert len(categories) == 2


def test_extract_top_finishers_top_n_per_category(finishers):
    results = extract_top_finishers(finishers)
    from collections import Counter
    cat_counts = Counter(cat for cat, _, _ in results)

    for cat, count in cat_counts.items():
        assert count <= TOP_N, f"{cat} has {count} entries, expected <= {TOP_N}"


def test_extract_top_finishers_places_are_sequential(finishers):
    results = extract_top_finishers(finishers)
    from collections import defaultdict
    cat_places: dict[str, list[int]] = defaultdict(list)
    for cat, place, _ in results:
        cat_places[cat].append(place)

    for cat, places in cat_places.items():
        assert sorted(places) == list(range(1, len(places) + 1)), \
            f"{cat} places are not sequential: {places}"


def test_extract_overall_male_top3_by_gender_place(finishers):
    results = extract_top_finishers(finishers)
    male_overall = [(place, f) for cat, place, f in results if cat == "Overall Male"]
    assert len(male_overall) == TOP_N

    # Places should be 1, 2, 3
    places = [p for p, _ in male_overall]
    assert places == [1, 2, 3]

    # Gender place should match
    for place, f in male_overall:
        assert f.gender_place == place


def test_extract_overall_female_top3_by_gender_place(finishers):
    results = extract_top_finishers(finishers)
    female_overall = [(place, f) for cat, place, f in results if cat == "Overall Female"]
    assert len(female_overall) == TOP_N

    for place, f in female_overall:
        assert f.gender_place == place
        assert f.gender == "F"


def test_no_duplicate_entries_per_category(finishers):
    results = extract_top_finishers(finishers)
    seen = set()
    for cat, _, f in results:
        key = (cat, f.bib)
        assert key not in seen, f"Duplicate entry: {key}"
        seen.add(key)
