"""Configure readable CLI logging."""

import sys

import structlog


def configure_logging() -> None:
    """Configure logging for the application."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
