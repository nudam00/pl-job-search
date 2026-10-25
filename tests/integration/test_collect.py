import json
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.collect_cli import main
from src.infra.justjoin import JustJoinHtmlSource

LISTING = "https://justjoin.it/job-offers/all-locations/ai?sortBy=newest"
PAGE_TWO = LISTING + "&page=2"
OFFER_ONE = "https://justjoin.it/job-offer/one"
OFFER_TWO = "https://justjoin.it/job-offer/two"


def page(document: dict[str, object], next_link: str = "") -> str:
    return (
        '<html><script type="application/ld+json">'
        + json.dumps(document)
        + "</script>"
        + next_link
        + "</html>"
    )


def test_collects_pages_and_skips_saved_offer_details() -> None:
    html = {
        LISTING: page(
            {
                "mainEntity": {
                    "@type": "ItemList",
                    "itemListElement": [{"url": OFFER_ONE}],
                }
            },
            '<a aria-label="Next" href="?sortBy=newest&amp;page=2">Next</a>',
        ),
        PAGE_TWO: page(
            {
                "mainEntity": {
                    "@type": "ItemList",
                    "itemListElement": [{"url": OFFER_ONE}, {"url": OFFER_TWO}],
                }
            }
        ),
        OFFER_ONE: page(
            {
                "@type": "JobPosting",
                "title": "AI Engineer",
                "hiringOrganization": {"name": "Example"},
                "description": "Build AI.",
            }
        ),
        OFFER_TWO: page({"@type": "JobPosting", "title": "Data Engineer"}),
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        listings = root / "listings.csv"
        listings.write_text(f"url\n{LISTING}\n{LISTING}\n", encoding="utf-8")
        output = root / "offers.jsonl"
        output.write_text(
            json.dumps(
                {
                    "url": OFFER_ONE,
                    "title": "Saved AI Engineer",
                    "company": "Example",
                    "location": None,
                    "date_posted": None,
                    "valid_through": None,
                    "employment_type": None,
                    "description": "Saved description",
                    "salary": None,
                    "source_url": LISTING,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with (
            patch("sys.argv", ["collect", str(listings), str(output)]),
            patch(
                "src.infra.justjoin.html_source.JustJoinHtmlSource._get",
                side_effect=lambda url: html[url],
            ) as fetch,
        ):
            assert main() == 0
            assert main() == 0

        offers = [json.loads(line) for line in output.read_text().splitlines()]
        assert [item["url"] for item in offers] == [OFFER_ONE, OFFER_TWO]
        assert offers[0]["company"] == "Example"
        assert offers[0]["title"] == "Saved AI Engineer"
        assert offers[1]["source_url"] == PAGE_TWO
        assert fetch.call_count == 5
        assert [call.args[0] for call in fetch.call_args_list].count(OFFER_ONE) == 0
        assert [call.args[0] for call in fetch.call_args_list].count(OFFER_TWO) == 1


def test_rejects_unsupported_host_before_fetching() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        listings = root / "listings.csv"
        listings.write_text("url\nhttps://other.example/jobs\n", encoding="utf-8")
        with (
            patch("sys.argv", ["collect", str(listings), str(root / "offers.jsonl")]),
            patch("src.infra.justjoin.html_source.JustJoinHtmlSource._get") as fetch,
        ):
            assert main() == 1
        fetch.assert_not_called()
        assert list(root.glob("*.jsonl")) == []


def test_rejects_untrusted_offer_url_from_page() -> None:
    listing_html = page(
        {
            "mainEntity": {
                "@type": "ItemList",
                "itemListElement": [{"url": "file:///tmp/private"}],
            }
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        listings = root / "listings.csv"
        listings.write_text(f"url\n{LISTING}\n", encoding="utf-8")
        with (
            patch("sys.argv", ["collect", str(listings), str(root / "offers.jsonl")]),
            patch(
                "src.infra.justjoin.html_source.JustJoinHtmlSource._get",
                return_value=listing_html,
            ) as fetch,
        ):
            assert main() == 1
        fetch.assert_called_once_with(LISTING)
        assert list(root.glob("*.jsonl")) == []


def test_http_redirect_is_not_followed() -> None:
    response = httpx.Response(
        302,
        headers={"Location": "https://other.example/private"},
        request=httpx.Request("GET", LISTING),
    )
    with patch("src.infra.justjoin.html_source.httpx.Client") as client_type:
        client_type.return_value.get.return_value = response
        with closing(JustJoinHtmlSource(delay_seconds=0)) as source:
            with pytest.raises(RuntimeError, match="Cannot fetch"):
                source._get(LISTING)
    assert client_type.call_args.kwargs["follow_redirects"] is False
    client_type.return_value.get.assert_called_once_with(LISTING)


def test_reuses_http_client_for_multiple_pages() -> None:
    with patch("src.infra.justjoin.html_source.httpx.Client") as client_type:
        client_type.return_value.get.return_value = httpx.Response(
            200, text="page", request=httpx.Request("GET", LISTING)
        )
        with closing(JustJoinHtmlSource(delay_seconds=0)) as source:
            assert source._get(LISTING) == "page"
            assert source._get(OFFER_ONE) == "page"
    client_type.assert_called_once()
    assert client_type.return_value.get.call_count == 2
    client_type.return_value.close.assert_called_once()
