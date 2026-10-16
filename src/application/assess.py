"""Application-level use case for assessing offers against a CV using a rubric."""

from collections.abc import Callable
from datetime import UTC, datetime

from src.domain import Assessment, Offer

from .ports import MatchScorer
from .rubric import RUBRIC_VERSION


def pending_offers(
    offers: list[Offer], assessments: list[Assessment], cv_hash: str
) -> list[Offer]:
    """Return the subset of offers that have not yet been assessed for the given CV hash and rubric version.

    Args:
        offers (list[Offer]): A list of offers to check for pending assessments.
        assessments (list[Assessment]): A list of existing assessments to compare against.
        cv_hash (str): The hash of the CV to filter assessments by.

    Returns:
        list[Offer]: A list of offers that have not yet been assessed for the given CV hash and rubric version.

    """
    assessed = {
        a.url
        for a in assessments
        if a.cv_hash == cv_hash and a.rubric_version == RUBRIC_VERSION
    }
    pending = []
    for offer in offers:
        if offer.url not in assessed:
            pending.append(offer)
            assessed.add(offer.url)
    return pending


def shortlist_assessments(
    assessments: list[Assessment], cv_hash: str, threshold: float
) -> list[Assessment]:
    """Select the latest assessment per URL for this CV and rubric, above the threshold.

    Args:
        assessments (list[Assessment]): A list of existing assessments to filter and sort.
        cv_hash (str): The hash of the CV to filter assessments by.
        threshold (float): The minimum score to include in the shortlist.

    Returns:
        list[Assessment]: A sorted list of assessments that meet the criteria.

    """
    current = {
        assessment.url: assessment
        for assessment in assessments
        if assessment.cv_hash == cv_hash and assessment.rubric_version == RUBRIC_VERSION
    }
    return sorted(
        (
            assessment
            for assessment in current.values()
            if assessment.score >= threshold
        ),
        key=lambda assessment: (-assessment.score, assessment.url),
    )


def assess_pending(  # noqa: PLR0913, PLR0917 - six arguments are necessary for this use case
    offers: list[Offer],
    cv_text: str,
    cv_hash: str,
    history: list[Assessment],
    scorer: MatchScorer,
    save: Callable[[list[Assessment]], None],
) -> tuple[int, list[str]]:
    """Assess the pending offers using the provided scorer and updates the assessment history.

    Args:
        offers (list[Offer]): A list of offers to assess.
        cv_text (str): The text of the CV to use for scoring.
        cv_hash (str): The hash of the CV to associate with the assessments.
        history (list[Assessment]): The current assessment history to update.
        scorer (MatchScorer): An instance of MatchScorer to score the offers.
        save (Callable[[list[Assessment]], None]): A callable to save the updated assessment history.

    Returns:
        tuple[int, list[str]]: Completed count and error messages.

    Raises:
        RuntimeError: If there is a runtime error during the scoring process.
        ValueError: If there is a value error during the scoring process.

    """
    completed = 0
    errors = []
    for offer in offers:
        try:
            score, confidence = scorer.score(cv_text, offer)
            history.append(
                Assessment.for_offer(
                    offer,
                    score,
                    confidence,
                    datetime.now(UTC).isoformat(),
                    cv_hash,
                    RUBRIC_VERSION,
                )
            )
            save(history)
            completed += 1
        except RuntimeError as exc:
            errors.append(str(exc))
            break
        except ValueError as exc:
            errors.append(str(exc))
    return completed, errors
