"""Domain model for offer assessments."""

from dataclasses import dataclass

from .model import Offer


@dataclass(frozen=True)
class Assessment:
    """Represents an assessment of a job offer based on a candidate's CV and a scoring rubric."""

    url: str
    title: str
    company: str | None
    location: str | None
    date_posted: str | None
    score: float
    confidence: float
    assessed_at: str
    cv_hash: str
    rubric_version: str

    @classmethod
    def for_offer(  # noqa: PLR0913, PLR0917 - six arguments are necessary for this use case
        cls,
        offer: Offer,
        score: float,
        confidence: float,
        assessed_at: str,
        cv_hash: str,
        rubric_version: str,
    ) -> "Assessment":
        """Create an assessment for a given offer with the provided score and confidence.

        Args:
            offer (Offer): The offer to be assessed.
            score (float): The match score for the offer.
            confidence (float): The confidence level of the score.
            assessed_at (str): The timestamp when the assessment was made.
            cv_hash (str): The hash of the candidate's CV used for the assessment.
            rubric_version (str): The version of the rubric used for scoring.

        Returns:
            Assessment: An instance of the Assessment class representing the assessment of the offer.

        """
        return cls(
            offer.url,
            offer.title,
            offer.company,
            offer.location,
            offer.date_posted,
            score,
            confidence,
            assessed_at,
            cv_hash,
            rubric_version,
        )
