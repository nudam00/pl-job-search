"""Application-level use case for assessing offers against a CV using a rubric."""

from collections.abc import Callable
from datetime import UTC, datetime

from src.domain import Assessment, Offer

from .ports import MatchScorer


def pending_offers(
    offers: list[Offer],
    assessments: list[Assessment],
    rubric_version: str,
) -> list[Offer]:
    """Return offers without an assessment for the given rubric version.

    Args:
        offers (list[Offer]): A list of offers to check for pending assessments.
        assessments (list[Assessment]): A list of existing assessments to compare against.
        rubric_version (str): The rubric and experience setting used to score.

    Returns:
        list[Offer]: Offers not yet assessed for the given rubric version, regardless of CV.

    """
    assessed = {a.url for a in assessments if a.rubric_version == rubric_version}
    pending = []
    for offer in offers:
        if offer.url not in assessed:
            pending.append(offer)
            assessed.add(offer.url)
    return pending


def shortlist_assessments(
    assessments: list[Assessment], threshold: float, rubric_version: str
) -> list[Assessment]:
    """Select the latest assessment per URL for the rubric, regardless of CV.

    Args:
        assessments (list[Assessment]): A list of existing assessments to filter and sort.
        threshold (float): The minimum score to include in the shortlist.
        rubric_version (str): The rubric and experience setting used to score.

    Returns:
        list[Assessment]: A sorted list of assessments that meet the criteria.

    """
    current = {
        assessment.url: assessment
        for assessment in assessments
        if assessment.rubric_version == rubric_version
    }
    return sorted(
        (
            assessment
            for assessment in current.values()
            if assessment.score >= threshold
        ),
        key=lambda assessment: (-assessment.score, assessment.url),
    )


def assess_pending(  # noqa: PLR0913, PLR0917 - arguments are necessary for this use case
    offers: list[Offer],
    cv_text: str,
    cv_hash: str,
    history: list[Assessment],
    scorer: MatchScorer,
    save: Callable[[list[Assessment]], None],
    rubric_version: str,
) -> tuple[int, list[str]]:
    """Assess the pending offers using the provided scorer and updates the assessment history.

    Args:
        offers (list[Offer]): A list of offers to assess.
        cv_text (str): The text of the CV to use for scoring.
        cv_hash (str): The hash of the CV to associate with the assessments.
        history (list[Assessment]): The current assessment history to update.
        scorer (MatchScorer): An instance of MatchScorer to score the offers.
        save (Callable[[list[Assessment]], None]): A callable to save the updated assessment history.
        rubric_version (str): The rubric and experience setting used to score.

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
                    rubric_version,
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
