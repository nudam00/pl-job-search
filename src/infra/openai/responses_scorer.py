"""Score CVs against job offers using OpenAI responses."""

import json
from typing import Any

from src.application.rubric import LEVELS, scoring_instructions
from src.domain import Offer

from .http_client import REQUEST_TIMEOUT_SECONDS, OpenAIHttpClient, OpenAIHttpError

MODEL_NAME = "gpt-5.6-luna"


class OpenAIResponsesScorer:
    """Scorer for evaluating CVs against job offers using OpenAI responses."""

    def __init__(
        self, client: OpenAIHttpClient, max_required_years: int | None = None
    ) -> None:
        """Initialize the OpenAIResponsesScorer with an OpenAI HTTP client.

        Args:
            client (OpenAIHttpClient): An instance of OpenAIHttpClient for making API requests.
            max_required_years (int | None): Maximum required experience in years, if set.

        """
        self.client = client
        self.max_required_years = max_required_years

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
        try:
            data = self.client.post(
                "/v1/responses",
                self._payload(cv_text, offer),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            content = next(
                item["text"]
                for output in data["output"]
                if output["type"] == "message"
                for item in output["content"]
                if item["type"] == "output_text"
            )
            answer = json.loads(content)
            score, confidence = float(answer["score"]), float(answer["confidence"])
            if not (0 <= score <= len(LEVELS) - 1 and 0 <= confidence <= 1):
                msg = "Score or confidence outside expected range"
                raise ValueError(msg)
        except OpenAIHttpError as exc:
            msg = f"Responses API {exc} for {offer.url}"
            raise RuntimeError(msg) from exc
        except (KeyError, StopIteration, TypeError, json.JSONDecodeError) as exc:
            msg = f"Invalid Responses API response for {offer.url}"
            raise ValueError(msg) from exc
        return score, confidence

    def _payload(self, cv_text: str, offer: Offer) -> dict[str, Any]:
        return {
            "model": MODEL_NAME,
            "reasoning": {"effort": "low"},
            "store": False,
            "input": [
                {
                    "role": "system",
                    "content": scoring_instructions(self.max_required_years)
                    + " Return a score from 0 to 4 using these levels: "
                    + json.dumps(LEVELS, ensure_ascii=False)
                    + ". A fractional score is allowed. Return confidence from 0 to 1 for how well the available evidence supports the score.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "cv": cv_text,
                            "offer_title": offer.title,
                            "offer_description": offer.description,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "offer_match",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "number"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["score", "confidence"],
                        "additionalProperties": False,
                    },
                }
            },
        }
