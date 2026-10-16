"""Command line interface for collecting job offers."""

import argparse
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import structlog

from .application import collect_offers
from .domain import Offer
from .infra.justjoin import JustJoinHtmlSource
from .infra.storage import CsvStore, JsonlStore
from .log_setup import configure_logging

log = structlog.get_logger(__name__)


def main() -> int:
    """Collect job offers and save a dated JSON Lines snapshot."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Export job offers to JSON Lines")
    parser.add_argument("input", type=Path, help="CSV file with a 'url' column")
    parser.add_argument(
        "output", type=Path, help="Base .jsonl path; date added before suffix"
    )
    args = parser.parse_args()
    try:
        urls = CsvStore.read_listings(args.input)
        with ExitStack() as resources:
            source = JustJoinHtmlSource()
            resources.callback(source.close)
            offers = collect_offers(urls, {"justjoin.it": source})
        output = args.output.with_name(
            f"{args.output.stem}-{datetime.now(UTC).astimezone().date().isoformat()}{args.output.suffix}"
        )
        JsonlStore(output, Offer).write(offers)
    except (OSError, ValueError, RuntimeError) as exc:
        log.error("offer_collection_failed", error=str(exc))  # noqa: TRY400
        return 1
    log.info("offers_saved", count=len(offers), output=str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
