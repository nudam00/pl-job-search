"""Read and write JSONL files."""

import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Generic, TypeVar

T = TypeVar("T")


class JsonlStore(Generic[T]):
    """Read and write JSONL files for records of type T."""

    def __init__(self, path: Path, record_type: type[T]) -> None:
        """Initialize the JsonlStore with a file path and record type.

        Args:
            path (Path): The path to the JSONL file.
            record_type (type[T]): The type of records to read and write.

        """
        self.path = path
        self.record_type = record_type

    def read(self, *, missing_ok: bool = False) -> list[T]:
        """Read records from the JSONL file.

        Args:
            missing_ok (bool): If True, return an empty list if the file does not exist.

        Returns:
            list[T]: A list of records of type T.

        """
        if missing_ok and not self.path.exists():
            return []
        return [
            self.record_type(**json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def write(self, records: list[T]) -> None:
        """Write records to the JSONL file.

        Args:
            records (list[T]): A list of records of type T to write to the file.

        Raises:
            TypeError: If any record is not an instance of the specified record type.

        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                encoding="utf-8",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                for record in records:
                    if isinstance(record, type) or not is_dataclass(record):
                        msg = "JSONL records must be dataclass instances"
                        raise TypeError(msg)
                    file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            temporary_path.replace(self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def append(self, record: T) -> None:
        """Durably append one record to the JSONL file.

        Args:
            record (T): The record to append.

        Raises:
            TypeError: If the record is not a dataclass instance.

        """
        if isinstance(record, type) or not is_dataclass(record):
            msg = "JSONL records must be dataclass instances"
            raise TypeError(msg)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+b") as file:
            if file.tell():
                file.seek(-1, os.SEEK_END)
                if file.read(1) != b"\n":
                    file.write(b"\n")
            file.write(
                (json.dumps(asdict(record), ensure_ascii=False) + "\n").encode("utf-8")
            )
            file.flush()
            os.fsync(file.fileno())
