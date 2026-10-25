"""Command line interface for collecting job offers."""

import argparse
from contextlib import ExitStack
from pathlib import Path

import structlog

from .application import collect_offers
from .domain import Offer
from .infra.justjoin import JustJoinHtmlSource
from .infra.nofluff import NoFluffHtmlSource
from .infra.storage import CsvStore, JsonlStore
from .log_setup import configure_logging

log = structlog.get_logger(__name__)


def main() -> int:
    """Collect new job offers into a persistent JSON Lines file."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Export job offers to JSON Lines")
    parser.add_argument("input", type=Path, help="CSV file with a 'url' column")
    parser.add_argument("output", type=Path, help="Persistent .jsonl path")
    args = parser.parse_args()
    try:
        urls = CsvStore.read_listings(args.input)
        store = JsonlStore(args.output, Offer)
        existing = store.read(missing_ok=True)
        with ExitStack() as resources:
            just_join_source = JustJoinHtmlSource()
            resources.callback(just_join_source.close)
            nofluff_source = NoFluffHtmlSource()
            resources.callback(nofluff_source.close)
            offers = collect_offers(
                urls,
                {"justjoin.it": just_join_source, "nofluffjobs.com": nofluff_source},
                existing,
                store.append,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        log.error("offer_collection_failed", error=str(exc))  # noqa: TRY400
        return 1
    log.info("offers_saved", count=len(offers), output=str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
