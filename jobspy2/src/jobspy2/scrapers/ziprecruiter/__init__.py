"""
jobspy2.scrapers.ziprecruiter
~~~~~~~~~~~~~~~~~~~

This module contains routines to scrape ZipRecruiter.
"""

from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
import logging
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from ...jobs import (
    Compensation,
    Country,
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
    markdown_converter,
    remove_attributes,
)
from .constants import headers



class ZipRecruiterScraper(Scraper):
    base_url = "https://www.ziprecruiter.com"
    api_url = "https://api.ziprecruiter.com"

    def __init__(self, logger: logging.Logger, proxies: list[str] | str | None = None, ca_cert: str | None = None) -> None:
        """
        Initializes ZipRecruiterScraper with the ZipRecruiter job search url
        """
        super().__init__(Site.ZIP_RECRUITER, logger=logger, proxies=proxies, ca_cert=ca_cert)

        self.scraper_input: ScraperInput | None = None
        self.session: requests.Session = create_session(proxies=proxies, ca_cert=ca_cert)
        self.session.headers.update(headers)
        self._get_cookies()

        self.delay: int = 5
        self.jobs_per_page: int = 20
        self.seen_urls: set[str] = set()

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        """
        Scrapes ZipRecruiter for jobs with scraper_input criteria.
        :param scraper_input: Information about job search criteria.
        :return: JobResponse containing a list of jobs.
        """
        self.scraper_input = scraper_input
        job_list: list[JobPost] = []
        continue_token = None

        max_pages = math.ceil(scraper_input.results_wanted / self.jobs_per_page)
        for page in range(1, max_pages + 1):
            if len(job_list) >= scraper_input.results_wanted:
                break
            if page > 1:
                time.sleep(self.delay)
            self.logger.info(f"search page: {page} / {max_pages}")
            jobs_on_page, continue_token = self._find_jobs_in_page(scraper_input, continue_token)
            if jobs_on_page:
                job_list.extend(jobs_on_page)
            else:
                break
            if not continue_token:
                break
        return JobResponse(jobs=job_list[: scraper_input.results_wanted])

    def _find_jobs_in_page(
        self, scraper_input: ScraperInput, continue_token: str | None = None
    ) -> tuple[list[JobPost], str | None]:
        """
        Scrapes a page of ZipRecruiter for jobs with scraper_input criteria
        :param scraper_input:
        :param continue_token:
        :return: jobs found on page
        """
        jobs_list: list[JobPost] = []
        params = self._add_params(scraper_input)
        if continue_token:
            params["continue_from"] = continue_token
        try:
            query_string = urlencode(params)
            full_url = f"{self.api_url}/jobs-app/jobs?{query_string}"	
            self.logger.debug(f"Getting ZipRecruiter URL: {full_url}")
            res = self.session.get(f"{self.api_url}/jobs-app/jobs", params=params)
            if res.status_code not in range(200, 400):
                if res.status_code == 429:
                    self.logger.error("429 Response - Blocked by ZipRecruiter for too many requests")
                    self.logger.debug(res.text)
                else:
                    err = f"ZipRecruiter response status code {res.status_code}"
                    err += f" with response: {res.text}"  # ZipRecruiter likely not available in EU
                    self.logger.error(err)
                return jobs_list, ""
        except Exception as e:
            if "Proxy responded with" in str(e):
                self.logger.exception("ZipRecruiter: Bad proxy")
            else:
                self.logger.exception("ZipRecruiter error")
            return jobs_list, ""

        res_data = res.json()
        jobs_data = res_data.get("jobs", [])
        next_continue_token = res_data.get("continue", None)
        with ThreadPoolExecutor(max_workers=self.jobs_per_page) as executor:
            job_results = [executor.submit(self._process_job, job) for job in jobs_data]

        job_list = list(filter(None, (result.result() for result in job_results)))
        return job_list, next_continue_token

    def _process_job(self, job: dict[str, Any]) -> JobPost | None:
        """
        Processes an individual job dict from the response
        """
        if not self.scraper_input:
            return None
        title = job.get("name") or "N/A"
        job_url = f"{self.base_url}/jobs//j?lvk={job['listing_key']}"
        if job_url in self.seen_urls:
            return None
        self.seen_urls.add(job_url)

        description = job.get("job_description", "").strip()
        listing_type = job.get("buyer_type", "")
        description = (
            markdown_converter(description)
            if self.scraper_input.description_format == DescriptionFormat.MARKDOWN
            else description
        )
        company = job.get("hiring_company", {}).get("name")
        country_value = "usa" if job.get("job_country") == "US" else "canada"
        country_enum = Country.from_string(country_value)

        location = Location(city=job.get("job_city"), state=job.get("job_state"), country=country_enum)
        job_type = self._get_job_type_enum(job.get("employment_type", "").replace("_", "").lower())
        date_posted = datetime.fromisoformat(job["posted_time"].rstrip("Z")).date()
        comp_interval = job.get("compensation_interval")
        comp_interval = "yearly" if comp_interval == "annual" else comp_interval
        comp_min = int(job["compensation_min"]) if "compensation_min" in job else None
        comp_max = int(job["compensation_max"]) if "compensation_max" in job else None
        comp_currency = job.get("compensation_currency")
        description_full, job_url_direct = self._get_descr(job_url)

        return JobPost(
            id=f"zr-{job['listing_key']}",
            title=title,
            company_name=company,
            location=location,
            job_type=job_type,
            compensation=Compensation(
                interval=comp_interval,
                min_amount=comp_min,
                max_amount=comp_max,
                currency=comp_currency,
            ),
            date_posted=date_posted,
            job_url=job_url,
            description=description_full if description_full else description,
            emails=extract_emails_from_text(description) if description else None,
            job_url_direct=job_url_direct,
            listing_type=listing_type,
        )

    def _get_descr(self, job_url: str) -> tuple[str | None, str | None]:
        """
        Gets the full job description and direct job URL from the job page
        :param job_url: The job page URL
        :return: Tuple of (description, direct job URL)
        """
        if not self.scraper_input:
            return None, None
        res = self.session.get(job_url, allow_redirects=True)
        description_full = job_url_direct = None
        if res.ok:
            soup = BeautifulSoup(res.text, "html.parser")
            job_descr_div = soup.find("div", class_="job_description")
            company_descr_section = soup.find("section", class_="company_description")
            job_description_clean = remove_attributes(job_descr_div).prettify(formatter="html") if job_descr_div else ""
            company_description_clean = (
                remove_attributes(company_descr_section).prettify(formatter="html") if company_descr_section else ""
            )
            description_full = job_description_clean + company_description_clean
            script_tag = soup.find("script", type="application/json")
            if script_tag:
                job_json = json.loads(script_tag.string)
                job_url_val = job_json["model"].get("saveJobURL", "")
                m = re.search(r"job_url=(.+)", job_url_val)
                if m:
                    job_url_direct = m.group(1)

            if self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
                description_full = markdown_converter(description_full)

        return description_full, job_url_direct

    def _get_cookies(self) -> None:
        """
        Gets initial cookies from ZipRecruiter
        """
        data = "event_type=session&logged_in=false&number_of_retry=1&property=model%3AiPhone&property=os%3AiOS&property=locale%3Aen_us&property=app_build_number%3A4734&property=app_version%3A91.0&property=manufacturer%3AApple&property=timestamp%3A2024-01-12T12%3A04%3A42-06%3A00&property=screen_height%3A852&property=os_version%3A16.6.1&property=source%3Ainstall&property=screen_width%3A393&property=device_model%3AiPhone%2014%20Pro&property=brand%3AApple"
        url = f"{self.api_url}/jobs-app/event"
        self.session.post(url, data=data)

    @staticmethod
    def _get_job_type_enum(job_type_str: str) -> list[JobType] | None:
        """
        Gets the job type enum from a string
        :param job_type_str: The job type string
        :return: List of JobType enums or None
        """
        for job_type in JobType:
            if job_type_str in job_type.value:
                return [job_type]
        return None

    @staticmethod
    def _add_params(scraper_input: ScraperInput) -> dict[str, str | Any]:
        """
        Adds parameters to the request
        :param scraper_input: The scraper input
        :return: Dictionary of parameters
        """
        params: dict[str, str | Any] = {
            "search": scraper_input.search_term,
            "location": scraper_input.location,
        }
        if scraper_input.hours_old:
            params["days"] = max(scraper_input.hours_old // 24, 1)
        job_type_map: dict[JobType, str] = {JobType.FULL_TIME: "full_time", JobType.PART_TIME: "part_time"}
        if scraper_input.job_type:
            job_type = scraper_input.job_type
            params["employment_type"] = job_type_map.get(job_type, job_type.value[0])
        if scraper_input.easy_apply:
            params["zipapply"] = 1
        if scraper_input.is_remote:
            params["remote"] = 1
        if scraper_input.distance:
            params["radius"] = scraper_input.distance
        return {k: v for k, v in params.items() if v is not None}
