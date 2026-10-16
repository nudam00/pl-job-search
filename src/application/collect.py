"""Application-level use case for collecting offers from various sources."""

from collections.abc import Iterable, Mapping
from urllib.parse import urlparse

from src.domain import Offer

from .ports import OfferSource


def collect_offers(
    urls: Iterable[str], sources: Mapping[str, OfferSource]
) -> list[Offer]:
    """Collect offers with the source registered for each URL's hostname.

    Args:
        urls (Iterable[str]): An iterable of listing URLs to collect offers from.
        sources (Mapping[str, OfferSource]): Source adapters keyed by hostname.

    Returns:
        list[Offer]: A list of unique offers collected from the source.

    Raises:
        ValueError: If there are any issues with the URLs or the source during collection.

    """
    offers: dict[str, Offer] = {}
    for url in urls:
        source = sources.get(urlparse(url).hostname or "")
        if source is None:
            msg = f"No offer source for {url}"
            raise ValueError(msg)
        for offer in source.collect(url):
            offers.setdefault(offer.url, offer)
    return list(offers.values())
