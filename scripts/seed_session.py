#!/usr/bin/env python3
"""
seed_session.py — Dev helper that loads sample CSV and creates a session
WITHOUT calling the Claude API. Prints the review URL to visit in browser.

Usage:
    cd congrats-agent
    python scripts/seed_session.py
    # Then visit the printed URL in your browser
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import ReviewSession, ReviewEntry, HandleSuggestion, PostCopy
from app.ingestion.csv_reader import load_csv
from app.ingestion.extractor import extract_top_finishers
from app.review.session_store import store
from app.main import create_app


def fake_handle(finisher) -> HandleSuggestion:
    slug = finisher.full_name.lower().replace(" ", "")
    return HandleSuggestion(
        instagram_handle=f"@{slug}_runs",
        instagram_url=f"https://instagram.com/{slug}_runs",
        facebook_name=finisher.full_name,
        facebook_url=f"https://facebook.com/{slug}",
        confidence="low",
        reasoning="Seeded by seed_session.py — not real AI output.",
    )


def fake_copy(finisher, category, place) -> PostCopy:
    place_suffix = {1: "st", 2: "nd", 3: "rd"}.get(place, "th")
    return PostCopy(
        instagram_text=(
            f"🏃 Congrats to {finisher.full_name} on finishing {place}{place_suffix} "
            f"in {category} at {finisher.race_name}! "
            f"⏱ {finisher.finish_time} #MarathonGuide #Running"
        )[:280],
        facebook_text=(
            f"Congratulations to {finisher.full_name} from {finisher.city}, {finisher.state} "
            f"on a fantastic {place}{place_suffix} place finish in {category} "
            f"at {finisher.race_name} with a time of {finisher.finish_time}!"
        ),
    )


def seed():
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "sample_results.csv"
    )
    with open(csv_path, "rb") as f:
        finishers = load_csv(f.read())

    top = extract_top_finishers(finishers)
    session = ReviewSession.create(
        race_name=finishers[0].race_name,
        race_date=finishers[0].race_date,
    )

    for category, place, finisher in top:
        handle = fake_handle(finisher)
        copy = fake_copy(finisher, category, place)
        entry = ReviewEntry.create(finisher, category, place, handle, copy)
        session.entries.append(entry)

    store.create(session)
    return session


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        session = seed()
        print(f"\n✅ Seeded session: {session.session_id}")
        print(f"   Entries: {session.total}")
        print(f"\n👉 Visit: http://localhost:8080/review/{session.session_id}\n")

    # Run the app so you can actually browse it
    # use_reloader=False prevents the process restart that would wipe the in-memory session
    app.run(debug=True, port=8080, use_reloader=False)
