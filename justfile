set dotenv-load := true

# List available commands
default:
    @just --list

# Install production dependencies only
install:
    uv sync --frozen --no-dev

# Install development dependencies and pre-commit hooks
install-dev:
    uv sync --frozen
    uv run pre-commit install

# Update the lockfile
lock:
    uv lock

# Run all repository linters
lint:
    uv run pre-commit run --all-files

# Run all tests
test:
    uv run pytest

# Run the same quality gates as CI
check: lint test

# Run data collection
collect listings="data/listings.csv" output="data/offers.jsonl":
    uv run python -m src.collect_cli {{listings}} {{output}}

# Run assessment
assess offers cv="data/cv.pdf" history="data/assessments.jsonl" shortlist="data/shortlist.csv" threshold="2.0" exclusions="data/exclusions.json":
    uv run python -m src.assess_cli {{offers}} {{cv}} {{history}} {{shortlist}} --threshold {{threshold}} --exclusions {{exclusions}}

# Clean build artifacts and caches
clean:
    rm -rf build/ dist/ htmlcov/ .coverage .ruff_cache/ .pytest_cache/ .mypy_cache/ .hypothesis/ .tox/
    find . -maxdepth 1 -type d -name "*.egg-info" -exec rm -rf {} +
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
