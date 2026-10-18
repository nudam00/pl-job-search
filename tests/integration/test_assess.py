import csv
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.assess_cli import _read_exclusions, main
from src.domain import Assessment, Offer
from src.infra.storage import JsonlStore


def offer(name: str) -> Offer:
    return Offer(
        url=f"https://justjoin.it/job-offer/{name}",
        title=f"{name} engineer",
        company="Example",
        location="Remote",
        date_posted="2026-10-14",
        valid_through=None,
        employment_type=None,
        description=f"{name} work",
        salary=None,
        source_url="https://justjoin.it/job-offers/all-locations/ai",
    )


def decision(score: float = 3.2) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "answers": [
                {
                    "name": "match",
                    "type": "score",
                    "score": score,
                    "confidence": 0.8,
                }
            ]
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/decisions"),
    )


def response(score: float = 3.2) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"score": score, "confidence": 0.8}),
                        }
                    ],
                }
            ]
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )


class Pdf:
    pages = [type("Page", (), {"extract_text": lambda _self: "Python CV"})()]


def test_exclusions_skip_scoring_and_shortlist() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        offers = root / "offers.jsonl"
        cv = root / "cv.pdf"
        history = root / "assessments.jsonl"
        shortlist = root / "shortlist.csv"
        exclusions = root / "exclusions.json"
        cv.write_bytes(b"CV")
        qa = offer("QA")
        tester = offer("tester")
        engineer = replace(offer("backend"), company=None)
        reviewed = offer("reviewed")
        company_match = replace(offer("partner"), company="ACME Systems")
        JsonlStore(offers, Offer).write([qa, tester, engineer, reviewed, company_match])
        exclusions.write_text(
            json.dumps(
                {
                    "exclude_title_keywords": ["qa", "TESTER"],
                    "exclude_company_keywords": ["acme"],
                    "exclude_offer_urls": [reviewed.url],
                }
            ),
            encoding="utf-8",
        )
        args = ["assess", str(offers), str(cv), str(history), str(shortlist)]

        excluded_args = [*args, "--exclusions", str(exclusions)]
        with (
            patch("sys.argv", args),
            patch("src.infra.cv.pdf_reader.PdfReader", return_value=Pdf()),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch(
                "src.infra.openai.http_client.httpx.post", return_value=decision()
            ) as http,
        ):
            with patch("sys.argv", excluded_args):
                assert main() == 0
            assert http.call_count == 1
            assert main() == 0
            assert http.call_count == 5
            with patch("sys.argv", excluded_args):
                assert main() == 0
            assert http.call_count == 5

        assert len(JsonlStore(history, Assessment).read()) == 5
        with shortlist.open(newline="", encoding="utf-8") as file:
            assert [row["url"] for row in csv.DictReader(file)] == [engineer.url]


