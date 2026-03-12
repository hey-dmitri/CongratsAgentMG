import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch

from app.models import Finisher, HandleSuggestion, PostCopy
from app.ai.handle_finder import (
    find_handles,
    generate_post_copy,
    _extract_json,
    _claude_web_search_channel,
    _analyze_results,
)


# --- Helper ---

def make_finisher(**kwargs) -> Finisher:
    defaults = dict(
        bib="101",
        full_name="James Carter",
        first_name="James",
        last_name="Carter",
        city="Springfield",
        state="IL",
        age=28,
        gender="M",
        age_group="M25-29",
        finish_time="1:12:34",
        overall_place=1,
        gender_place=1,
        age_group_place=1,
        race_name="Springfield Half Marathon",
        race_date="2024-04-20",
        race_location="Springfield IL",
    )
    defaults.update(kwargs)
    return Finisher(**defaults)


SERPER_RESULTS = {
    "instagram": [{"url": "https://instagram.com/jamescarter_runs", "snippet": "James Carter — runner in Springfield"}],
    "facebook": [{"url": "https://facebook.com/james.carter.runner", "snippet": "James Carter — Springfield IL"}],
}

EMPTY_SERPER_RESULTS = {"instagram": [], "facebook": []}

CLAUDE_WEB_SEARCH_RESPONSE = """{
  "instagram_handle": "@jamescarter_runs",
  "instagram_url": "https://instagram.com/jamescarter_runs",
  "facebook_name": "James Carter",
  "facebook_url": "https://facebook.com/james.carter.runner",
  "notes": "Found running profile matching name and city."
}"""

VALID_ANALYSIS_RESPONSE = """{
  "instagram_handle": "@jamescarter_runs",
  "instagram_url": "https://instagram.com/jamescarter_runs",
  "facebook_name": "James Carter",
  "facebook_url": "https://facebook.com/james.carter.runner",
  "confidence": "high",
  "reasoning": "Both channels agree. Name matches, running content present, Springfield mentioned."
}"""

LOW_CONFIDENCE_ANALYSIS_RESPONSE = """{
  "instagram_handle": "",
  "instagram_url": "",
  "facebook_name": "",
  "facebook_url": "",
  "confidence": "low",
  "reasoning": "No matching profiles found in either channel."
}"""


# --- _extract_json tests ---

def test_extract_json_plain():
    assert _extract_json('{"key": "value"}') == {"key": "value"}

def test_extract_json_with_markdown_fence():
    assert _extract_json('```json\n{"key": "value"}\n```') == {"key": "value"}

def test_extract_json_with_bare_fence():
    assert _extract_json('```\n{"key": "value"}\n```') == {"key": "value"}

def test_extract_json_invalid_raises():
    with pytest.raises(Exception):
        _extract_json("not json at all")


# --- _claude_web_search_channel tests ---

