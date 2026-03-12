from datetime import datetime
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    jsonify, flash, current_app
)

from app.models import ReviewSession, ReviewEntry
from app.review.session_store import store
from app.ingestion.csv_reader import load_csv
from app.ingestion.extractor import extract_top_finishers
from app.ai.handle_finder import find_handles, generate_post_copy
from app.ai.search_cache import get_cache

bp = Blueprint("review", __name__)


@bp.route("/")
def upload_page():
    cache = get_cache()
    recent = store.get_recent_approved()
    return render_template("upload.html", cache_size=cache.size(), recent_approved=recent)


@bp.route("/clear-cache", methods=["POST"])
def clear_cache():
    get_cache().clear()
    flash("Search cache cleared — next run will fetch fresh results.", "success")
    return redirect(url_for("review.upload_page"))


@bp.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("Please select a CSV file.", "error")
        return redirect(url_for("review.upload_page"))

    if not file.filename.lower().endswith(".csv"):
        flash("Only .csv files are supported.", "error")
        return redirect(url_for("review.upload_page"))

    try:
        content = file.read()
        finishers = load_csv(content, filename=file.filename)
    except ValueError as e:
        flash(f"CSV error: {e}", "error")
        return redirect(url_for("review.upload_page"))

    if not finishers:
        flash("No valid rows found in CSV.", "error")
        return redirect(url_for("review.upload_page"))

    top_finishers = extract_top_finishers(finishers)
    if not top_finishers:
        flash("Could not identify top finishers from the CSV data.", "error")
        return redirect(url_for("review.upload_page"))

    # Build session and kick off background processing
    first = finishers[0]
    session = ReviewSession.create(race_name=first.race_name, race_date=first.race_date)
    store.create(session)
    store.set_processing(session.session_id, total=len(top_finishers))

    def process_one(app, session_id, category, place, finisher):
        """Process a single finisher — runs in a thread pool worker."""
        with app.app_context():
            print(f"\n[upload] Processing {finisher.full_name} ({category} #{place})", flush=True)
            handle = find_handles(finisher)
            copy = generate_post_copy(finisher, category, place, handle)
            entry = ReviewEntry.create(finisher, category, place, handle, copy)
            if not handle.instagram_handle and not handle.facebook_url and not handle.facebook_name:
                entry.status = "skipped"
                entry.reviewer_notes = "Auto-skipped: no handles found"
            return entry

    def process_in_background(app, session_id, top_finishers):
        with app.app_context():
            print(f"\n[upload] Starting parallel processing for session {session_id}", flush=True)
            try:
                futures = {}
                with ThreadPoolExecutor(max_workers=6) as executor:
                    for category, place, finisher in top_finishers:
                        f = executor.submit(process_one, app, session_id, category, place, finisher)
                        futures[f] = (category, place, finisher)

                    for f in as_completed(futures):
                        try:
                            entry = f.result()
                            s = store.get(session_id)
                            if s:
                                s.entries.append(entry)
                        except Exception as e:
                            category, place, finisher = futures[f]
                            print(f"\n[upload] Failed {finisher.full_name}: {e}", flush=True)
                        store.increment_processed(session_id)

                # Sort entries by overall finish place
                s = store.get(session_id)
                if s:
                    s.entries.sort(key=lambda e: e.finisher.overall_place)

                print(f"\n[upload] Processing complete for session {session_id}", flush=True)
                store.set_processing_done(session_id)
            except Exception as e:
                print(f"\n[upload] Processing error: {e}", flush=True)
                store.set_processing_done(session_id, error=str(e))

    app = current_app._get_current_object()
    t = Thread(target=process_in_background, args=(app, session.session_id, top_finishers), daemon=True)
    t.start()

    return redirect(url_for("review.processing", session_id=session.session_id))


@bp.route("/review/<session_id>/processing")
def processing(session_id: str):
    session = store.get(session_id)
    if not session:
        flash("Session not found.", "error")
        return redirect(url_for("review.upload_page"))
    return render_template("processing.html", session=session)


