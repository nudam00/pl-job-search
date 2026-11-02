"""Collect offers from The Protocol in a browser session with manual challenges."""

from __future__ import annotations

import time
from concurrent.futures import Future
from contextlib import ExitStack
from threading import Thread
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import structlog

from src.domain import Offer
from src.infra.text_parser import TextParser

from .state_parser import StateParser

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page, Route

log = structlog.get_logger(__name__)


class TheProtocolBrowserSource:
    """Collect offers from The Protocol using installed Chrome and a temporary browser session."""

    def __init__(self, delay_seconds: float = 5.0) -> None:
        """Initialize the TheProtocolBrowserSource with a minimum delay between page requests.

        Args:
            delay_seconds (float): The number of seconds to wait between requests. Default is 5 seconds.

        """
        self.delay_seconds = delay_seconds
        self._last_request = 0.0
        self._resources = ExitStack()
        self._page: Page | None = None

    def close(self) -> None:
        """Close Chrome and the Playwright runtime."""
        self._resources.close()
        self._page = None

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
            ValueError: If the listing URL is invalid or does not contain expected data.
            RuntimeError: If there is an error reading the listing or offer pages in Chrome.

        """
        parsed = urlsplit(listing_url)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key != "pageNumber"
        ]
        urls: dict[str, str] = {}
        number = 1
        pages = 1
        while number <= pages:
            page_query = query + ([("pageNumber", str(number))] if number > 1 else [])
            url = urlunsplit(parsed._replace(query=urlencode(page_query), fragment=""))
            listing = self._listing(url)
            if listing["page"]["number"] != number:
                msg = f"Unexpected The Protocol page at {url}"
                raise ValueError(msg)
            if number == 1:
                pages = listing["page"]["count"]
            for posting in listing["offers"]:
                urls.setdefault(
                    posting["id"],
                    urljoin(url, f"/szczegoly/praca/{posting['offerUrlName']}"),
                )
            number += 1
        seen = set(known_urls or ())
        for url in urls.values():
            if url not in seen:
                offer = self._offer(url, listing_url)
                seen.add(url)
                yield offer

    def _listing(self, url: str) -> dict[str, Any]:
        self._validate_url(url)
        path = urlsplit(url).path.rstrip("/")
        if path not in {"/praca", "/filtry"} and not path.startswith("/filtry/"):
            msg = f"Not a The Protocol listing URL: {url}"
            raise ValueError(msg)
        parser = StateParser()
        parser.feed(self._get(url))
        listing = parser.state.get("offersResponse")
        if (
            not isinstance(listing, dict)
            or not {"page", "offers", "offersCount"} <= listing.keys()
        ):
            msg = f"No listing data found at {url}"
            raise ValueError(msg)
        return listing

    def _offer(self, url: str, source_url: str) -> Offer:
        self._validate_url(url)
        path = urlsplit(url).path
        if (
            not path.startswith(("/szczegoly/praca/", "/praca/"))
            or ",oferta," not in path
        ):
            msg = f"Unexpected The Protocol offer URL: {url}"
            raise ValueError(msg)
        parser = StateParser()
        parser.feed(self._get(url))
        postings = parser.job_postings()
        if not postings:
            msg = f"No JobPosting data found at {url}"
            raise ValueError(msg)
        posting = postings[0]
        company = posting.get("hiringOrganization") or {}
        places = posting.get("jobLocation") or []
        places = places if isinstance(places, list) else [places]
        employment = posting.get("employmentType")
        text = TextParser()
        text.feed(posting.get("description") or "")
        return Offer(
            url=url,
            title=posting.get("title") or "",
            company=company if isinstance(company, str) else company.get("name"),
            location=", ".join(
                dict.fromkeys(
                    place.get("address", {}).get("addressLocality", "")
                    for place in places
                )
            )
            or None,
            date_posted=posting.get("datePosted"),
            valid_through=posting.get("validThrough"),
            employment_type=(
                ", ".join(employment) if isinstance(employment, list) else employment
            ),
            description=text.text(),
            salary=posting.get("baseSalary"),
            source_url=source_url,
        )

    def _allow_navigation(self, route: Route) -> None:
        request = route.request
        if request.is_navigation_request() and request.frame.parent_frame is None:
            try:
                self._validate_url(request.url)
            except ValueError:
                log.warning("protocol_navigation_blocked", url=request.url)
                route.abort()
                return
        parsed = urlsplit(request.url)
        challenge_asset = (
            parsed.hostname == "challenges.cloudflare.com"
            or parsed.path.startswith("/cdn-cgi/")
        )
        if not challenge_asset and (
            request.resource_type in {"image", "media", "font"}
            or "prefetch" in request.headers.get("purpose", "").casefold()
            or "prefetch" in request.headers.get("sec-purpose", "").casefold()
            or request.headers.get("next-router-prefetch") == "1"
        ):
            route.abort()
            return
        route.continue_()

    def _get(self, url: str) -> str:
        self._validate_url(url)
        try:
            from playwright import sync_api  # noqa: PLC0415 - optional browser extra
        except ImportError as exc:
            msg = "The Protocol requires browser support: run uv sync --frozen --extra browser"
            raise RuntimeError(msg) from exc
        remaining = self.delay_seconds - (time.monotonic() - self._last_request)
        if remaining > 0:
            if self._page is None:
                time.sleep(remaining)
            else:
                self._page.wait_for_timeout(remaining * 1000)
        try:
            if self._page is None:
                playwright = self._resources.enter_context(sync_api.sync_playwright())
                browser = playwright.chromium.launch(channel="chrome", headless=False)
                self._resources.callback(browser.close)
                context = browser.new_context(service_workers="block")
                context.route("**/*", self._allow_navigation)
                self._page = context.new_page()
            self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            state = self._page.locator("script#__NEXT_DATA__")
            try:
                state.wait_for(state="attached", timeout=10000)
            except sync_api.TimeoutError:
                log.warning("protocol_manual_verification_required", url=url)
                self._wait_for_confirmation(
                    self._page,
                    "Complete any challenge in Chrome, then press Enter here when the page is visible: ",
                )
                state.wait_for(state="attached", timeout=10000)
            self._validate_url(self._page.url)
            return self._page.content()
        except (sync_api.Error, EOFError, OSError) as exc:
            msg = f"Cannot read {url} in Chrome: {exc}"
            raise RuntimeError(msg) from exc
        finally:
            self._last_request = time.monotonic()

    @staticmethod
    def _wait_for_confirmation(page: Page, prompt: str) -> None:
        confirmation: Future[None] = Future()

        def read_input() -> None:
            try:
                input(prompt)
            except (EOFError, OSError) as exc:
                confirmation.set_exception(exc)
            else:
                confirmation.set_result(None)

        Thread(target=read_input, daemon=True).start()
        # Intercepted navigation needs Playwright's event loop even during the prompt.
        while not confirmation.done():
            page.wait_for_timeout(100)
        confirmation.result()

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "theprotocol.it"
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
        ):
            msg = f"Unexpected The Protocol URL: {url}"
            raise ValueError(msg)
