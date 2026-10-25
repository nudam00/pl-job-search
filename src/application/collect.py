"""Application-level use case for collecting offers from various sources."""

from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urlparse

from src.domain import Offer

from .ports import OfferSource


def collect_offers(
    urls: Iterable[str],
    sources: Mapping[str, OfferSource],
    existing: Iterable[Offer] = (),
    save: Callable[[Offer], None] | None = None,
) -> list[Offer]:
    """Collect offers with the source registered for each URL's hostname.

    Args:
        urls (Iterable[str]): An iterable of listing URLs to collect offers from.
        sources (Mapping[str, OfferSource]): Source adapters keyed by hostname.
        existing (Iterable[Offer]): Saved offers to retain and skip while collecting.
        save (Callable[[Offer], None] | None): Persist each newly collected offer.

    Returns:
        list[Offer]: A list of unique offers collected from the source.

    Raises:
        ValueError: If there are any issues with the URLs or the source during collection.

    """
    offers = {offer.url: offer for offer in existing}
    for url in urls:
        source = sources.get(urlparse(url).hostname or "")
        if source is None:
            msg = f"No offer source for {url}"
            raise ValueError(msg)
        for offer in source.collect(url, set(offers)):
            if offer.url not in offers:
                if save is not None:
                    save(offer)
                offers[offer.url] = offer
    return list(offers.values())
