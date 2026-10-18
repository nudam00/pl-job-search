# Working in PL Job Search

Read `README.md` for setup and CLI usage, and `CONTEXT.md` for project terms.
Keep changes small and follow the existing separation:

- `src/domain/` holds `Offer` and `Assessment` records. It has no infrastructure dependencies.
- `src/application/` holds collection and assessment workflows, scorer selection, and ports.
- `src/infra/` handles HTTP, HTML/PDF parsing, and CSV/JSONL storage.
- `src/collect_cli.py` and `src/assess_cli.py` connect these parts. Keep `src/__init__.py` so package imports work with the type checker.

## Changes that affect behavior

- When changing the scoring instructions or levels in `src/application/rubric.py`, increment `RUBRIC_VERSION`. It determines whether saved assessments can be reused.
- To add a job site, implement `OfferSource` and register its hostname in `collect_cli.py`.
  Register resource cleanup with `ExitStack`. Validate URLs before fetching and keep redirects disabled or validate every redirect target.
- Keep assessment history durable after each successful score. Preserve the existing JSONL format unless a migration is part of the task.
- Never commit API keys, CVs, extracted CV text, or files from `data/`. Tests should use synthetic data and mock external HTTP/PDF boundaries.

## Checks

Run from the repository root:

```bash
uv run --frozen python -m pytest -q
uv run --frozen pre-commit run --all-files
```

For a new untracked file, also run `uv run --frozen pre-commit run --files <path>`; `--all-files` only checks tracked files.
