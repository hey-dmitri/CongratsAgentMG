from __future__ import annotations

import time
from typing import Optional
import anthropic
from app.config import Config


class ClaudeClient:
    """Thin wrapper around the Anthropic SDK with basic retry logic."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def complete(
        self,
        prompt: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1024,
        system: str = "",
    ) -> str:
        """
        Send a prompt and return the text response.
        Retries up to MAX_RETRIES times on transient errors.
        Raises on permanent failure.
        """
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self._client.messages.create(**kwargs)
                return response.content[0].text
            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * attempt)
            except anthropic.APIStatusError as e:
                # 5xx errors are retryable; 4xx are not
                if e.status_code >= 500 and attempt < self.MAX_RETRIES:
                    last_error = e
                    time.sleep(self.RETRY_DELAY * attempt)
                else:
                    raise
            except anthropic.APIConnectionError as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * attempt)

        raise RuntimeError(
            f"Claude API failed after {self.MAX_RETRIES} attempts: {last_error}"
        )

    def complete_with_web_search(
        self,
        prompt: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 1024,
        system: str = "",
    ) -> str:
        """
        Send a prompt with the web_search_20250305 tool enabled.
        Claude autonomously searches the web and returns a text response.
        Retries up to MAX_RETRIES times on transient errors.
        """
        tools = [{"type": "web_search_20250305", "name": "web_search"}]
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "tools": tools,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self._client.beta.messages.create(
                    betas=["web-search-2025-03-05"],
                    **kwargs,
                )
                # Claude returns multiple text blocks: intermediate reasoning + final answer.
                # Only the last text block contains the final response we want.
                text_blocks = [
                    block.text
                    for block in response.content
                    if hasattr(block, "text") and block.text
                ]
                return text_blocks[-1] if text_blocks else ""
            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * attempt)
            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < self.MAX_RETRIES:
                    last_error = e
                    time.sleep(self.RETRY_DELAY * attempt)
                else:
                    raise
            except anthropic.APIConnectionError as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * attempt)

        raise RuntimeError(
            f"Claude web search failed after {self.MAX_RETRIES} attempts: {last_error}"
        )


# Singleton
_client: Optional[ClaudeClient] = None


def get_client() -> ClaudeClient:
    global _client
    if _client is None:
        _client = ClaudeClient()
    return _client
