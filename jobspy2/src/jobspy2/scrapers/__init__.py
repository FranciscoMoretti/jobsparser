from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from .utils import create_logger 

from ..jobs import (
    BaseModel,
    Country,
    DescriptionFormat,
    Enum,
    JobResponse,
    JobType,
)


class Site(Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    ZIP_RECRUITER = "zip_recruiter"
    GLASSDOOR = "glassdoor"
    GOOGLE = "google"


class SalarySource(Enum):
    DIRECT_DATA = "direct_data"
    DESCRIPTION = "description"


class LinkedInExperienceLevel(Enum):
    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    ASSOCIATE = "associate"
    MID_SENIOR_LEVEL = "mid_senior_level"
    DIRECTOR = "director"
    EXECUTIVE = "executive"


class ScraperInput(BaseModel):
    site_type: list[Site]
    search_term: str | None = None
    google_search_term: str | None = None

    location: str | None = None
    country: Country = Country.USA
    distance: int | None = None
    is_remote: bool = False
    job_type: JobType | None = None
    easy_apply: bool | None = None
    offset: int = 0
    linkedin_fetch_description: bool = False
    linkedin_company_ids: list[int] | None = None
    linkedin_experience_levels: list[LinkedInExperienceLevel] | None = None
    description_format: DescriptionFormat | None = DescriptionFormat.MARKDOWN

    results_wanted: int = 15
    hours_old: int | None = None

    logger: logging.Logger | None = None


class Scraper(ABC):
    def __init__(self, site: Site, logger: logging.Logger, proxies: list[str] | str | None = None, ca_cert: str | None = None):
        self.site = site
        self.proxies = proxies
        self.ca_cert = ca_cert
        self.logger = logger

    @abstractmethod
    def scrape(self, scraper_input: ScraperInput) -> JobResponse: ...
