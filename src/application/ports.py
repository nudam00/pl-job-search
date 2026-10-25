"""Application-level protocols for handling offer assessment and collection."""

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from src.domain import Offer


class ScorerUnavailableError(RuntimeError):
    """Raised when the scorer is unavailable due to an error with the API request."""


@runtime_checkable
class OfferSource(Protocol):
    """Collect offers from a listing."""

    def collect(self, listing_url: str, known_urls: set[str]) -> Iterable[Offer]:
        """Return offers from the given listing URL.

        Args:
            listing_url (str): The URL of the listing to collect offers from.
            known_urls (set[str]): Offer URLs already saved or collected.

        Returns:
            Iterable[Offer]: An iterable of offers collected from the listing URL.

        Raises:
            ValueError: If there is a pagination loop or unexpected URL format.

        """
        ...


@runtime_checkable
class MatchScorer(Protocol):
    """Score an offer against a candidate's CV."""

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
        ...