@bp.route("/review/<session_id>/processing-status")
def processing_status(session_id: str):
    status = store.get_processing_status(session_id)
    if not status:
        return jsonify({"error": "Not found"}), 404
    return jsonify(status)


@bp.route("/review/<session_id>")
def dashboard(session_id: str):
    session = store.get(session_id)
    if not session:
        flash("Session not found or expired.", "error")
        return redirect(url_for("review.upload_page"))
    return render_template("review.html", session=session)


@bp.route("/review/<session_id>/entry/<entry_id>")
def entry_view(session_id: str, entry_id: str):
    session = store.get(session_id)
    entry = store.get_entry(session_id, entry_id)
    if not session or not entry:
        flash("Entry not found.", "error")
        return redirect(url_for("review.dashboard", session_id=session_id))
    # Don't present entries with no handles — redirect to dashboard
    h = entry.handle_suggestion
    if not h.instagram_handle and not h.facebook_url and not h.facebook_name:
        flash(f"No handles found for {entry.finisher.full_name} — nothing to review.", "warning")
        return redirect(url_for("review.dashboard", session_id=session_id))
    return render_template("review_entry.html", session=session, entry=entry)


@bp.route("/review/<session_id>/entry/<entry_id>/approve", methods=["POST"])
def approve_entry(session_id: str, entry_id: str):
    entry = store.get_entry(session_id, entry_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404

    form = request.form
    entry.edited_instagram_handle = form.get("instagram_handle", "").strip()
    entry.edited_facebook_url = form.get("facebook_url", "").strip()
    entry.edited_instagram_text = form.get("instagram_text", "").strip()
    entry.edited_facebook_text = form.get("facebook_text", "").strip()
    entry.reviewer_notes = form.get("reviewer_notes", "").strip()

    # "edited" if any field was changed from AI suggestion
    ai_handle = entry.handle_suggestion.instagram_handle
    ai_ig = entry.post_copy.instagram_text
    ai_fb = entry.post_copy.facebook_text
    was_edited = (
        (entry.edited_instagram_handle and entry.edited_instagram_handle != ai_handle)
        or (entry.edited_instagram_text and entry.edited_instagram_text != ai_ig)
        or (entry.edited_facebook_text and entry.edited_facebook_text != ai_fb)
    )
    entry.status = "edited" if was_edited else "approved"
    entry.approved_at = datetime.utcnow().isoformat()

    store.update_entry(session_id, entry)

    # Redirect to next pending entry if available
    session = store.get(session_id)
    next_entry = next((e for e in session.entries if e.status == "pending"), None)
    if next_entry:
        return redirect(url_for("review.entry_view", session_id=session_id, entry_id=next_entry.id))
    return redirect(url_for("review.dashboard", session_id=session_id))


@bp.route("/review/<session_id>/entry/<entry_id>/skip", methods=["POST"])
def skip_entry(session_id: str, entry_id: str):
    entry = store.get_entry(session_id, entry_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404

    entry.status = "skipped"
    entry.reviewer_notes = request.form.get("reviewer_notes", "").strip()
    store.update_entry(session_id, entry)

    session = store.get(session_id)
    next_entry = next((e for e in session.entries if e.status == "pending"), None)
    if next_entry:
        return redirect(url_for("review.entry_view", session_id=session_id, entry_id=next_entry.id))
    return redirect(url_for("review.dashboard", session_id=session_id))


@bp.route("/review/<session_id>/status")
def session_status(session_id: str):
    session = store.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({
        "total": session.total,
        "reviewed": session.reviewed_count,
        "approved": session.approved_count,
        "skipped": session.skipped_count,
        "pending": session.pending_count,
        "is_complete": session.is_complete,
    })


@bp.route("/review/<session_id>/finalize", methods=["POST"])
def finalize(session_id: str):
    session = store.get(session_id)
    if not session:
        flash("Session not found.", "error")
        return redirect(url_for("review.upload_page"))

    approved = [e for e in session.entries if e.status in ("approved", "edited")]

    session.completed_at = datetime.utcnow().isoformat()

    return render_template(
        "complete.html",
        session=session,
        approved=approved,
    )
