"""Parse No Fluff Jobs server state from HTML."""

import json
from html.parser import HTMLParser
from typing import Any


class StateParser(HTMLParser):
    """Parses No Fluff Jobs server state from HTML content."""

    def __init__(self) -> None:
        """Initialize the StateParser."""
        super().__init__()
        self.state: dict[str, Any] = {}
        self._reading = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle the start of an HTML tag.

        Args:
            tag (str): The name of the tag.
            attrs (list[tuple[str, str | None]]): A list of (name, value) pairs containing the attributes.

        """
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == "serverApp-state":
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
            self.state = json.loads("".join(self._buffer))


class TextParser(HTMLParser):
    """Convert a posting's HTML description to plain text."""

    def __init__(self) -> None:
        """Initialize the TextParser."""
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],  # noqa: ARG002
    ) -> None:
        """Handle the start of an HTML tag.

        Args:
            tag (str): The name of the tag.
            attrs (list[tuple[str, str | None]]): A list of (name, value) pairs containing the attributes.

        """
        if tag in {"br", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Handle the data inside an HTML tag.

        Args:
            data (str): The data inside the tag.

        """
        self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Handle the end of an HTML tag.

        Args:
            tag (str): The name of the tag.

        """
        if tag in {"div", "h1", "h2", "h3", "h4", "li", "p", "ul"}:
            self.parts.append("\n")

    def text(self) -> str:
        """Return plain text with normalized whitespace.

        Returns:
            str: The plain text with normalized whitespace.

        """
        return "\n".join(
            " ".join(line.split())
            for line in "".join(self.parts).splitlines()
            if line.strip()
        )
