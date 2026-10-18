"""Score CVs against job offers using OpenAI Decisions API."""

import json
import random
import time
from http import HTTPStatus
from typing import Any

import structlog

from src.application.ports import ScorerUnavailableError
from src.application.rubric import LEVELS, scoring_instructions
from src.domain import Offer

from .http_client import REQUEST_TIMEOUT_SECONDS, OpenAIHttpClient, OpenAIHttpError

RETRY_BUDGET_SECONDS = 180
MAX_ATTEMPTS = 5
MIN_REQUEST_INTERVAL_SECONDS = 2
NON_RETRYABLE_429 = {
    "credit_balance_exhausted",
    "insufficient_quota",
    "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
}
MODEL_NAME = "gpt-6-luna"
log = structlog.get_logger(__name__)


class DecisionRateLimitError(ScorerUnavailableError):
    """A Decisions rate limit cannot be retried within this run."""


class OpenAIDecisionsScorer:
    """Scorer for evaluating CVs against job offers using OpenAI Decisions API."""

    def __init__(
        self, client: OpenAIHttpClient, max_required_years: int | None = None
    ) -> None:
        """Initialize the OpenAIDecisionsScorer with an OpenAI HTTP client.

        Args:
            client (OpenAIHttpClient): The HTTP client for interacting with the OpenAI API.
            max_required_years (int | None): Maximum required experience in years, if set.

        """
        self.client = client
        self.max_required_years = max_required_years
        self._last_request = 0.0

    def score(self, cv_text: str, offer: Offer) -> tuple[float, float]:
        """Return the match score and confidence for an offer.

        Args:
            cv_text (str): The text of the candidate's CV.
            offer (Offer): The offer to score against the CV.

        Returns:
            tuple[float, float]: A tuple containing the match score and confidence.

        Raises:
            RuntimeError: If there is an error with the API request.
            ValueError: If the response is invalid or the score or confidence is out of range.

        """
        data = self._request(self._payload(cv_text, offer), offer)
        try:
            answer = next(a for a in data["answers"] if a["name"] == "match")
            if answer["type"] != "score":
                msg = f"Decisions API returned {answer['type']} for {offer.url}"
                raise ValueError(msg)
            score = float(answer["score"])
            confidence = float(answer["confidence"])
            if not (0 <= score <= len(LEVELS) - 1 and 0 <= confidence <= 1):
                msg = "Score or confidence outside expected range"
                raise ValueError(msg)
        except (KeyError, StopIteration, TypeError) as exc:
            msg = f"Invalid Decisions API response for {offer.url}"
            raise ValueError(msg) from exc
        return score, confidence

    def _payload(self, cv_text: str, offer: Offer) -> dict[str, Any]:
        return {
            "model": MODEL_NAME,
            "input": json.dumps(
                {
                    "cv": cv_text,
                    "offer_title": offer.title,
                    "offer_description": offer.description,
                },
                ensure_ascii=False,
            ),
            "questions": [
                {
                    "type": "score",
                    "name": "match",
                    "instructions": scoring_instructions(self.max_required_years),
                    "levels": LEVELS,
                }
            ],
        }

    def _request(self, payload: dict[str, Any], offer: Offer) -> dict[str, Any]:
        deadline = time.monotonic() + RETRY_BUDGET_SECONDS
        for attempt in range(MAX_ATTEMPTS):
            self._wait_for_interval()
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    msg = f"Decisions API retry budget exhausted for {offer.url}"
                    raise RuntimeError(msg)
                return self.client.post(
                    "/v1/decisions",
                    payload,
                    timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
                )
            except OpenAIHttpError as exc:
                detail = f"Decisions API {exc} for {offer.url}"
                if (
                    exc.status
                    not in (
                        HTTPStatus.TOO_MANY_REQUESTS,
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    or exc.code in NON_RETRYABLE_429
                    or exc.error_type == "insufficient_quota"
                ):
                    raise RuntimeError(detail) from exc
                rate_limit = (
                    exc.status == HTTPStatus.TOO_MANY_REQUESTS
                    and exc.code == "rate_limit_exceeded"
                )
                if attempt == MAX_ATTEMPTS - 1:
                    msg = f"{detail}; retries exhausted"
                    if rate_limit:
                        raise DecisionRateLimitError(msg) from exc
                    raise RuntimeError(msg) from exc
                delay = self._retry_delay(exc, attempt)
                if delay >= deadline - time.monotonic():
                    msg = f"{detail}; Retry-After exceeds retry budget"
                    if rate_limit:
                        raise DecisionRateLimitError(msg) from exc
                    raise RuntimeError(msg) from exc
                log.warning(
                    "decision_request_retrying",
                    error=detail,
                    delay_seconds=round(delay, 1),
                )
                time.sleep(delay)
            finally:
                self._last_request = time.monotonic()
        msg = f"Decisions API retries exhausted for {offer.url}"
        raise RuntimeError(msg)

    def _wait_for_interval(self) -> None:
        pause = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
        if pause > 0:
            time.sleep(pause)

    @staticmethod
    def _retry_delay(error: OpenAIHttpError, attempt: int) -> float:
        jitter = random.uniform(0, 1)  # noqa: S311  # nosec B311
        try:
            if error.retry_after is not None:
                return max(0.0, float(error.retry_after)) + jitter
        except ValueError:
            pass
        return float(min(2 ** (attempt + 1), 60)) + jitter
