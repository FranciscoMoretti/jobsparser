"""
jobspy2.scrapers.linkedin
~~~~~~~~~~~~~~~~~~~

This module contains routines to scrape LinkedIn.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse, urlencode
import logging

import regex as re
import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from ...jobs import (
    Compensation,
    Country,
    DescriptionFormat,
    JobPost,
    JobResponse,
    JobType,
    Location,
)
from .. import LinkedInExperienceLevel, Scraper, ScraperInput, Site
from ..exceptions import LinkedInException
from ..utils import (
    create_logger,
    create_session,
    currency_parser,
    extract_emails_from_text,
    get_enum_from_job_type,
    markdown_converter,
    remove_attributes,
)
from .constants import headers


# Map from experience level to the number
experience_level_map: dict[LinkedInExperienceLevel, str] = {
    LinkedInExperienceLevel.INTERNSHIP: "1",
    LinkedInExperienceLevel.ENTRY_LEVEL: "2",
    LinkedInExperienceLevel.ASSOCIATE: "3",
    LinkedInExperienceLevel.MID_SENIOR_LEVEL: "4",
    LinkedInExperienceLevel.DIRECTOR: "5",
    LinkedInExperienceLevel.EXECUTIVE: "6",
}


class LinkedInScraper(Scraper):
    base_url = "https://www.linkedin.com"
    delay = 3
    band_delay = 4
    jobs_per_page = 25

    def __init__(self, logger: logging.Logger, proxies: list[str] | str | None = None, ca_cert: str | None = None) -> None:
        """
        Initializes LinkedInScraper with the LinkedIn job search url
        """
        super().__init__(Site.LINKEDIN, logger=logger, proxies=proxies, ca_cert=ca_cert)

        self.session = create_session(
            proxies=self.proxies,
            ca_cert=ca_cert,
            is_tls=False,
            has_retry=True,
            delay=5,
            clear_cookies=True,
        )
        self.session.headers.update(headers)
        self.scraper_input: ScraperInput | None = None
        self.country: str = "worldwide"
        self.job_url_direct_regex = re.compile(r'(?<=\?url=)[^"]+')

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        """
        Scrapes LinkedIn for jobs with scraper_input criteria
        """
        self.scraper_input = scraper_input
        job_list: list[JobPost] = []
        seen_ids: set[str] = set()
        start = scraper_input.offset // 10 * 10 if scraper_input.offset else 0
        request_count = 0
        seconds_old = scraper_input.hours_old * 3600 if scraper_input.hours_old else None

        while self._should_continue_search(job_list, start):
            request_count += 1
            self.logger.info(f"search page: {request_count} / {math.ceil(scraper_input.results_wanted / 10)}")

            response = self._make_search_request(start, seconds_old)
            if not response:
                return JobResponse(jobs=job_list)

            job_cards = self._get_job_cards(response)
            if not job_cards:
                return JobResponse(jobs=job_list)

            if not self._process_job_cards(job_cards, job_list, seen_ids):
                break

            if self._should_continue_search(job_list, start):
                time.sleep(random.uniform(self.delay, self.delay + self.band_delay))  # noqa: S311
                start += len(job_list)

        job_list = job_list[: self.scraper_input.results_wanted]
        return JobResponse(jobs=job_list)

    def _should_continue_search(self, job_list: list[JobPost], start: int) -> bool:
        if not self.scraper_input:
            return False
        return len(job_list) < self.scraper_input.results_wanted and start < 1000

    def _make_search_request(self, start: int, seconds_old: int | None) -> requests.Response | None:
        if not self.scraper_input:
            return None
        params = self._build_search_params(start, seconds_old)
        query_string = urlencode(params)
        full_url = f"{self.base_url}/jobs-guest/jobs/api/seeMoreJobPostings/search?{query_string}"
        try:
            self.logger.debug(f"Getting Linkedin URL: {full_url}")

            response = self.session.get(
                f"{self.base_url}/jobs-guest/jobs/api/seeMoreJobPostings/search",
                params=params,
                timeout=10,
            )
            if response.status_code not in range(200, 400):
                err = (
                    "429 Response - Blocked by LinkedIn for too many requests"
                    if response.status_code == 429
                    else f"LinkedIn response status code {response.status_code} - {response.text}"
                )
                self.logger.error(err)
                return None
            else:
                return response
        except Exception as e:
            if "Proxy responded with" in str(e):
                self.logger.exception("LinkedIn: Bad proxy")
            else:
                self.logger.exception("LinkedIn error")
            return None

    def _build_search_params(self, start: int, seconds_old: int | None) -> dict[str, Any]:
        if not self.scraper_input:
            return {}
        params: dict[str, Any] = {
            "keywords": self.scraper_input.search_term,
            "location": self.scraper_input.location,
            "distance": self.scraper_input.distance,
            "f_WT": 2 if self.scraper_input.is_remote else None,
            "f_E": ",".join(
                experience_level_map.get(level, "") for level in self.scraper_input.linkedin_experience_levels
            )
            if self.scraper_input.linkedin_experience_levels
            else None,
            "f_JT": (self.job_type_code(self.scraper_input.job_type) if self.scraper_input.job_type else None),
            "pageNum": 0,
            "start": start,
            "f_AL": "true" if self.scraper_input.easy_apply else None,
            "f_C": (
                ",".join(map(str, self.scraper_input.linkedin_company_ids))
                if self.scraper_input.linkedin_company_ids
                else None
            ),
        }
        if seconds_old is not None:
            params["f_TPR"] = f"r{seconds_old}"
        return {k: v for k, v in params.items() if v is not None}

    def _get_job_cards(self, response: requests.Response) -> list[Tag]:
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.find_all("div", class_="base-search-card")

    def _process_job_cards(self, job_cards: list[Tag], job_list: list[JobPost], seen_ids: set[str]) -> bool:
        if not self.scraper_input:
            return False
        for job_card in job_cards:
            href_tag = job_card.find("a", class_="base-card__full-link")
            if not href_tag or not isinstance(href_tag, Tag):
                continue
            if "href" not in href_tag.attrs:
                continue

            href = href_tag.attrs["href"].split("?")[0]
            job_id = href.split("-")[-1]

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            try:
                fetch_desc = self.scraper_input.linkedin_fetch_description
                job_post = self._process_job(job_card, job_id, fetch_desc)
                if job_post:
                    job_list.append(job_post)
                if not self._should_continue_search(job_list, 0):
                    return False
            except Exception as err:
                raise LinkedInException() from err
        return True

    def _process_job(self, job_card: Tag, job_id: str, full_descr: bool) -> JobPost | None:
        salary_tag = job_card.find("span", class_="job-search-card__salary-info")

        compensation = None
        if salary_tag:
            salary_text = salary_tag.get_text(separator=" ").strip()
            salary_values = [currency_parser(value) for value in salary_text.split("-")]
            salary_min = salary_values[0]
            salary_max = salary_values[1]
            currency = salary_text[0] if salary_text[0] != "$" else "USD"

            compensation = Compensation(
                min_amount=int(salary_min),
                max_amount=int(salary_max),
                currency=currency,
            )

        title_tag = job_card.find("span", class_="sr-only")
        title = title_tag.get_text(strip=True) if title_tag else "N/A"

        company_tag = job_card.find("h4", class_="base-search-card__subtitle")
        company_a_tag = company_tag.find("a") if company_tag else None
        if not company_a_tag or not isinstance(company_a_tag, Tag):
            return None
        company_url = urlunparse(urlparse(href)._replace(query="")) if (href := company_a_tag.get("href")) else ""
        company = company_a_tag.get_text(strip=True) if company_a_tag else "N/A"

        metadata_card = job_card.find("div", class_="base-search-card__metadata")
        location = self._get_location(metadata_card)

        datetime_tag = metadata_card.find("time", class_="job-search-card__listdate") if metadata_card else None
        date_posted = None
        if datetime_tag and "datetime" in datetime_tag.attrs:
            datetime_str = datetime_tag["datetime"]
            try:
                date_posted = self._parse_date(datetime_str)
            except ValueError as e:
                self.logger.warning(f"Failed to parse date {datetime_str}: {e}")
        job_details: dict[str, Any] = {}
        if full_descr:
            job_details = self._get_job_details(job_id)

        return JobPost(
            id=f"li-{job_id}",
            title=title,
            company_name=company,
            company_url=company_url,
            location=location,
            date_posted=date_posted,
            job_url=f"{self.base_url}/jobs/view/{job_id}",
            compensation=compensation,
            job_type=job_details.get("job_type"),
            job_level=job_details.get("job_level", "").lower(),
            company_industry=job_details.get("company_industry"),
            description=job_details.get("description"),
            job_url_direct=job_details.get("job_url_direct"),
            emails=extract_emails_from_text(job_details.get("description")),
        )

    def _get_job_details(self, job_id: str) -> dict[str, Any]:
        """
        Retrieves job description and other job details by going to the job page url
        :param job_page_url:
        :return: dict
        """
        if not self.scraper_input:
            return {}
        try:
            response = self.session.get(f"{self.base_url}/jobs/view/{job_id}", timeout=5)
            response.raise_for_status()
        except (requests.RequestException, TimeoutError) as e:
            self.logger.warning(f"Failed to get job details: {e}")
            return {}
        if "linkedin.com/signup" in response.url:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        div_content = soup.find("div", class_=lambda x: x and "show-more-less-html__markup" in x)
        description = None
        if div_content is not None:
            div_content = remove_attributes(div_content)
            description = div_content.prettify(formatter="html")
            if self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
                description = markdown_converter(description)

        h3_tag = soup.find("h3", text=lambda text: text and "Job function" in text.strip())

        job_function = None
        if h3_tag:
            job_function_span = h3_tag.find_next("span", class_="description__job-criteria-text")
            if job_function_span:
                job_function = job_function_span.text.strip()

        company_logo = (
            logo_image.get("data-delayed-url")
            if (logo_image := soup.find("img", {"class": "artdeco-entity-image"}))
            else None
        )
        return {
            "description": description,
            "job_level": self._parse_job_level(soup),
            "company_industry": self._parse_company_industry(soup),
            "job_type": self._parse_job_type(soup),
            "job_url_direct": self._parse_job_url_direct(soup),
            "company_logo": company_logo,
            "job_function": job_function,
        }

    def _get_location(self, metadata_card: Tag | None) -> Location:
        """
        Extracts the location data from the job metadata card.
        :param metadata_card
        :return: location
        """
        location = Location(country=Country.from_string(self.country))
        if metadata_card is not None:
            location_tag = metadata_card.find("span", class_="job-search-card__location")
            location_string = location_tag.text.strip() if location_tag else "N/A"
            parts = location_string.split(", ")
            if len(parts) == 2:
                city, state = parts
                location = Location(
                    city=city,
                    state=state,
                    country=Country.from_string(self.country),
                )
            elif len(parts) == 3:
                city, state, country = parts
                country = Country.from_string(country)
                location = Location(city=city, state=state, country=country)
        return location

    @staticmethod
    def _parse_job_type(soup_job_type: BeautifulSoup) -> list[JobType]:
        """
        Gets the job type from job page
        :param soup_job_type:
        :return: JobType
        """
        h3_tag = soup_job_type.find(
            "h3",
            class_="description__job-criteria-subheader",
            string=lambda text: "Employment type" in text,
        )
        employment_type = None
        if h3_tag:
            employment_type_span = h3_tag.find_next_sibling(
                "span",
                class_="description__job-criteria-text description__job-criteria-text--criteria",
            )
            if employment_type_span:
                employment_type = employment_type_span.get_text(strip=True)
                employment_type = employment_type.lower()
                employment_type = employment_type.replace("-", "")

        return [get_enum_from_job_type(employment_type)] if employment_type else []

    @staticmethod
    def _parse_job_level(soup_job_level: BeautifulSoup) -> str | None:
        """
        Gets the job level from job page
        :param soup_job_level:
        :return: str
        """
        h3_tag = soup_job_level.find(
            "h3",
            class_="description__job-criteria-subheader",
            string=lambda text: "Seniority level" in text,
        )
        job_level = None
        if h3_tag:
            job_level_span = h3_tag.find_next_sibling(
                "span",
                class_="description__job-criteria-text description__job-criteria-text--criteria",
            )
            if job_level_span:
                job_level = job_level_span.get_text(strip=True)

        return job_level

    @staticmethod
    def _parse_company_industry(soup_industry: BeautifulSoup) -> str | None:
        """
        Gets the company industry from job page
        :param soup_industry:
        :return: str
        """
        h3_tag = soup_industry.find(
            "h3",
            class_="description__job-criteria-subheader",
            string=lambda text: "Industries" in text,
        )
        industry = None
        if h3_tag:
            industry_span = h3_tag.find_next_sibling(
                "span",
                class_="description__job-criteria-text description__job-criteria-text--criteria",
            )
            if industry_span:
                industry = industry_span.get_text(strip=True)

        return industry

    def _parse_job_url_direct(self, soup: BeautifulSoup) -> str | None:
        """
        Gets the job url direct from job page
        :param soup:
        :return: str
        """
        job_url_direct = None
        job_url_direct_content = soup.find("code", id="applyUrl")
        if job_url_direct_content:
            job_url_direct_match = self.job_url_direct_regex.search(job_url_direct_content.decode_contents().strip())
            if job_url_direct_match:
                job_url_direct = unquote(job_url_direct_match.group())

        return job_url_direct

    @staticmethod
    def job_type_code(job_type_enum: JobType) -> str:
        return {
            JobType.FULL_TIME: "F",
            JobType.PART_TIME: "P",
            JobType.INTERNSHIP: "I",
            JobType.CONTRACT: "C",
            JobType.TEMPORARY: "T",
        }.get(job_type_enum, "")

    def _parse_date(self, datetime_str: str) -> datetime | None:
        try:
            return datetime.strptime(datetime_str, "%Y-%m-%d")
        except ValueError as e:
            self.logger.warning(f"Failed to parse date {datetime_str}: {e}")
            return None