def test_exclusions_lists_may_be_empty(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.json"
    path.write_text(
        '{"exclude_title_keywords": [], "exclude_offer_urls": [], "exclude_company_keywords": []}',
        encoding="utf-8",
    )
    assert _read_exclusions(path) == {
        "exclude_title_keywords": [],
        "exclude_offer_urls": [],
        "exclude_company_keywords": [],
    }


@pytest.mark.parametrize(
    "contents",
    [
        "{",
        "[]",
        '{"exclude_title_keywords": [], "exclude_offer_urls": []}',
        '{"exclude_title_keywords": ["QA"], "exclude_offer_urls": [42]}',
        '{"exclude_title_keywords": [""], "exclude_offer_urls": []}',
        '{"exclude_title_keywords": [], "exclude_offer_urls": [], "exclude_company_keywords": [42]}',
    ],
)
def test_invalid_exclusions_do_not_assess(contents: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        exclusions = root / "exclusions.json"
        exclusions.write_text(contents, encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "assess",
                str(root / "offers.jsonl"),
                str(root / "cv.pdf"),
                str(root / "assessments.jsonl"),
                str(root / "shortlist.csv"),
                "--exclusions",
                str(exclusions),
            ],
        ):
            assert main() == 1
        assert not (root / "assessments.jsonl").exists()


def test_history_shortlist_threshold_and_cv_change() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        offers = root / "offers.jsonl"
        cv = root / "cv.pdf"
        history = root / "assessments.jsonl"
        shortlist = root / "shortlist.csv"
        cv.write_bytes(b"first CV")
        JsonlStore(offers, Offer).write([offer("one"), offer("two")])
        args = ["assess", str(offers), str(cv), str(history), str(shortlist)]

        def post(url, **kwargs):
            assert kwargs["timeout"] == 120
            assert kwargs["follow_redirects"] is False
            assert url == "https://api.openai.com/v1/decisions"
            payload = kwargs["json"]
            assert payload["model"] == "gpt-6-luna"
            assert "Python CV" in payload["input"]
            return decision(3.2 if "one work" in payload["input"] else 1.2)

        with (
            patch("sys.argv", args),
            patch("src.infra.cv.pdf_reader.PdfReader", return_value=Pdf()) as pdf,
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("src.infra.openai.http_client.httpx.post", side_effect=post) as http,
        ):
            assert main() == 0
            assert main() == 0
            assert http.call_count == 2
            pdf.assert_called_once()

            with patch("sys.argv", [*args, "--threshold", "1"]):
                assert main() == 0
            with shortlist.open(newline="", encoding="utf-8") as file:
                assert len(list(csv.DictReader(file))) == 2

            JsonlStore(offers, Offer).write([offer("three")])
            cv.write_bytes(b"changed CV")
            assert main() == 0

        records = JsonlStore(history, Assessment).read()
        assert len(records) == 3
        assert records[-1].url == offer("three").url
        assert http.call_count == 3
        assert pdf.call_count == 2
        assert not history.with_suffix(".offers.jsonl").exists()
        with shortlist.open(newline="", encoding="utf-8") as file:
            assert len(list(csv.DictReader(file))) == 0


def test_unretryable_decisions_limit_uses_responses_for_remaining_offers() -> None:
    limit = httpx.Response(
        429,
        headers={"Retry-After": "1800"},
        json={"error": {"code": "rate_limit_exceeded", "message": "limit reached"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/decisions"),
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        offers = root / "offers.jsonl"
        history = root / "assessments.jsonl"
        JsonlStore(offers, Offer).write([offer("one"), offer("two")])
        cv = root / "cv.pdf"
        cv.write_bytes(b"CV")
        with (
            patch(
                "sys.argv",
                [
                    "assess",
                    str(offers),
                    str(cv),
                    str(history),
                    str(root / "shortlist.csv"),
                ],
            ),
            patch("src.infra.cv.pdf_reader.PdfReader", return_value=Pdf()),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch(
                "src.infra.openai.http_client.httpx.post",
                side_effect=[limit, response(), response()],
            ) as http,
        ):
            assert main() == 0
        assert len(JsonlStore(history, Assessment).read()) == 2
        assert [call.args[0].rsplit("/", 1)[-1] for call in http.call_args_list] == [
            "decisions",
            "responses",
            "responses",
        ]


def test_quota_error_keeps_history_for_next_run() -> None:
    quota = httpx.Response(
        429,
        json={"error": {"code": "credit_balance_exhausted"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/decisions"),
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        offers = root / "offers.jsonl"
        history = root / "assessments.jsonl"
        JsonlStore(offers, Offer).write([offer("one"), offer("two")])
        cv = root / "cv.pdf"
        cv.write_bytes(b"CV")
        with (
            patch(
                "sys.argv",
                [
                    "assess",
                    str(offers),
                    str(cv),
                    str(history),
                    str(root / "shortlist.csv"),
                ],
            ),
            patch("src.infra.cv.pdf_reader.PdfReader", return_value=Pdf()),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch(
                "src.infra.openai.http_client.httpx.post", return_value=quota
            ) as http,
        ):
            assert main() == 1
        http.assert_called_once()
        assert not history.exists()


@pytest.mark.parametrize("error_code", ["slow_down", "rate_limit_exceeded"])
def test_temporary_rate_limit_retries_and_saves_result(error_code: str) -> None:
    retry = httpx.Response(
        429,
        headers={"Retry-After": "3"},
        json={"error": {"code": error_code}},
        request=httpx.Request("POST", "https://api.openai.com/v1/decisions"),
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        offers = root / "offers.jsonl"
        history = root / "assessments.jsonl"
        JsonlStore(offers, Offer).write([offer("one")])
        cv = root / "cv.pdf"
        cv.write_bytes(b"CV")
        with (
            patch(
                "sys.argv",
                [
                    "assess",
                    str(offers),
                    str(cv),
                    str(history),
                    str(root / "shortlist.csv"),
                ],
            ),
            patch("src.infra.cv.pdf_reader.PdfReader", return_value=Pdf()),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch(
                "src.infra.openai.http_client.httpx.post",
                side_effect=[retry, decision()],
            ) as http,
            patch("src.infra.openai.decisions_scorer.time.sleep") as sleep,
            patch("src.infra.openai.decisions_scorer.random.uniform", return_value=0),
        ):
            assert main() == 0
        assert len(JsonlStore(history, Assessment).read()) == 1
        assert http.call_count == 2
        assert sleep.call_args_list[0].args == (3,)
