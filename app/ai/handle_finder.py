from __future__ import annotations

import json
import re

from app.models import Finisher, HandleSuggestion, PostCopy
from app.ai.claude_client import get_client
from app.ai.web_searcher import search_runner, IG_PROFILE_RE, FB_PROFILE_RE, _is_profile_url

WEB_SEARCH_MODEL = "claude-sonnet-4-6"   # Channel 2: needs web search tool support
ANALYSIS_MODEL = "claude-haiku-4-5-20251001"  # Analysis: fast JSON reconciliation
COPY_MODEL = "claude-haiku-4-5-20251001"

CLAUDE_WEB_SEARCH_SYSTEM = """You are a social media research assistant helping find athlete profiles.
Search the web to find Instagram and Facebook profiles for the given runner.
Be honest about what you find — only report profiles you actually located.
Respond only with valid JSON."""

ANALYSIS_SYSTEM = """You are a social media research assistant reconciling search results to identify
the most likely social media profiles for a runner. Be honest about confidence —
'low' is better than a confident wrong answer. Respond only with valid JSON."""

COPY_SYSTEM = """You are a social media copywriter for MarathonGuide.com, a running event
directory. You write short, enthusiastic, emoji-forward posts congratulating race finishers.
You respond only with valid JSON."""


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    return json.loads(text)


def _claude_web_search_channel(finisher: Finisher) -> dict:
    """
    Channel 2: Use Claude with web_search_20250305 to find Instagram and Facebook handles.
    Returns a dict with instagram_handle, instagram_url, facebook_name, facebook_url, notes.
    Returns empty dict on failure.
    """
    prompt = f"""Search the web to find the Instagram and Facebook profiles for this marathon runner.

Runner details:
  Name: {finisher.full_name}
  City: {finisher.city}, {finisher.state}
  Race won: {finisher.race_name}

Search for their personal Instagram profile and their personal Facebook profile.

IMPORTANT: Only return profiles that belong to this individual athlete. Immediately disqualify:
  - Race or marathon organization pages (e.g. the official Wilmington Marathon page)
  - Running clubs, sports organizations, or brands
  - News articles, race result listings, or directory pages
  - Any page where the runner is merely mentioned, not the profile owner

A valid result must be a personal social media profile where this individual is the account owner.

Signals that confirm the right person:
  - Profile name or handle closely matches "{finisher.full_name}"
  - Profile mentions running, marathons, or races in a personal context
  - Location matches {finisher.city}, {finisher.state}

If you cannot find a personal profile with confidence, return empty strings.

Return ONLY this JSON:
{{
  "instagram_handle": "@username or empty string",
  "instagram_url": "full URL or empty string",
  "facebook_name": "display name as shown on profile or empty string",
  "facebook_url": "full URL or empty string",
  "notes": "brief description of what you found and how you identified this person"
}}"""

    try:
        print(f"  [channel 2] Claude web search for: {finisher.full_name}", flush=True)
        client = get_client()
        raw = client.complete_with_web_search(
            prompt,
            model=WEB_SEARCH_MODEL,
            max_tokens=512,
            system=CLAUDE_WEB_SEARCH_SYSTEM,
        )
        result = _extract_json(raw)
        print(
            f"  [channel 2] Found: IG={result.get('instagram_handle', '') or 'none'}, "
            f"FB={result.get('facebook_url', '') or 'none'}",
            flush=True,
        )
        return result
    except Exception as e:
        print(f"  [channel 2] Failed ({type(e).__name__}): {e}", flush=True)
        return {}


