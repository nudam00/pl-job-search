"""Parse The Protocol's embedded listing and offer data."""

import json
from typing import Any

from src.infra.justjoin.json_ld_parser import JsonLdParser


class StateParser(JsonLdParser):
    """Parses Next.js page properties alongside JSON-LD documents."""

    def __init__(self) -> None:
        """Initialize the StateParser."""
        super().__init__()
        self.state: dict[str, Any] = {}
        self._reading_state = False
        self._state_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle the start of an HTML tag.

        Args:
            tag (str): The name of the tag.
            attrs (list[tuple[str, str | None]]): A list of (name, value) pairs containing the attributes.

        """
        super().handle_starttag(tag, attrs)
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._reading_state = True
            self._state_buffer = []

    def handle_data(self, data: str) -> None:
        """Handle the data inside an HTML tag.

        Args:
            data (str): The data inside the tag.

        """
        super().handle_data(data)
        if self._reading_state:
            self._state_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Handle the end of an HTML tag.

        Args:
            tag (str): The name of the tag.

        """
        super().handle_endtag(tag)
        if tag == "script" and self._reading_state:
            self._reading_state = False
            document = json.loads("".join(self._state_buffer))
            self.state = document.get("props", {}).get("pageProps", {})

    def job_postings(self) -> list[dict[str, Any]]:
        """Find JobPosting objects in the parsed JSON-LD documents.

        Returns:
            list[dict[str, Any]]: Job postings in document order, including nested graphs.

        """
        postings: list[dict[str, Any]] = []
        pending: list[Any] = list(reversed(self.documents))
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(reversed(value))
            elif isinstance(value, dict):
                types = value.get("@type", [])
                if types == "JobPosting" or (
                    isinstance(types, list) and "JobPosting" in types
                ):
                    postings.append(value)
                else:
                    pending.extend(reversed(value.values()))
        return postings
