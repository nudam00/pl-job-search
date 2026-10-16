"""Collects offers from Just Join IT listing and detail pages."""

import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from src.domain import Offer

from .json_ld_parser import JsonLdParser


class JustJoinHtmlSource:
    """Collects offers from JSON-LD on Just Join IT listing and detail pages."""

    def __init__(self, delay_seconds: float = 0.5) -> None:
        """Initialize the JustJoinHtmlSource with an optional delay between requests.

        Args:
            delay_seconds (float): The number of seconds to wait between requests. Default is 0.5 seconds.

        """
        self.delay_seconds = delay_seconds
        self._last_request = 0.0
        self.client = httpx.Client(
            headers={"User-Agent": "role-radar/0.1", "Accept-Language": "en"},
            timeout=20,
            follow_redirects=False,
        )

    def close(self) -> None:
        """Close the shared HTTP connection pool."""
        self.client.close()

    def collect(self, listing_url: str) -> list[Offer]:
        """Return offers from the given listing URL.

        Args:
            listing_url (str): The URL of the listing to collect offers from.

        Returns:
            list[Offer]: A list of offers collected from the listing URL.

        Raises:
            ValueError: If there is a pagination loop or unexpected URL format.

        """
        parsed = urlparse(listing_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "justjoin.it"
            or not parsed.path.startswith("/job-offers/")
        ):
            msg = f"Not a Just Join IT listing URL: {listing_url}"
            raise ValueError(msg)
        offers: list[Offer] = []
        seen_pages: set[str] = set()
        seen_offers: set[str] = set()
        page_url: str | None = listing_url
        while page_url:
            if page_url in seen_pages:
                msg = f"Pagination loop at {page_url}"
                raise ValueError(msg)
            seen_pages.add(page_url)
            items, next_url = self._listing(page_url)
            for item in items:
                if item["url"] not in seen_offers:
                    offers.append(self._offer(item, page_url))
                    seen_offers.add(item["url"])
            if next_url:
                parsed = urlparse(next_url)
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != "justjoin.it"
                    or parsed.path != urlparse(listing_url).path
                ):
                    msg = f"Unexpected next page URL: {next_url}"
                    raise ValueError(msg)
            page_url = next_url
        return offers

    def _listing(self, url: str) -> tuple[list[dict[str, Any]], str | None]:
        parser = JsonLdParser()
        parser.feed(self._get(url))
        items = next(
            (
                doc["mainEntity"]["itemListElement"]
                for doc in parser.documents
                if isinstance(doc.get("mainEntity"), dict)
                and doc["mainEntity"].get("@type") == "ItemList"
            ),
            None,
        )
        if items is None:
            msg = f"No ItemList JSON-LD found at {url}"
            raise ValueError(msg)
        return items, urljoin(url, parser.next_url) if parser.next_url else None

    def _offer(self, item: dict[str, Any], source_url: str) -> Offer:
        url = item["url"]
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "justjoin.it"
            or not parsed.path.startswith("/job-offer/")
        ):
            msg = f"Unexpected offer URL: {url}"
            raise ValueError(msg)
        parser = JsonLdParser()
        parser.feed(self._get(url))
        posting = next(
            (doc for doc in parser.documents if doc.get("@type") == "JobPosting"), None
        )
        if posting is None:
            msg = f"No JobPosting JSON-LD found at {url}"
            raise ValueError(msg)
        organization = posting.get("hiringOrganization") or {}
        place = posting.get("jobLocation") or {}
        if isinstance(place, list):
            place = place[0] if place else {}
        address = place.get("address") or {}
        return Offer(
            url=url,
            title=posting.get("title") or item.get("name") or "",
            company=organization.get("name"),
            location=address.get("addressLocality"),
            date_posted=posting.get("datePosted"),
            valid_through=posting.get("validThrough"),
            employment_type=posting.get("employmentType"),
            description=posting.get("description"),
            salary=posting.get("baseSalary"),
            source_url=source_url,
        )

    def _get(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "justjoin.it":
            msg = f"Unexpected fetch URL: {url}"
            raise ValueError(msg)
        remaining = self.delay_seconds - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"Cannot fetch {url}: {exc}"
            raise RuntimeError(msg) from exc
        else:
            return response.text
        finally:
            self._last_request = time.monotonic()
