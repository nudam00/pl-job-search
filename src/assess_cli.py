"""Command line interface for assessing job offers against a CV PDF."""

import argparse
import os
from pathlib import Path

import structlog

from .application import (
    LEVELS,
    FallbackMatchScorer,
    MatchScorer,
    assess_pending,
    pending_offers,
    shortlist_assessments,
)
from .domain import Assessment, Offer
from .infra.cv import PdfCvReader
from .infra.openai import (
    OpenAIDecisionsScorer,
    OpenAIHttpClient,
    OpenAIResponsesScorer,
)
from .infra.storage import CsvStore, JsonlStore
from .log_setup import configure_logging

log = structlog.get_logger(__name__)


def _create_scorer() -> MatchScorer:
    client = OpenAIHttpClient(os.environ["OPENAI_API_KEY"])
    return FallbackMatchScorer(
        OpenAIDecisionsScorer(client), OpenAIResponsesScorer(client)
    )


def main() -> int:
    """Assess job offers against a CV PDF and save the results to a JSONL file."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Score job offers against a CV PDF")
    parser.add_argument("offers", type=Path, help="Input offers JSONL")
    parser.add_argument("cv", type=Path, help="Local CV PDF")
    parser.add_argument("history", type=Path, help="All assessments JSONL")
    parser.add_argument("shortlist", type=Path, help="Selected offers CSV")
    parser.add_argument(
        "--threshold",
        type=float,
        default=2.0,
        help="Minimum score from 0 to 4 (default: 2.0)",
    )
    args = parser.parse_args()
    max_score = len(LEVELS) - 1
    if not 0 <= args.threshold <= max_score:
        parser.error(f"--threshold must be between 0 and {max_score}")
    try:
        offers = JsonlStore(args.offers, Offer).read()
        cv_hash, cv_text = PdfCvReader(args.cv).read()
        history_store = JsonlStore(args.history, Assessment)
        history = history_store.read(missing_ok=True)
        pending = pending_offers(offers, history, cv_hash)
        if pending and not os.environ.get("OPENAI_API_KEY"):
            log.error(
                "assessment_failed", error="Set OPENAI_API_KEY to assess new offers"
            )
            return 1
        completed, errors = (
            assess_pending(
                pending,
                cv_text,
                cv_hash,
                history,
                _create_scorer(),
                history_store.write,
            )
            if pending
            else (0, [])
        )
        for error in errors:
            log.error("assessment_failed", error=error)
        selected = CsvStore.write_shortlist(
            args.shortlist, shortlist_assessments(history, cv_hash, args.threshold)
        )
    except (OSError, ValueError) as exc:
        log.exception("assessment_failed", error=str(exc))
        return 1
    log.info(
        "assessment_finished",
        assessed=completed,
        shortlisted=selected,
        threshold=args.threshold,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
