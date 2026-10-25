"""Collect offers from No Fluff Jobs listing and detail pages."""

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

import httpx
import structlog

from src.domain import Offer

from .state_parser import StateParser, TextParser

log = structlog.get_logger(__name__)
HTTP_TOO_MANY_REQUESTS = 429
MAX_RATE_LIMIT_RETRIES = 5
MAX_RETRY_WAIT_SECONDS = 300
MAX_REQUEST_DELAY_SECONDS = 30


class NoFluffHtmlSource:
    """Collects offers from No Fluff Jobs listing and detail pages."""

    def __init__(self, delay_seconds: float = 2.0) -> None:
        """Initialize the NoFluffHtmlSource with an optional delay between requests.

        Args:
            delay_seconds (float): The number of seconds to wait between requests. Default is 2 seconds.

        """
        self.delay_seconds = delay_seconds
        self._last_request = 0.0
        self.client = httpx.Client(
            headers={"User-Agent": "pl-job-search/0.1", "Accept-Language": "pl"},
            timeout=20,
            follow_redirects=False,
        )

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self.client.close()

    def collect(
        self, listing_url: str, known_urls: set[str] | None = None
    ) -> Iterator[Offer]:
        """Return offers from the given listing URL.

        Args:
            listing_url (str): The URL of the listing to collect offers from.
            known_urls (set[str]): Offer URLs already saved or collected.

        Returns:
            Iterable[Offer]: An iterable of offers collected from the listing URL.

        Raises:
            ValueError: If there is a pagination loop or unexpected URL format.
            RuntimeError: If the listing is incomplete or cannot be fetched.

        """
        listing = self._listing(listing_url)
        use_api = listing["exactMatchesPages"] > 1
        if use_api:
            search = {
                "rawSearch": listing.get("rawSearch", ""),
                "criteriaSearch": listing.get("criteriaSearch", {}),
            }
            sort = dict(parse_qsl(urlparse(listing_url).query)).get("sort")
            listing = self._search_page(search, 1, sort=sort, limit=listing["divs"])
        postings = self._postings(listing, use_api=use_api)
        expected = listing.get("divs")
        if expected is not None and len(postings) != expected:
            msg = (
                f"Incomplete No Fluff Jobs listing: found {len(postings)} "
                f"unique offers, expected {expected} at {listing_url}"
            )
            raise RuntimeError(msg)
        seen_offers = set(known_urls or ())
        for posting in postings:
            slug = posting.get("url") or posting["location"]["places"][0]["url"]
            url = urljoin(listing_url, f"/pl/job/{slug}")
            if url not in seen_offers:
                offer = self._offer(url, listing_url)
                seen_offers.add(url)
                yield offer

    def _listing(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "nofluffjobs.com"
            or not parsed.path.startswith("/pl/")
            or parsed.path.startswith("/pl/job/")
        ):
            msg = f"Not a No Fluff Jobs listing URL: {url}"
            raise ValueError(msg)
        parser = StateParser()
        parser.feed(self._get(url))
        listing = next(
            (
                value
                for value in parser.state.values()
                if isinstance(value, dict)
                and "exactMatchesPages" in value
                and "postings" in value
            ),
            None,
        )
        if listing is None:
            msg = f"No listing data found at {url}"
            raise ValueError(msg)
        return listing

    def _search_page(
        self,
        search: dict[str, Any],
        page: int,
        *,
        sort: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return json.loads(
            self._get(
                "https://nofluffjobs.com/api/search/posting",
                search=search,
                page=page,
                sort=sort,
                limit=limit,
            )
        )

    def _postings(
        self, listing: dict[str, Any], *, use_api: bool
    ) -> list[dict[str, Any]]:
        postings: list[dict[str, Any]] = listing["postings"]
        if not use_api:
            return postings if listing["exactMatchesPages"] else []
        unique: dict[str, dict[str, Any]] = {}
        for posting in postings:
            unique.setdefault(posting.get("reference") or posting["id"], posting)
        return list(unique.values())

    def _offer(self, url: str, source_url: str) -> Offer:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "nofluffjobs.com"
            or not parsed.path.startswith("/pl/job/")
        ):
            msg = f"Unexpected offer URL: {url}"
            raise ValueError(msg)
        parser = StateParser()
        parser.feed(self._get(url))
        posting = next(
            (
                value
                for key, value in parser.state.items()
                if isinstance(value, dict)
                and (
                    key.startswith("/posting/")
                    or value.get("postingUrl") == parsed.path.removeprefix("/pl/job/")
                )
            ),
            None,
        )
        if posting is None:
            msg = f"No posting data found at {url}"
            raise ValueError(msg)
        requirements = posting.get("requirements") or {}
        description_html = "\n".join(
            part
            for part in (
                requirements.get("description"),
                (posting.get("details") or {}).get("description"),
                "Required: "
                + ", ".join(item["value"] for item in requirements.get("musts", [])),
                "Preferred: "
                + ", ".join(item["value"] for item in requirements.get("nices", [])),
            )
            if part
        )
        text_parser = TextParser()
        text_parser.feed(description_html)
        places = (posting.get("location") or {}).get("places") or []
        return Offer(
            url=url,
            title=posting.get("title") or "",
            company=(posting.get("company") or {}).get("name"),
            location=places[0].get("city") if places else None,
            date_posted=(
                datetime.fromtimestamp(posting["posted"] / 1000, UTC).date().isoformat()
                if posting.get("posted")
                else None
            ),
            valid_through=posting.get("expiresAt"),
            employment_type=", ".join(
                (posting.get("essentials") or {})
                .get("originalSalary", {})
                .get("types", {})
            ),
            description=text_parser.text(),
            salary=(posting.get("essentials") or {}).get("originalSalary"),
            source_url=source_url,
        )

    def _get(
        self,
        url: str,
        *,
        search: dict[str, Any] | None = None,
        page: int = 1,
        sort: str | None = None,
        limit: int = 20,
    ) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "nofluffjobs.com":
            msg = f"Unexpected fetch URL: {url}"
            raise ValueError(msg)
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            remaining = self.delay_seconds - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            try:
                response = (
                    self.client.post(
                        url,
                        params={
                            "page": page,
                            "limit": limit,
                            "salaryCurrency": "original",
                            "salaryPeriod": "original",
                            "region": "pl",
                            "withSalaryMatch": "true",
                            **({"sort": sort} if sort else {}),
                        },
                        headers={"Content-Type": "application/postingSearch+json"},
                        json=search,
                    )
                    if search is not None
                    else self.client.get(url)
                )
                if response.status_code == HTTP_TOO_MANY_REQUESTS:
                    if attempt == MAX_RATE_LIMIT_RETRIES:
                        msg = (
                            f"Cannot fetch {url}: rate limited after {attempt} retries"
                        )
                        raise RuntimeError(msg)
                    wait = self._retry_delay(response, attempt)
                    if wait > MAX_RETRY_WAIT_SECONDS:
                        msg = f"Cannot fetch {url}: rate limited for {wait} seconds"
                        raise RuntimeError(msg)
                    log.warning(
                        "offer_source_rate_limited",
                        url=url,
                        retry_in_seconds=wait,
                        retry=attempt + 1,
                        max_retries=MAX_RATE_LIMIT_RETRIES,
                        request_delay_seconds=self.delay_seconds,
                    )
                    time.sleep(wait)
                    continue
                response.raise_for_status()
            except httpx.HTTPError as exc:
                msg = f"Cannot fetch {url}: {exc}"
                raise RuntimeError(msg) from exc
            else:
                return response.text
            finally:
                self._last_request = time.monotonic()
        msg = f"Cannot fetch {url}: rate limit retries exhausted"
        raise RuntimeError(msg)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        if self.delay_seconds < MAX_REQUEST_DELAY_SECONDS:
            self.delay_seconds = min(
                MAX_REQUEST_DELAY_SECONDS, max(5, self.delay_seconds * 2)
            )
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after.isdecimal():
            return float(retry_after)
        if retry_after:
            try:
                deadline = parsedate_to_datetime(retry_after)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=UTC)
                return max(0, deadline.timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                pass
        return min(MAX_RETRY_WAIT_SECONDS, 30 * 2.0**attempt)
