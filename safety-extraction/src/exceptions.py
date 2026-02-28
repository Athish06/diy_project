"""Custom exceptions for the safety extraction pipeline."""


class ExtractionError(Exception):
    """Raised when rule extraction from LLM fails after retries."""
    pass


class PDFIngestionError(Exception):
    """Raised when PDF cannot be read or processed."""
    pass
