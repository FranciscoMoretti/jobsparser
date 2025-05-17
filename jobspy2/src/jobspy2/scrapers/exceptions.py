"""
jobspy2.scrapers.exceptions
~~~~~~~~~~~~~~~~~~~

This module contains the set of Scrapers' exceptions.
"""


class LinkedInException(Exception):
    """Raised when there's an error processing LinkedIn job data."""

    def __init__(self) -> None:
        self.message = "Failed to process LinkedIn job data"
        super().__init__(self.message)


class IndeedException(Exception):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "An error occurred with Indeed")


class ZipRecruiterException(Exception):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "An error occurred with ZipRecruiter")


class GlassdoorException(Exception):
    JOB_PROCESSING_FAILED = "Job processing failed"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "An error occurred with Glassdoor")


class GoogleJobsException(Exception):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "An error occurred with Google Jobs")


class GlassdoorLocationError(Exception):
    """Raised when a location cannot be found on Glassdoor."""

    def __init__(self, location: str) -> None:
        self.message = f"Location {location!r} not found on Glassdoor"
        super().__init__(self.message)
