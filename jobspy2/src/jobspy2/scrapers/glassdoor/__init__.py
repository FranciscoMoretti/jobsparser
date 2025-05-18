"""
jobspy2.scrapers.glassdoor
~~~~~~~~~~~~~~~~~~~

This module contains routines to scrape Glassdoor.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

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
from ..exceptions import GlassdoorException, GlassdoorLocationError
from ..utils import (
    create_logger,
    create_session,
    extract_emails_from_text,
    markdown_converter,
)
from .constants import fallback_token, headers, query_template



class GlassdoorAPIError(GlassdoorException):
    """Raised when the Glassdoor API returns an error."""

    BAD_STATUS = "Bad response status code: {}"
    API_ERROR = "Error encountered in API response"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class GlassdoorScraper(Scraper):
    def __init__(self, logger: logging.Logger, proxies: list[str] | str | None = None, ca_cert: str | None = None) -> None:
        """
        Initializes GlassdoorScraper with the Glassdoor job search url
        """
        site = Site(Site.GLASSDOOR)
        super().__init__(site, logger=logger, proxies=proxies, ca_cert=ca_cert)

        self.base_url: str | None = None
        self.country: str | None = None
        self.session: requests.Session | None = None
        self.scraper_input: ScraperInput | None = None
        self.jobs_per_page: int = 30
        self.max_pages: int = 30
        self.seen_urls: set[str] = set()

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        """
        Scrapes Glassdoor for jobs with scraper_input criteria.
        :param scraper_input: Information about job search criteria.
        :return: JobResponse containing a list of jobs.
        """
        self.scraper_input = scraper_input
        self.scraper_input.results_wanted = min(900, scraper_input.results_wanted)
        self.base_url = self.scraper_input.country.get_glassdoor_url()

        self.session = create_session(proxies=self.proxies, ca_cert=self.ca_cert, is_tls=True, has_retry=True)
        token = self._get_csrf_token()
        headers["gd-csrf-token"] = token if token else fallback_token
        self.session.headers.update(headers)

        location_id, location_type = self._get_location(scraper_input.location, scraper_input.is_remote)
        if location_type is None:
            self.logger.error("Glassdoor: location not parsed")
            return JobResponse(jobs=[])
        job_list: list[JobPost] = []
        cursor = None

        range_start = 1 + (scraper_input.offset // self.jobs_per_page)
        tot_pages = (scraper_input.results_wanted // self.jobs_per_page) + 2
        range_end = min(tot_pages, self.max_pages + 1)
        for page in range(range_start, range_end):
            self.logger.info(f"search page: {page} / {range_end - 1}")
            try:
                jobs, cursor = self._fetch_jobs_page(scraper_input, location_id, location_type, page, cursor)
                job_list.extend(jobs)
                if not jobs or len(job_list) >= scraper_input.results_wanted:
                    job_list = job_list[: scraper_input.results_wanted]
                    break
            except Exception:
                self.logger.exception("Glassdoor error")
                break
        return JobResponse(jobs=job_list)

    def _raise_for_status(self, response: requests.Response) -> dict[str, Any]:
        """Handle error responses from Glassdoor API."""
        if response.status_code != 200:
            raise GlassdoorAPIError(GlassdoorAPIError.BAD_STATUS.format(response.status_code))
        res_json = response.json()[0]
        if "errors" in res_json:
            raise GlassdoorAPIError(GlassdoorAPIError.API_ERROR)
        return res_json

    def _fetch_jobs_page(
        self,
        scraper_input: ScraperInput,
        location_id: int,
        location_type: str,
        page_num: int,
        cursor: str | None,
    ) -> tuple[list[JobPost], str | None]:
        """
        Scrapes a page of Glassdoor for jobs with scraper_input criteria
        """
        jobs: list[JobPost] = []
        self.scraper_input = scraper_input
        try:
            payload = self._add_payload(location_id, location_type, page_num, cursor)
            response = self.session.post(
                f"{self.base_url}/graph",
                timeout=15,
                data=payload,
            )
            res_json = self._raise_for_status(response)
        except Exception:
            self.logger.exception("Glassdoor error")
            return jobs, None

        jobs_data = res_json["data"]["jobListings"]["jobListings"]

        with ThreadPoolExecutor(max_workers=self.jobs_per_page) as executor:
            future_to_job_data = {executor.submit(self._process_job, job): job for job in jobs_data}
            for future in as_completed(future_to_job_data):
                try:
                    job_post = future.result()
                    if job_post:
                        jobs.append(job_post)
                except Exception as exc:
                    raise GlassdoorException(GlassdoorException.JOB_PROCESSING_FAILED) from exc

        return jobs, self.get_cursor_for_page(res_json["data"]["jobListings"]["paginationCursors"], page_num + 1)

    def _get_csrf_token(self) -> str | None:
        """
        Fetches csrf token needed for API by visiting a generic page
        """
        if not self.session or not self.base_url:
            return None
        res = self.session.get(f"{self.base_url}/Job/computer-science-jobs.htm")
        pattern = r'"token":\s*"([^"]+)"'
        matches = re.findall(pattern, res.text)
        token = None
        if matches:
            token = matches[0]
        return token

    def _process_job(self, job_data: dict[str, Any]) -> JobPost | None:
        """
        Processes a single job and fetches its description.
        """
        if not self.base_url:
            return None
        job_id = job_data["jobview"]["job"]["listingId"]
        job_url = f"{self.base_url}job-listing/j?jl={job_id}"
        if job_url in self.seen_urls:
            return None
        self.seen_urls.add(job_url)
        job = job_data["jobview"]
        title = job["job"]["jobTitleText"]
        company_name = job["header"]["employerNameFromSearch"]
        company_id = job_data["jobview"]["header"]["employer"]["id"]
        location_name = job["header"].get("locationName", "")
        location_type = job["header"].get("locationType", "")
        age_in_days = job["header"].get("ageInDays")
        is_remote, location = False, None
        date_diff = (datetime.now() - timedelta(days=age_in_days)).date() if age_in_days is not None else None
        date_posted = date_diff if age_in_days is not None else None

        if location_type == "S":
            is_remote = True
        else:
            location = self.parse_location(location_name)

        compensation = self.parse_compensation(job["header"])
        description = None
        try:
            description = self._fetch_job_description(job_id)
        except Exception:
            self.logger.exception("Failed to fetch job description")

        company_url = f"{self.base_url}Overview/W-EI_IE{company_id}.htm"
        company_logo = job_data["jobview"].get("overview", {}).get("squareLogoUrl", None)
        listing_type = job_data["jobview"].get("header", {}).get("adOrderSponsorshipLevel", "").lower()
        return JobPost(
            id=f"gd-{job_id}",
            title=title,
            company_url=company_url if company_id else None,
            company_name=company_name,
            date_posted=date_posted,
            job_url=job_url,
            location=location,
            compensation=compensation,
            is_remote=is_remote,
            description=description,
            emails=extract_emails_from_text(description) if description else None,
            company_logo=company_logo,
            listing_type=listing_type,
        )

    def _fetch_job_description(self, job_id: str) -> str | None:
        """
        Fetches the job description for a single job ID.
        """
        if not self.base_url or not self.scraper_input:
            return None
        url = f"{self.base_url}/graph"
        body = [
            {
                "operationName": "JobDetailQuery",
                "variables": {
                    "jl": job_id,
                    "queryString": "q",
                    "pageTypeEnum": "SERP",
                },
                "query": """
                query JobDetailQuery($jl: Long!, $queryString: String, $pageTypeEnum: PageTypeEnum) {
                    jobview: jobView(
                        listingId: $jl
                        contextHolder: {queryString: $queryString, pageTypeEnum: $pageTypeEnum}
                    ) {
                        job {
                            description
                            __typename
                        }
                        __typename
                    }
                }
                """,
            }
        ]
        res = requests.post(url, json=body, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        data = res.json()[0]
        desc = data["data"]["jobview"]["job"]["description"]
        if self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
            desc = markdown_converter(desc)
        return desc

    def _get_location(self, location: str | None, is_remote: bool) -> tuple[int, str]:
        """
        Gets the location ID and type from Glassdoor.
        """
        if not self.base_url or not self.session:
            raise GlassdoorException("Session not initialized")
        if is_remote:
            return 0, "REMOTE"
        if not location:
            return 0, "ANYWHERE"
        try:
            params = {"term": location}
            query_string = urlencode(params)
            full_url = f'{self.base_url}findPopularLocationAjax.htm?{query_string}'
            self.logger.debug(f"Getting Glassdoor location: {full_url}")
            response = self.session.get(
                f'{self.base_url}findPopularLocationAjax.htm?',
                params=params,
            )
            if response.status_code != 200:
                raise GlassdoorException(f'{response.status_code} {response.text}')
            locations = response.json()
            if not locations:
                raise GlassdoorLocationError(location)
            return locations[0]["locationId"], locations[0]["locationType"]
        except Exception as e:
            raise GlassdoorException() from e

    def _add_payload(
        self,
        location_id: int,
        location_type: str,
        page_num: int,
        cursor: str | None = None,
    ) -> str:
        """
        Adds the payload to the request.
        """
        if not self.scraper_input:
            raise GlassdoorException("Scraper input not initialized")
        variables = {
            "excludeJobListingIds": [],
            "filterParams": [
                {"filterKey": "locId", "filterType": location_type, "filterValue": location_id},
            ],
            "numJobsToShow": self.jobs_per_page,
            "pageNumber": page_num,
            "searchText": self.scraper_input.search_term,
        }
        if cursor:
            variables["cursor"] = cursor
        if self.scraper_input.hours_old:
            variables["filterParams"].append({
                "filterKey": "postedDate",
                "filterType": "FILTER_DATE_POSTED",
                "filterValue": f"{self.scraper_input.hours_old}",
            })
        if self.scraper_input.easy_apply:
            variables["filterParams"].append({"filterKey": "easyApply", "filterType": "BVAL", "filterValue": "true"})
        if self.scraper_input.job_type:
            variables["filterParams"].append({
                "filterKey": "jobType",
                "filterType": "BVAL",
                "filterValue": self.scraper_input.job_type[0].value[0],
            })
        return json.dumps([{"operationName": "JobSearchResultsQuery", "variables": variables, "query": query_template}])

    @staticmethod
    def parse_compensation(data: dict[str, Any]) -> Compensation | None:
        """
        Parses the compensation data from the job header.
        """
        if not data.get("salarySource"):
            return None
        salary = data["salarySource"]
        if not salary.get("payCurrency") or not salary.get("payPeriod"):
            return None
        return Compensation(
            interval=CompensationInterval.get_interval(salary["payPeriod"]),
            min_amount=salary.get("payMin"),
            max_amount=salary.get("payMax"),
            currency=salary["payCurrency"],
        )

    @staticmethod
    def get_job_type_enum(job_type_str: str) -> list[JobType] | None:
        """
        Gets the job type enum from a string.
        """
        return [JobType.FULL_TIME] if job_type_str == "fulltime" else None

    @staticmethod
    def parse_location(location_name: str) -> Location | None:
        """
        Parses the location string into a Location object.
        """
        if not location_name:
            return None
        parts = location_name.split(", ")
        return Location(city=parts[0], state=parts[1] if len(parts) > 1 else None)

    @staticmethod
    def get_cursor_for_page(pagination_cursors: list[dict[str, str]], page_num: int) -> str | None:
        """
        Gets the cursor for the next page.
        """
        for cursor in pagination_cursors:
            if cursor["pageNumber"] == page_num:
                return cursor["cursor"]
        return None
