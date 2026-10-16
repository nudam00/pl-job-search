"""Domain model for job offers."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Offer:
    """Represents a job offer with relevant details."""

    url: str
    title: str
    company: str | None
    location: str | None
    date_posted: str | None
    valid_through: str | None
    employment_type: str | None
    description: str | None
    salary: dict[str, Any] | None
    source_url: str
