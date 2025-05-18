"""
jobspy2.scrapers.indeed
~~~~~~~~~~~~~~~~~~~

This module contains routines to scrape Indeed.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from ...jobs import (
    Compensation,
    CompensationInterval,
    DescriptionFormat,
    JobPost,
    JobResponse,
    JobType,
    Location,
)
from .. import Scraper, ScraperInput, Site
from ..utils import (
    create_logger,
    create_session,
    extract_emails_from_text,
    get_enum_from_job_type,
    markdown_converter,
)
from .constants import api_headers, job_search_query



class IntervalError(ValueError):
    """Raised when an unsupported interval is provided."""

    def __init__(self, interval: str, is_compensation: bool = False) -> None:
        prefix = "compensation " if is_compensation else ""
        self.message = f"Unsupported {prefix}interval: {interval!r}"
        super().__init__(self.message)


class IndeedScraper(Scraper):
    def __init__(self, logger: logging.Logger, proxies: list[str] | str | None = None, ca_cert: str | None = None) -> None:
        """
        Initializes IndeedScraper with the Indeed API url
        """
        super().__init__(Site.INDEED, logger=logger, proxies=proxies, ca_cert=ca_cert)

        self.session = create_session(proxies=self.proxies, ca_cert=ca_cert, is_tls=False)
        self.scraper_input: ScraperInput | None = None
        self.jobs_per_page: int = 100
        self.num_workers: int = 10
        self.seen_urls: set[str] = set()
        self.headers: dict[str, str] | None = None
        self.api_country_code: str | None = None
        self.base_url: str | None = None
        self.api_url: str = "https://apis.indeed.com/graphql"

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        """
        Scrapes Indeed for jobs with scraper_input criteria
        :param scraper_input:
        :return: job_response
        """
        self.scraper_input = scraper_input
        domain, self.api_country_code = self.scraper_input.country.indeed_domain_value
        self.base_url = f"https://{domain}.indeed.com"
        self.headers = api_headers.copy()
        self.headers["indeed-co"] = self.api_country_code
        job_list: list[JobPost] = []
        page = 1

        cursor = None

        while len(self.seen_urls) < scraper_input.results_wanted + scraper_input.offset:
            self.logger.info(f"search page: {page} / {math.ceil(scraper_input.results_wanted / self.jobs_per_page)}")
            jobs, cursor = self._scrape_page(cursor)
            if not jobs:
                self.logger.info(f"found no jobs on page: {page}")
                break
            job_list += jobs
            page += 1
        return JobResponse(jobs=job_list[scraper_input.offset : scraper_input.offset + scraper_input.results_wanted])

    def _scrape_page(self, cursor: str | None) -> tuple[list[JobPost], str | None]:
        """
        Scrapes a page of Indeed for jobs with scraper_input criteria
        :param cursor:
        :return: jobs found on page, next page cursor
        """
        if not self.scraper_input or not self.api_country_code:
            return [], None
        jobs: list[JobPost] = []
        new_cursor = None
        filters = self._build_filters()
        search_term = self.scraper_input.search_term.replace('"', '\\"') if self.scraper_input.search_term else ""
        query = job_search_query.format(
            what=(f'what: "{search_term}"' if search_term else ""),
            location=(
                f'location: {{where: "{self.scraper_input.location}", radius: {self.scraper_input.distance}, radiusUnit: MILES}}'
                if self.scraper_input.location
                else ""
            ),
            dateOnIndeed=self.scraper_input.hours_old,
            cursor=f'cursor: "{cursor}"' if cursor else "",
            filters=filters,
        )
        payload = {
            "query": query,
        }
        api_headers_temp = api_headers.copy()
        api_headers_temp["indeed-co"] = self.api_country_code
        
        # Log request details for debugging
        self.logger.debug("Indeed API Request Details:")
        self.logger.debug(f"URL: {self.api_url}")
        self.logger.debug("Headers:")
        for key, value in api_headers_temp.items():
            self.logger.debug(f"  {key}: {value}")
        self.logger.debug("Payload:")
        self.logger.debug(f"  {payload}")
        
        response = self.session.post(
            self.api_url,
            headers=api_headers_temp,
            json=payload,
            timeout=10,
        )
        if not response.ok:
            self.logger.info(
                f"responded with status code: {response.status_code} (submit GitHub issue if this appears to be a bug)"
            )
            return jobs, new_cursor
        data = response.json()
        jobs_data = data["data"]["jobSearch"]["results"]
        new_cursor = data["data"]["jobSearch"]["pageInfo"]["nextCursor"]

        job_list: list[JobPost] = []
        for job in jobs_data:
            processed_job = self._process_job(job["job"])
            if processed_job:
                job_list.append(processed_job)

        return job_list, new_cursor

    def _build_filters(self) -> str:
        """
        Builds the filters dict for job type/is_remote. If hours_old is provided, composite filter for job_type/is_remote is not possible.
        IndeedApply: filters: { keyword: { field: "indeedApplyScope", keys: ["DESKTOP"] } }
        """
        if not self.scraper_input:
            return ""
        filters_str = ""
        if self.scraper_input.hours_old:
            filters_str = f"""
            filters: {{
                date: {{
                  field: "dateOnIndeed",
                  start: "{self.scraper_input.hours_old}h"
                }}
            }}
            """
        elif self.scraper_input.easy_apply:
            filters_str = """
            filters: {
                keyword: {
                  field: "indeedApplyScope",
                  keys: ["DESKTOP"]
                }
            }
            """
        elif self.scraper_input.job_type or self.scraper_input.is_remote:
            job_type_key_mapping: dict[JobType, str] = {
                JobType.FULL_TIME: "CF3CP",
                JobType.PART_TIME: "75GKK",
                JobType.CONTRACT: "NJXCK",
                JobType.INTERNSHIP: "VDTG7",
            }

            keys: list[str] = []
            if self.scraper_input.job_type:
                key = job_type_key_mapping[self.scraper_input.job_type]
                keys.append(key)

            if self.scraper_input.is_remote:
                keys.append("DSQF7")

            if keys:
                keys_str = '", "'.join(keys)
                filters_str = f"""
                filters: {{
                  composite: {{
                    filters: [{{
                      keyword: {{
                        field: "attributes",
                        keys: ["{keys_str}"]
                      }}
                    }}]
                  }}
                }}
                """
        return filters_str

    def _process_job(self, job: dict[str, Any]) -> JobPost | None:
        """
        Parses the job dict into JobPost model
        :param job: dict to parse
        :return: JobPost if it's a new job
        """
        if not self.base_url or not self.scraper_input:
            return None
        job_url = f"{self.base_url}/viewjob?jk={job['key']}"
        if job_url in self.seen_urls:
            return None
        self.seen_urls.add(job_url)
        description = job["description"]["html"]
        if self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
            description = markdown_converter(description)

        job_type = self._get_job_type(job["attributes"])
        timestamp_seconds = job["datePublished"] / 1000
        date_posted = datetime.fromtimestamp(timestamp_seconds).date()
        employer = job["employer"].get("dossier") if job["employer"] else None
        employer_details = employer.get("employerDetails", {}) if employer else {}
        rel_url = job["employer"]["relativeCompanyPageUrl"] if job["employer"] else None
        return JobPost(
            id=f"in-{job['key']}",
            title=job["title"],
            description=description,
            company_name=job["employer"].get("name") if job.get("employer") else None,
            company_url=(f"{self.base_url}{rel_url}" if job["employer"] else None),
            company_url_direct=(employer["links"]["corporateWebsite"] if employer else None),
            location=Location(
                city=job.get("location", {}).get("city"),
                state=job.get("location", {}).get("admin1Code"),
                country=job.get("location", {}).get("countryCode"),
            ),
            job_type=job_type,
            compensation=self._get_compensation(job["compensation"]),
            date_posted=date_posted,
            job_url=job_url,
            job_url_direct=(job["recruit"].get("viewJobUrl") if job.get("recruit") else None),
            emails=extract_emails_from_text(description) if description else None,
            is_remote=self._is_job_remote(job, description),
            company_addresses=(employer_details["addresses"][0] if employer_details.get("addresses") else None),
            company_industry=(
                employer_details["industry"].replace("Iv1", "").replace("_", " ").title().strip()
                if employer_details.get("industry")
                else None
            ),
            company_num_employees=employer_details.get("employeesLocalizedLabel"),
            company_revenue=employer_details.get("revenueLocalizedLabel"),
            company_description=employer_details.get("briefDescription"),
            company_logo=(employer["images"].get("squareLogoUrl") if employer and employer.get("images") else None),
        )

    @staticmethod
    def _get_job_type(attributes: list[dict[str, str]]) -> list[JobType]:
        """
        Parses the attributes to get list of job types
        :param attributes:
        :return: list of JobType
        """
        job_types: list[JobType] = []
        for attribute in attributes:
            if attribute.get("type") == "jobtype":
                job_type = get_enum_from_job_type(attribute["label"].lower())
                if job_type:
                    job_types.append(job_type)
        return job_types

    @staticmethod
    def _get_compensation(compensation: dict[str, Any] | None) -> Compensation | None:
        """
        Parses the compensation dict into Compensation model
        :param compensation:
        :return: Compensation
        """
        if not compensation:
            return None
        interval = compensation.get("interval")
        if not interval:
            return None
        return Compensation(
            interval=CompensationInterval.get_interval(interval),
            min_amount=compensation.get("min"),
            max_amount=compensation.get("max"),
            currency=compensation.get("currency", "USD"),
        )

    @staticmethod
    def _is_job_remote(job: dict[str, Any], description: str) -> bool:
        """
        Checks if job is remote
        :param job:
        :param description:
        :return: bool
        """
        if job.get("workplaceType") == "REMOTE":
            return True
        if description and ("remote" in description.lower() or "wfh" in description.lower()):
            return True
        return False

    @staticmethod
    def _get_compensation_interval(interval: str) -> CompensationInterval:
        """
        Gets the compensation interval from string
        :param interval:
        :return: CompensationInterval
        """
        interval_mapping: dict[str, CompensationInterval] = {
            "YEARLY": CompensationInterval.YEARLY,
            "MONTHLY": CompensationInterval.MONTHLY,
            "WEEKLY": CompensationInterval.WEEKLY,
            "DAILY": CompensationInterval.DAILY,
            "HOURLY": CompensationInterval.HOURLY,
        }
        if interval not in interval_mapping:
            raise IntervalError(interval, is_compensation=True)
        return interval_mapping[interval]

    def _parse_compensation_interval(self, interval: str) -> CompensationInterval:
        """
        Parses the compensation interval from string
        :param interval:
        :return: CompensationInterval
        """
        if not interval:
            raise IntervalError(interval, is_compensation=True)
        return self._get_compensation_interval(interval)
