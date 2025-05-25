"""
jobspy2.scrapers.google
~~~~~~~~~~~~~~~~~~~

This module contains routines to scrape Google.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from ...jobs import (
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
    extract_job_type,
)
from .constants import async_param, headers_initial, headers_jobs



class GoogleJobsScraper(Scraper):
    def __init__(self, logger: logging.Logger, proxies: list[str] | str | None = None, ca_cert: str | None = None) -> None:
        """
        Initializes Google Scraper with the Goodle jobs search url
        """
        site = Site(Site.GOOGLE)
        super().__init__(site, logger=logger, proxies=proxies, ca_cert=ca_cert)

        self.country: str | None = None
        self.session: requests.Session | None = None
        self.scraper_input: ScraperInput | None = None
        self.jobs_per_page: int = 10
        self.seen_urls: set[str] = set()
        self.url: str = "https://www.google.com/search"
        self.jobs_url: str = "https://www.google.com/async/callback:550"

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        """
        Scrapes Google for jobs with scraper_input criteria.
        :param scraper_input: Information about job search criteria.
        :return: JobResponse containing a list of jobs.
        """
        self.scraper_input = scraper_input
        self.scraper_input.results_wanted = min(900, scraper_input.results_wanted)

        self.session = create_session(proxies=self.proxies, ca_cert=self.ca_cert, is_tls=False, has_retry=True)
        forward_cursor, job_list = self._get_initial_cursor_and_jobs()
        if forward_cursor is None:
            self.logger.warning("initial cursor not found, try changing your query or there was at most 10 results")
            return JobResponse(jobs=job_list)

        page = 1

        while len(self.seen_urls) < scraper_input.results_wanted + scraper_input.offset and forward_cursor:
            self.logger.info(f"search page: {page} / {math.ceil(scraper_input.results_wanted / self.jobs_per_page)}")
            try:
                jobs, forward_cursor = self._get_jobs_next_page(forward_cursor)
            except Exception:
                self.logger.exception(f"failed to get jobs on page: {page}")
                break
            if not jobs:
                self.logger.info(f"found no jobs on page: {page}")
                break
            job_list += jobs
            page += 1
        return JobResponse(jobs=job_list[scraper_input.offset : scraper_input.offset + scraper_input.results_wanted])

    def _build_search_query(self) -> str:
        """Builds the search query string based on scraper input parameters"""
        if not self.scraper_input:
            return ""
        if self.scraper_input.google_search_term:
            return self.scraper_input.google_search_term

        query = f"{self.scraper_input.search_term} jobs"

        job_type_mapping: dict[JobType, str] = {
            JobType.FULL_TIME: "Full time",
            JobType.PART_TIME: "Part time",
            JobType.INTERNSHIP: "Internship",
            JobType.CONTRACT: "Contract",
        }

        if self.scraper_input.job_type in job_type_mapping:
            query += f" {job_type_mapping[self.scraper_input.job_type]}"

        if self.scraper_input.location:
            query += f" near {self.scraper_input.location}"

        if self.scraper_input.hours_old:
            query += f" {self._get_time_range(self.scraper_input.hours_old)}"

        if self.scraper_input.is_remote:
            query += " remote"

        return query

    @staticmethod
    def _get_time_range(hours_old: int) -> str:
        """Converts hours into human readable time range"""
        if hours_old <= 24:
            return "since yesterday"
        elif hours_old <= 72:
            return "in the last 3 days"
        elif hours_old <= 168:
            return "in the last week"
        return "in the last month"

    def _get_initial_cursor_and_jobs(self) -> tuple[str | None, list[JobPost]]:
        """Gets initial cursor and jobs to paginate through job listings"""
        if not self.session:
            return None, []
        query = self._build_search_query()
        params = {"q": query, "udm": "8"}
        
        # Debug: Log the full URL being visited
        full_url = f"{self.url}?{urlencode(params)}"
        self.logger.debug(f"Visiting initial search URL: {full_url}")
        
        response = self.session.get(self.url, headers=headers_initial, params=params)

        pattern_fc = r'<div jsname="Yust4d"[^>]+data-async-fc="([^"]+)"'
        match_fc = re.search(pattern_fc, response.text)
        data_async_fc = match_fc.group(1) if match_fc else None

        jobs_raw = self._find_job_info_initial_page(response.text, self.logger)
        jobs: list[JobPost] = []
        for job_raw in jobs_raw:
            job_post = self._parse_job(job_raw)
            if job_post:
                jobs.append(job_post)
        return data_async_fc, jobs

    def _get_jobs_next_page(self, forward_cursor: str) -> tuple[list[JobPost], str | None]:
        if not self.session:
            return [], None
        params = {"fc": [forward_cursor], "fcv": ["3"], "async": [async_param]}
        
        # Debug: Log the full URL being visited
        full_url = f"{self.jobs_url}?{urlencode(params, doseq=True)}"
        self.logger.debug(f"Visiting next page URL: {full_url}")
        
        response = self.session.get(self.jobs_url, headers=headers_jobs, params=params)
        return self._parse_jobs(response.text)

    def _parse_jobs(self, job_data: str) -> tuple[list[JobPost], str | None]:
        """
        Parses jobs on a page with next page cursor
        """
        start_idx = job_data.find("[[[")
        end_idx = job_data.rindex("]]]") + 3
        s = job_data[start_idx:end_idx]
        parsed = json.loads(s)[0]

        pattern_fc = r'data-async-fc="([^"]+)"'
        match_fc = re.search(pattern_fc, job_data)
        data_async_fc = match_fc.group(1) if match_fc else None
        jobs_on_page: list[JobPost] = []
        for array in parsed:
            _, job_data = array
            if not job_data.startswith("[[["):
                continue
            job_d = json.loads(job_data)

            job_info = self._find_job_info(job_d)
            if not job_info:
                continue
            job_post = self._parse_job(job_info)
            if job_post:
                jobs_on_page.append(job_post)
        return jobs_on_page, data_async_fc

    def _parse_job(self, job_info: list[Any]) -> JobPost | None:
        job_url = job_info[3][0][0] if job_info[3] and job_info[3][0] else None
        if not job_url or job_url in self.seen_urls:
            return None
        self.seen_urls.add(job_url)

        title = job_info[0]
        company_name = job_info[1]
        location = city = job_info[2]
        state = country = date_posted = None
        if location and "," in location:
            city, state, *country = (x.strip() for x in location.split(","))

        days_ago_str = job_info[12]
        if isinstance(days_ago_str, str):
            match = re.search(r"\d+", days_ago_str)
            days_ago = int(match.group()) if match else None
            date_posted = (datetime.now() - timedelta(days=days_ago)).date() if days_ago else None

        description = job_info[19]

        return JobPost(
            id=f"go-{job_info[28]}",
            title=title,
            company_name=company_name,
            location=Location(city=city, state=state, country=country[0] if country else None),
            job_url=job_url,
            date_posted=date_posted,
            is_remote="remote" in description.lower() or "wfh" in description.lower(),
            description=description,
            emails=extract_emails_from_text(description),
            job_type=extract_job_type(description),
        )

    @staticmethod
    def _find_job_info(jobs_data: list[Any] | dict[str, Any]) -> list[Any] | None:
        """Iterates through the JSON data to find the job listings"""
        if isinstance(jobs_data, dict):
            for key, value in jobs_data.items():
                if key == "520084652" and isinstance(value, list):
                    return value
                else:
                    result = GoogleJobsScraper._find_job_info(value)
                    if result:
                        return result
        elif isinstance(jobs_data, list):
            for item in jobs_data:
                result = GoogleJobsScraper._find_job_info(item)
                if result:
                    return result
        return None

    @staticmethod
    def _find_job_info_initial_page(html_text: str, logger: logging.Logger) -> list[Any]:
        pattern = '520084652":(' + r"\[.*?\]\s*])\s*}\s*]\s*]\s*]"
        results: list[Any] = []
        matches = re.finditer(pattern, html_text)

        for match in matches:
            try:
                parsed_data = json.loads(match.group(1))
                results.append(parsed_data)

            except json.JSONDecodeError as e:
                logger.exception("Failed to parse match")
                results.append({"raw_match": match.group(0), "error": str(e)})
        return results
