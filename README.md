# Role Radar

Collect job offers from listing pages and score them against a PDF CV.
Assessment uses OpenAI Decisions, with a Responses fallback when a Decisions rate limit cannot be retried during the run.

## Table of contents

- [Responsible collection](#responsible-collection)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Privacy and cost](#privacy-and-cost)
- [Development](#development)

## Responsible collection

Before collecting from any site, check its current terms and applicable rules, and obtain permission where required.
This project does not grant access or collection rights. You can also assess offer data obtained without using the collector.

## Requirements

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- An OpenAI API key for assessment. Collection does not require one.

## Quick start

From the repository root, install dependencies:

```bash
uv sync --frozen
```

Copy [the example listings file](examples/listings.csv) to `data/listings.csv`, replace its URL with permitted listing URLs, then collect:

```bash
mkdir -p data
cp examples/listings.csv data/listings.csv
uv run python -m src.collect_cli data/listings.csv data/offers.jsonl
```

Only `https://justjoin.it/job-offers/...` listing URLs are supported at present.
Collection writes `data/offers-YYYY-MM-DD.jsonl` using your local date; a second run on the same day replaces that day's file.

Put a text-based PDF CV at `data/cv.pdf`, set `OPENAI_API_KEY` in your environment, and assess the snapshot:

```bash
uv run python -m src.assess_cli data/offers-YYYY-MM-DD.jsonl data/cv.pdf data/assessments.jsonl data/shortlist.csv --threshold 2.0
```

If you have [`just`](https://github.com/casey/just), you can use the shorter commands:

```bash
just install-dev
just collect
just assess data/offers-YYYY-MM-DD.jsonl
```

Replace `YYYY-MM-DD` with the actual filename date. Scores range from 0 to 4, and the CLI's default threshold is 2.0.
To skip unwanted titles, companies, and offers already reviewed, copy [the example exclusions file](examples/exclusions.json) to `data/exclusions.json`, then edit its lists:

```bash
mkdir -p data
cp -n examples/exclusions.json data/exclusions.json
```

Pass the file when assessing:

```bash
uv run python -m src.assess_cli data/offers-YYYY-MM-DD.jsonl data/cv.pdf data/assessments.jsonl data/shortlist.csv --exclusions data/exclusions.json
```

`just assess` uses `data/exclusions.json`. Use the direct CLI command above to choose another file.

Title and company keyword matching ignore case and check only their respective fields. Offer URLs match exactly.
Excluded offers are not scored or included in the shortlist; existing assessment history is preserved.
All three lists are required but may be empty. Files in `data/` are ignored by Git.
If the PDF contains no selectable text, run OCR on it first. Assessment sends the extracted CV text and offer details to OpenAI and can incur API charges.

If you already have offer data, skip collection and pass your own JSONL file as the first argument to the assessment command.
Each line must contain the fields shown below; replace the example values with your own:

```json
{
  "url": "https://example.com/jobs/123",
  "title": "Software Engineer",
  "company": "Example",
  "location": "Remote",
  "date_posted": null,
  "valid_through": null,
  "employment_type": null,
  "description": "Build software.",
  "salary": null,
  "source_url": "https://example.com/jobs"
}
```

Successful scores, including scores below the threshold, are saved in `data/assessments.jsonl`.
Rerunning with the same CV and rubric reuses them; changing either reassesses offers in the supplied snapshot.
`data/shortlist.csv` is rebuilt from assessment history with one row per offer URL, so manually removed rows can reappear.

## Privacy and cost

Files in `data/` and `.env` are ignored by Git; do not add private data to commits manually.
The CLI reads `OPENAI_API_KEY` from the environment. Direct `uv` commands need it set in the shell; `just` also loads it from `.env` if present.
Extracted CV text is cached beside the PDF as `cv.profile.json` and refreshed when the PDF changes.

## Development

Run the integration tests with:

```bash
uv run --frozen python -m pytest -q
```

The code has `domain/` records, `application/` workflows and ports, and `infra/` adapters.
To add another job site, implement `OfferSource` and register its hostname in `src/collect_cli.py`.
Run `just --list` to see the other available commands and their defaults.

Licensed under the [MIT License](LICENSE).
