"""Parses JSON-LD data from HTML content."""

import json
from html.parser import HTMLParser
from typing import Any


class JsonLdParser(HTMLParser):
    """Parses JSON-LD data from HTML content."""

    def __init__(self) -> None:
        """Initialize the JsonLdParser."""
        super().__init__()
        self._reading = False
        self._buffer: list[str] = []
        self.documents: list[dict[str, Any]] = []
        self.next_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle the start of an HTML tag.

        Args:
            tag (str): The name of the tag.
            attrs (list[tuple[str, str | None]]): A list of (name, value) pairs containing the attributes.

        """
        attributes = dict(attrs)
        if tag == "a" and attributes.get("aria-label") == "Next":
            self.next_url = attributes.get("href")
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._reading = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        """Handle the data inside an HTML tag.

        Args:
            data (str): The data inside the tag.

        """
        if self._reading:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Handle the end of an HTML tag.

        Args:
            tag (str): The name of the tag.

        """
        if tag == "script" and self._reading:
            self._reading = False
            self.documents.append(json.loads("".join(self._buffer)))
