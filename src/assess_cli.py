"""Command line interface for assessing job offers against a CV PDF."""

import argparse
import json
import os
from pathlib import Path
from typing import TypedDict, cast

import structlog

from .application import (
    LEVELS,
    RUBRIC_VERSION,
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


class Exclusions(TypedDict):
    """Structure of the exclusions JSON file."""

    exclude_title_keywords: list[str]
    exclude_offer_urls: list[str]
    exclude_company_keywords: list[str]


def _create_scorer(max_required_years: int | None) -> MatchScorer:
    client = OpenAIHttpClient(os.environ["OPENAI_API_KEY"])
    return FallbackMatchScorer(
        OpenAIDecisionsScorer(client, max_required_years),
        OpenAIResponsesScorer(client, max_required_years),
    )


def _read_exclusions(path: Path) -> Exclusions:
    exclusions = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "exclude_title_keywords",
        "exclude_offer_urls",
        "exclude_company_keywords",
    }
    if (
        not isinstance(exclusions, dict)
        or set(exclusions) != required
        or any(
            not isinstance(exclusions[key], list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in exclusions[key]
            )
            for key in exclusions
        )
    ):
        msg = "Exclusions must contain exclude_title_keywords, exclude_offer_urls, and exclude_company_keywords lists of nonempty strings"
        raise ValueError(msg)
    return cast("Exclusions", exclusions)


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
    parser.add_argument("--exclusions", type=Path, help="Exclusions JSON file")
    parser.add_argument(
        "--max-required-years",
        type=int,
        default=5,
        help="Score clear requirements above this many years as No fit (default: 5)",
    )
    args = parser.parse_args()
    max_score = len(LEVELS) - 1
    if not 0 <= args.threshold <= max_score:
        parser.error(f"--threshold must be between 0 and {max_score}")
    if args.max_required_years < 0:
        parser.error("--max-required-years must be nonnegative")
    rubric_version = f"{RUBRIC_VERSION}:max-required-years={args.max_required_years}"
    try:
        exclusions: Exclusions = (
            _read_exclusions(args.exclusions)
            if args.exclusions
            else {
                "exclude_title_keywords": [],
                "exclude_offer_urls": [],
                "exclude_company_keywords": [],
            }
        )
        offers = JsonlStore(args.offers, Offer).read()
        excluded_urls = set(exclusions["exclude_offer_urls"]) | {
            offer.url
            for offer in offers
            if any(
                keyword.casefold() in offer.title.casefold()
                for keyword in exclusions["exclude_title_keywords"]
            )
            or any(
                keyword.casefold() in (offer.company or "").casefold()
                for keyword in exclusions["exclude_company_keywords"]
            )
        }
        cv_hash, cv_text = PdfCvReader(args.cv).read()
        history_store = JsonlStore(args.history, Assessment)
        history = history_store.read(missing_ok=True)
        pending = pending_offers(
            [offer for offer in offers if offer.url not in excluded_urls],
            history,
            cv_hash,
            rubric_version,
        )
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
                _create_scorer(args.max_required_years),
                history_store.write,
                rubric_version,
            )
            if pending
            else (0, [])
        )
        for error in errors:
            log.error("assessment_failed", error=error)
        selected = CsvStore.write_shortlist(
            args.shortlist,
            [
                assessment
                for assessment in shortlist_assessments(
                    history, cv_hash, args.threshold, rubric_version
                )
                if assessment.url not in excluded_urls
            ],
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