def test_claude_web_search_channel_returns_dict(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.return_value = CLAUDE_WEB_SEARCH_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    result = _claude_web_search_channel(make_finisher())

    assert isinstance(result, dict)
    assert result["instagram_handle"] == "@jamescarter_runs"
    assert result["facebook_url"] == "https://facebook.com/james.carter.runner"


def test_claude_web_search_channel_returns_empty_on_failure(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.side_effect = RuntimeError("API down")
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    result = _claude_web_search_channel(make_finisher())

    assert result == {}


def test_claude_web_search_channel_returns_empty_on_bad_json(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.return_value = "Sorry, I cannot help with that."
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    result = _claude_web_search_channel(make_finisher())

    assert result == {}


# --- _analyze_results tests ---

def test_analyze_results_high_confidence_when_both_channels_agree(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.return_value = VALID_ANALYSIS_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    claude_data = {"instagram_handle": "@jamescarter_runs", "facebook_url": "https://facebook.com/james.carter.runner"}
    result = _analyze_results(make_finisher(), SERPER_RESULTS, claude_data)

    assert isinstance(result, HandleSuggestion)
    assert result.confidence == "high"
    assert result.instagram_handle == "@jamescarter_runs"


def test_analyze_results_low_confidence_when_nothing_found(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.return_value = LOW_CONFIDENCE_ANALYSIS_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    result = _analyze_results(make_finisher(), EMPTY_SERPER_RESULTS, {})

    assert isinstance(result, HandleSuggestion)
    assert result.confidence == "low"
    assert result.instagram_handle == ""


def test_analyze_results_fallback_on_api_error(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("API down")
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    result = _analyze_results(make_finisher(), SERPER_RESULTS, {})

    assert isinstance(result, HandleSuggestion)
    assert result.confidence == "low"
    assert "Analysis failed" in result.reasoning


# --- find_handles integration tests ---

def test_find_handles_returns_handle_suggestion(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.return_value = CLAUDE_WEB_SEARCH_RESPONSE
    mock_client.complete.return_value = VALID_ANALYSIS_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)
    monkeypatch.setattr("app.ai.handle_finder.search_runner", lambda **_: SERPER_RESULTS)

    result = find_handles(make_finisher())

    assert isinstance(result, HandleSuggestion)
    assert result.instagram_handle == "@jamescarter_runs"
    assert result.confidence == "high"
    assert result.reasoning != ""


def test_find_handles_still_works_when_channel2_fails(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.side_effect = RuntimeError("web search down")
    mock_client.complete.return_value = LOW_CONFIDENCE_ANALYSIS_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)
    monkeypatch.setattr("app.ai.handle_finder.search_runner", lambda **_: SERPER_RESULTS)

    result = find_handles(make_finisher())

    assert isinstance(result, HandleSuggestion)
    assert result.confidence == "low"


def test_find_handles_still_works_when_both_channels_fail(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.side_effect = RuntimeError("web search down")
    mock_client.complete.side_effect = RuntimeError("API down")
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)
    monkeypatch.setattr("app.ai.handle_finder.search_runner", lambda **_: EMPTY_SERPER_RESULTS)

    result = find_handles(make_finisher())

    assert isinstance(result, HandleSuggestion)
    assert result.confidence == "low"
    assert "failed" in result.reasoning.lower()


def test_find_handles_still_works_when_serper_fails(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete_with_web_search.return_value = CLAUDE_WEB_SEARCH_RESPONSE
    mock_client.complete.return_value = VALID_ANALYSIS_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)
    monkeypatch.setattr("app.ai.handle_finder.search_runner", lambda **_: EMPTY_SERPER_RESULTS)

    result = find_handles(make_finisher())

    assert isinstance(result, HandleSuggestion)
    assert result.instagram_handle == "@jamescarter_runs"


# --- generate_post_copy tests ---

VALID_COPY_RESPONSE = """{
  "instagram_text": "🏃 Congrats to @jamescarter_runs on winning the Springfield Half Marathon! ⏱ 1:12:34 #MarathonGuide #SpringfieldHalfMarathon #Running",
  "facebook_text": "Congratulations to James Carter from Springfield, IL on an incredible 1st place finish in the Overall Male category at the Springfield Half Marathon with a time of 1:12:34!"
}"""


def test_generate_post_copy_skipped_when_no_handles(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    handle = HandleSuggestion(confidence="low")  # no instagram or facebook
    result = generate_post_copy(make_finisher(), "Overall Male", 1, handle)

    assert isinstance(result, PostCopy)
    assert result.instagram_text == ""
    assert result.facebook_text == ""
    mock_client.complete.assert_not_called()


def test_generate_post_copy_only_instagram_when_only_ig_handle(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.return_value = '{"instagram_text": "🏃 Congrats @jamescarter_runs! #MarathonGuide #Running"}'
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    handle = HandleSuggestion(instagram_handle="@jamescarter_runs", confidence="medium")
    result = generate_post_copy(make_finisher(), "Overall Male", 1, handle)

    assert result.instagram_text != ""
    assert result.facebook_text == ""
    assert len(result.instagram_text) <= 280


def test_generate_post_copy_only_facebook_when_only_fb_handle(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.return_value = '{"facebook_text": "Congratulations to James Carter on a great race!"}'
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    handle = HandleSuggestion(facebook_name="James Carter", facebook_url="https://facebook.com/james.carter", confidence="medium")
    result = generate_post_copy(make_finisher(), "Overall Male", 1, handle)

    assert result.instagram_text == ""
    assert result.facebook_text != ""


def test_generate_post_copy_both_when_both_handles(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.return_value = VALID_COPY_RESPONSE
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    handle = HandleSuggestion(
        instagram_handle="@jamescarter_runs",
        facebook_name="James Carter",
        facebook_url="https://facebook.com/james.carter.runner",
        confidence="high",
    )
    result = generate_post_copy(make_finisher(), "Overall Male", 1, handle)

    assert isinstance(result, PostCopy)
    assert result.instagram_text != ""
    assert result.facebook_text != ""
    assert len(result.instagram_text) <= 280


def test_generate_post_copy_returns_empty_on_api_error(monkeypatch):
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("API down")
    monkeypatch.setattr("app.ai.handle_finder.get_client", lambda: mock_client)

    handle = HandleSuggestion(instagram_handle="@jamescarter_runs", confidence="medium")
    result = generate_post_copy(make_finisher(), "Overall Male", 1, handle)

    assert isinstance(result, PostCopy)
    assert result.instagram_text == ""
    assert result.facebook_text == ""
