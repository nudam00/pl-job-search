"""Fallback scoring across providers."""

import structlog

from src.domain import Offer

from .ports import MatchScorer, ScorerUnavailableError

log = structlog.get_logger(__name__)


class FallbackMatchScorer:
    """Use a secondary scorer after the primary becomes unavailable."""

    def __init__(self, primary: MatchScorer, fallback: MatchScorer) -> None:
        """Store the primary and fallback scorers.

        Args:
            primary (MatchScorer): The primary scorer to use until it becomes unavailable.
            fallback (MatchScorer): The fallback scorer to use when the primary is unavailable.

        """
        self.primary = primary
        self.fallback = fallback
        self._using_fallback = False

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
        if self._using_fallback:
            return self.fallback.score(cv_text, offer)
        try:
            return self.primary.score(cv_text, offer)
        except ScorerUnavailableError as exc:
            self._using_fallback = True
            log.warning("switching_to_fallback_scorer", reason=str(exc))
            return self.fallback.score(cv_text, offer)
