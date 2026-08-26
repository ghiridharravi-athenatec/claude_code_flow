"""Exception types for LLM-judged scoring (SPEC.md Section 6.3)."""

from __future__ import annotations


class LLMJudgingError(Exception):
    """Base class for every error raised while getting a Claude-judged score."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidApiKeyError(LLMJudgingError):
    """Raised when the Claude API rejects the supplied Anthropic API key."""

    def __init__(self, message: str = "The supplied Claude API key was rejected.") -> None:
        super().__init__(message)


class LLMServiceError(LLMJudgingError):
    """Raised for any other Claude API failure (network, rate limit, malformed response)."""

    def __init__(self, message: str = "The Claude API call failed.") -> None:
        super().__init__(message)