def _analyze_results(
    finisher: Finisher,
    serper_results: dict,
    claude_results: dict,
) -> HandleSuggestion:
    """
    Reconcile both channels and return the best HandleSuggestion.
    Makes a Claude call (no web search) to reason over the combined evidence.
    """
    def _format_serper_candidates(candidates: list[dict], platform: str) -> str:
        if not candidates:
            return f"No {platform} candidates found.\n"
        lines = [f"{platform} candidates:"]
        for i, c in enumerate(candidates, 1):
            lines.append(f"  [{i}] URL: {c['url']}")
            if c.get("snippet"):
                lines.append(f"      Snippet: {c['snippet']}")
        return "\n".join(lines) + "\n"

    serper_text = (
        _format_serper_candidates(serper_results.get("instagram", []), "Instagram")
        + "\n"
        + _format_serper_candidates(serper_results.get("facebook", []), "Facebook")
    )

    claude_text = (
        json.dumps(claude_results, indent=2)
        if claude_results
        else "No results from Claude web search channel."
    )

    prompt = f"""Analyze and reconcile these social media search results for a race winner.

Runner:
  Name: {finisher.full_name}
  City: {finisher.city}, {finisher.state}
  Age: {finisher.age} | Gender: {finisher.gender}
  Finish Time: {finisher.finish_time}
  Race: {finisher.race_name}

--- Channel 1: Google/Serper search results ---
{serper_text}
--- Channel 2: Claude web search results ---
{claude_text}

DISQUALIFY any candidate that is:
  - A race, marathon, or sporting event page (e.g. official race Facebook/Instagram)
  - A running club, organization, charity, or brand
  - A page where the runner is merely mentioned (race results, news articles, podium posts)
  - Any non-personal account

Only personal athlete profiles owned by "{finisher.full_name}" are valid.

Scoring — count how many signals match for each remaining candidate:
  Signal 1: Name match (profile name or handle closely matches "{finisher.full_name}")
  Signal 2: Running content (bio/posts mention running, marathon, race, miles, etc. in personal context)
  Signal 3: Location or race match ("{finisher.city}" or "{finisher.race_name}" appears)
  Bonus: Both channels agree on the same profile

Confidence rules:
  "high"   → 3 signals match, OR both channels agree with 2+ signals
  "medium" → 2 signals match
  "low"    → 1 signal matches, conflicting results, or common name with no disambiguation
  If nothing found (or everything was disqualified), return empty strings with confidence "low"

Return ONLY this JSON:
{{
  "instagram_handle": "@username or empty string",
  "instagram_url": "full URL or empty string",
  "facebook_name": "display name or empty string",
  "facebook_url": "full URL or empty string",
  "confidence": "high|medium|low",
  "reasoning": "which signals matched, which channels agreed, and why you accepted or rejected candidates"
}}"""

    try:
        print(f"  [analysis] Reconciling results for: {finisher.full_name}", flush=True)
        client = get_client()
        raw = client.complete(prompt, model=ANALYSIS_MODEL, max_tokens=600, system=ANALYSIS_SYSTEM)
        data = _extract_json(raw)

        # Validate URLs — reject anything that isn't a real profile URL
        ig_url = data.get("instagram_url", "")
        fb_url = data.get("facebook_url", "")
        if ig_url and not _is_profile_url(ig_url, IG_PROFILE_RE):
            print(f"  [analysis] Rejected bad Instagram URL: {ig_url}", flush=True)
            ig_url = ""
        if fb_url and not _is_profile_url(fb_url, FB_PROFILE_RE):
            print(f"  [analysis] Rejected bad Facebook URL: {fb_url}", flush=True)
            fb_url = ""

        return HandleSuggestion(
            instagram_handle=data.get("instagram_handle", ""),
            instagram_url=ig_url,
            facebook_name=data.get("facebook_name", ""),
            facebook_url=fb_url,
            confidence=data.get("confidence", "low"),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        return HandleSuggestion(
            confidence="low",
            reasoning=f"Analysis failed — please fill in manually. ({type(e).__name__}: {e})",
        )


def find_handles(finisher: Finisher) -> HandleSuggestion:
    """
    Two-channel handle lookup:
      Channel 1 — Serper.dev Google search (cached)
      Channel 2 — Claude with web_search_20250305 tool
    Results are reconciled by a separate Claude analysis call.
    Never raises — returns low-confidence empty suggestion on total failure.
    """
    print(f"\n[handle_finder] Looking up handles for: {finisher.full_name}", flush=True)

    # Channel 1: Serper Google search (uses cache)
    print(f"  [channel 1] Serper search...", flush=True)
    serper_results = search_runner(
        full_name=finisher.full_name,
        city=finisher.city,
        state=finisher.state,
    )
    print(
        f"  [channel 1] Found: {len(serper_results.get('instagram', []))} IG, "
        f"{len(serper_results.get('facebook', []))} FB candidates",
        flush=True,
    )

    # Channel 2: Claude with web search tool
    claude_results = _claude_web_search_channel(finisher)

    # Analysis: reconcile both channels
    return _analyze_results(finisher, serper_results, claude_results)


def generate_post_copy(finisher: Finisher, category: str, place: int,
                       handle_suggestion: HandleSuggestion) -> PostCopy:
    """
    Generate post copy only for platforms where a handle was found.
    If no handles were found, returns an empty PostCopy immediately.
    Never raises.
    """
    has_instagram = bool(handle_suggestion.instagram_handle)
    has_facebook = bool(handle_suggestion.facebook_url or handle_suggestion.facebook_name)

    if not has_instagram and not has_facebook:
        print(f"  No handles found for {finisher.full_name} — skipping post copy generation.", flush=True)
        return PostCopy()

    place_suffix = {1: "st", 2: "nd", 3: "rd"}.get(place, "th")
    race_hashtag = "#" + re.sub(r"[^a-zA-Z0-9]", "", finisher.race_name)

    platform_instructions = []
    json_fields = []

    if has_instagram:
        platform_instructions.append(
            f"Instagram requirements:\n"
            f"- Max 280 characters\n"
            f"- Emoji-forward and enthusiastic\n"
            f"- Include hashtags: #MarathonGuide {race_hashtag} #Running\n"
            f"- Tag the runner as {handle_suggestion.instagram_handle}"
        )
        json_fields.append('  "instagram_text": "post content here"')

    if has_facebook:
        fb_name = handle_suggestion.facebook_name or finisher.full_name
        platform_instructions.append(
            f"Facebook requirements:\n"
            f"- 2-3 sentences, friendly and celebratory\n"
            f"- Fuller format, slightly more formal than Instagram\n"
            f"- Mention the runner by name ({fb_name}) and their achievement"
        )
        json_fields.append('  "facebook_text": "post content here"')

    prompt = f"""Write congratulatory social media posts for this race finisher:

Runner: {finisher.full_name}
City: {finisher.city}, {finisher.state}
Category: {category}
Place: {place}{place_suffix}
Finish Time: {finisher.finish_time}
Race: {finisher.race_name} on {finisher.race_date}

{chr(10).join(platform_instructions)}

Return ONLY this JSON:
{{
{chr(10).join(json_fields)}
}}"""

    try:
        print(
            f"  Generating post copy for {finisher.full_name} "
            f"({'IG' if has_instagram else ''}{'+ FB' if has_instagram and has_facebook else 'FB' if has_facebook else ''}).",
            flush=True,
        )
        client = get_client()
        raw = client.complete(prompt, model=COPY_MODEL, max_tokens=512, system=COPY_SYSTEM)
        data = _extract_json(raw)
        return PostCopy(
            instagram_text=data.get("instagram_text", "") if has_instagram else "",
            facebook_text=data.get("facebook_text", "") if has_facebook else "",
        )
    except Exception as e:
        print(f"  Post copy generation failed for {finisher.full_name}: {e}", flush=True)
        return PostCopy()
