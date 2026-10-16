"""Read listing URLs and write assessment shortlists as CSV."""

import csv
from pathlib import Path

from src.domain import Assessment

SHORTLIST_COLUMNS = (
    "url",
    "title",
    "company",
    "location",
    "score",
    "confidence",
    "date_posted",
    "assessed_at",
)


class CsvStore:
    """Handle the two CSV formats used by the application."""

    @staticmethod
    def read_listings(path: Path) -> list[str]:
        """Read listing URLs from a CSV file.

        Args:
            path (Path): The path to the CSV file containing listing URLs.

        Returns:
            list[str]: A list of unique listing URLs read from the CSV file.

        Raises:
            ValueError: If the CSV file does not have a 'url' column or contains no listing URLs.

        """
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames or "url" not in reader.fieldnames:
                msg = "CSV must have a 'url' column"
                raise ValueError(msg)
            urls = [
                row["url"].strip()
                for row in reader
                if row["url"] and row["url"].strip()
            ]
        if not urls:
            msg = "CSV contains no listing URLs"
            raise ValueError(msg)
        return list(dict.fromkeys(urls))

    @staticmethod
    def write_shortlist(
        path: Path,
        assessments: list[Assessment],
    ) -> int:
        """Write selected assessments to CSV.

        Args:
            path (Path): The path to the CSV file to write the shortlist.
            assessments (list[Assessment]): The selected assessments to write.

        Returns:
            int: The number of assessments written to the CSV file.

        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=SHORTLIST_COLUMNS)
            writer.writeheader()
            for assessment in assessments:
                writer.writerow(
                    {name: getattr(assessment, name) for name in SHORTLIST_COLUMNS}
                )
        return len(assessments)
