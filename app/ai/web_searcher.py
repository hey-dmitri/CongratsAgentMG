from __future__ import annotations

import re
import time
import requests
from app.config import Config
from app.ai.search_cache import get_cache

SERPER_URL = "https://google.serper.dev/search"
SERPER_TIMEOUT = 8  # seconds

# Instagram/Facebook profile URL patterns — exclude posts, reels, stories
IG_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?$"
)
FB_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?facebook\.com/([A-Za-z0-9._\-]+)/?$"
)
SOCIAL_NON_PROFILE = {"p", "reel", "tv", "stories", "explore", "accounts", "share"}


def _is_profile_url(url: str, pattern: re.Pattern) -> bool:
    m = pattern.match(url)
    if not m:
        return False
    username = m.group(1).lower()
    return username not in SOCIAL_NON_PROFILE and not username.startswith("_")


def _extract_social_candidates(results: list[dict]) -> dict[str, list[dict]]:
    instagram: list[dict] = []
    facebook: list[dict] = []
    seen: set[str] = set()

    for item in results:
        link = item.get("link", "").split("?")[0].rstrip("/")
        snippet = item.get("snippet", "")
        title = item.get("title", "")
        context = f"{title} — {snippet}"

        if "instagram.com" in link and _is_profile_url(link, IG_PROFILE_RE):
            if link not in seen:
                seen.add(link)
                instagram.append({"url": link, "snippet": context})

        elif "facebook.com" in link and _is_profile_url(link, FB_PROFILE_RE):
            if link not in seen:
                seen.add(link)
                facebook.append({"url": link, "snippet": context})

    return {"instagram": instagram[:3], "facebook": facebook[:3]}


def _serper_search(query: str, headers: dict) -> list[dict]:
    """
    Run a single Serper query. Checks cache first — only hits the API on a miss.
    Claude analysis is never cached; only raw Serper results are stored.
    """
    cache = get_cache()
    cached = cache.get(query)
    if cached is not None:
        print(f"    [cache hit] {query}", flush=True)
        return cached  # type: ignore

    print(f"    Serper: {query}", flush=True)
    try:
        resp = requests.post(
            SERPER_URL,
            headers=headers,
            json={"q": query, "num": 5},
            timeout=SERPER_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("organic", [])
        print(f"    → {len(hits)} results", flush=True)
        cache.set(query, hits)
        return hits
    except requests.exceptions.Timeout:
        print("    Serper timed out, skipping.", flush=True)
        return []
    except Exception as e:
        print(f"    Serper failed ({type(e).__name__}): {e}", flush=True)
        return []


def search_runner(
    full_name: str,
    city: str,
    state: str,
) -> dict[str, list[dict]]:
    """
    Fire 3 Serper searches and return candidate social profile URLs + snippets.
    Results are cached to data/search_cache.json — Claude analysis is always re-run.
    Returns {"instagram": [{"url", "snippet"}], "facebook": [...]}
    """
    if not Config.SERPER_API_KEY:
        print("    SERPER_API_KEY not set — skipping web search.", flush=True)
        return {"instagram": [], "facebook": []}

    headers = {
        "X-API-KEY": Config.SERPER_API_KEY,
        "Content-Type": "application/json",
    }

    queries = [
        f'"{full_name}" instagram runner {city} {state}',
        f'"{full_name}" facebook runner {city} {state}',
        f'"{full_name}" runner marathon',
    ]

    all_results: list[dict] = []
    cache = get_cache()
    for i, query in enumerate(queries):
        was_cached = cache.get(query) is not None
        hits = _serper_search(query, headers)
        all_results.extend(hits)
        # 2-second delay between live API calls only (skip if result came from cache)
        if not was_cached and i < len(queries) - 1:
            time.sleep(2)

    candidates = _extract_social_candidates(all_results)
    print(
        f"    Candidates: {len(candidates['instagram'])} Instagram, "
        f"{len(candidates['facebook'])} Facebook",
        flush=True,
    )
    return candidates
