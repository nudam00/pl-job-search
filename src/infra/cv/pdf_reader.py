"""Read text from a PDF CV file."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfCvReader:
    """Reads text from a PDF CV file and caches the result."""

    def __init__(self, path: Path) -> None:
        """Initialize the PdfCvReader with the path to the PDF file.

        Args:
            path (Path): The path to the PDF CV file.

        """
        self.path = path
        self.cache_path = path.with_suffix(".profile.json")

    def read(self) -> tuple[str, Any]:
        """Read the text from the PDF CV file, using a cache if available.

        Returns:
            tuple[str, Any]: A tuple containing the SHA-256 hash of the PDF file and the extracted text.

        """
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if self.cache_path.exists():
            try:
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if cached["cv_hash"] == digest and cached["text"].strip():
                    return digest, cached["text"]
            except (KeyError, json.JSONDecodeError):
                pass
        try:
            text = "\n".join(
                page.extract_text() or "" for page in PdfReader(self.path).pages
            ).strip()
        except PdfReadError as exc:
            msg = f"Cannot read CV PDF {self.path}: {exc}"
            raise ValueError(msg) from exc
        if not text:
            msg = f"No selectable text in {self.path}; use a text PDF or OCR it first"
            raise ValueError(msg)
        self.cache_path.write_text(
            json.dumps({"cv_hash": digest, "text": text}, ensure_ascii=False),
            encoding="utf-8",
        )
        return digest, text
