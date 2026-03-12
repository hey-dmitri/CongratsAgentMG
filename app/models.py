from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import uuid


@dataclass
class Finisher:
    bib: str
    full_name: str
    first_name: str
    last_name: str
    city: str
    state: str
    age: int
    gender: str
    age_group: str
    finish_time: str
    overall_place: int
    gender_place: int
    age_group_place: int
    race_name: str
    race_date: str
    race_location: str


@dataclass
class HandleSuggestion:
    instagram_handle: str = ""
    instagram_url: str = ""
    facebook_name: str = ""
    facebook_url: str = ""
    confidence: str = "low"   # "high" | "medium" | "low"
    reasoning: str = ""


@dataclass
class PostCopy:
    instagram_text: str = ""   # ≤280 chars, emoji-forward, hashtags
    facebook_text: str = ""    # 2-3 sentences, fuller format


@dataclass
class ReviewEntry:
    id: str
    finisher: Finisher
    category: str
    place: int
    handle_suggestion: HandleSuggestion
    post_copy: PostCopy
    status: str = "pending"   # "pending" | "approved" | "edited" | "skipped"
    reviewer_notes: str = ""
    edited_instagram_text: str = ""
    edited_facebook_text: str = ""
    edited_instagram_handle: str = ""
    edited_facebook_url: str = ""
    approved_at: Optional[str] = None

    @classmethod
    def create(cls, finisher: Finisher, category: str, place: int,
               handle_suggestion: HandleSuggestion, post_copy: PostCopy) -> "ReviewEntry":
        return cls(
            id=str(uuid.uuid4()),
            finisher=finisher,
            category=category,
            place=place,
            handle_suggestion=handle_suggestion,
            post_copy=post_copy,
        )

    @property
    def final_instagram_text(self) -> str:
        return self.edited_instagram_text or self.post_copy.instagram_text

    @property
    def final_facebook_text(self) -> str:
        return self.edited_facebook_text or self.post_copy.facebook_text

    @property
    def final_instagram_handle(self) -> str:
        return self.edited_instagram_handle or self.handle_suggestion.instagram_handle

    @property
    def final_facebook_url(self) -> str:
        return self.edited_facebook_url or self.handle_suggestion.facebook_url


@dataclass
class ReviewSession:
    session_id: str
    race_name: str
    race_date: str
    entries: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    @classmethod
    def create(cls, race_name: str, race_date: str) -> "ReviewSession":
        return cls(
            session_id=str(uuid.uuid4()),
            race_name=race_name,
            race_date=race_date,
        )

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self.entries if e.status == "pending")

    @property
    def approved_count(self) -> int:
        return sum(1 for e in self.entries if e.status in ("approved", "edited"))

    @property
    def skipped_count(self) -> int:
        return sum(1 for e in self.entries if e.status == "skipped")

    @property
    def reviewed_count(self) -> int:
        return self.total - self.pending_count

    @property
    def is_complete(self) -> bool:
        return self.pending_count == 0
