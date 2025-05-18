from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

import pandas as pd

from .jobs import JobType, Location
from .scrapers import Country, JobResponse, LinkedInExperienceLevel, SalarySource, ScraperInput, Site
from .scrapers.exceptions import (
    GlassdoorException as GlassdoorException,
)
from .scrapers.exceptions import (
    GoogleJobsException as GoogleJobsException,
)
from .scrapers.exceptions import (
    IndeedException as IndeedException,
)
from .scrapers.exceptions import (
    LinkedInException as LinkedInException,
)
from .scrapers.exceptions import (
    ZipRecruiterException as ZipRecruiterException,
)
from .scrapers.glassdoor import GlassdoorScraper
from .scrapers.google import GoogleJobsScraper
from .scrapers.indeed import IndeedScraper
from .scrapers.linkedin import LinkedInScraper
from .scrapers.utils import create_logger, extract_salary
from .scrapers.ziprecruiter import ZipRecruiterScraper


class JobTypeError(Exception):
    """Raised when an invalid job type is provided."""

    def __init__(self, value_str: str):
        self.message = f"Invalid job type: {value_str}"
        super().__init__(self.message)


def _get_enum_from_value(value_str: str | None) -> JobType | None:
    if not value_str:
        return None
    for job_type in JobType:
        if value_str in job_type.value:
            return job_type
    raise JobTypeError(value_str)


def _get_site_type(site_name: str | list[str] | Site | list[Site] | None) -> list[Site]:
    site_types = list(Site)
    if isinstance(site_name, str):
        site_types = [Site[site_name.upper()]]
    elif isinstance(site_name, Site):
        site_types = [site_name]
    elif isinstance(site_name, list):
        site_types = [Site[site.upper()] if isinstance(site, str) else site for site in site_name]
    return site_types


def _convert_to_annual(job_data: dict) -> None:
    multipliers = {"hourly": 2080, "monthly": 12, "weekly": 52, "daily": 260}
    interval = job_data["interval"]
    if interval in multipliers:
        multiplier = multipliers[interval]
        job_data["min_amount"] *= multiplier
        job_data["max_amount"] *= multiplier
        job_data["interval"] = "yearly"


def _process_job_data(job_data: dict, enforce_annual_salary: bool, country_enum: Country) -> dict:
    job_url = job_data["job_url"]
    job_data["job_url_hyper"] = f'<a href="{job_url}">{job_url}</a>'
    job_data["company"] = job_data["company_name"]

    if job_data["job_type"]:
        job_data["job_type"] = ", ".join(job_type.value[0] for job_type in job_data["job_type"])

    if job_data["emails"]:
        job_data["emails"] = ", ".join(job_data["emails"])

    if job_data["location"]:
        job_data["location"] = Location(**job_data["location"]).display_location()

    compensation_obj = job_data.get("compensation")
    if compensation_obj and isinstance(compensation_obj, dict):
        job_data["interval"] = compensation_obj.get("interval").value if compensation_obj.get("interval") else None
        job_data["min_amount"] = compensation_obj.get("min_amount")
        job_data["max_amount"] = compensation_obj.get("max_amount")
        job_data["currency"] = compensation_obj.get("currency", "USD")
        job_data["salary_source"] = SalarySource.DIRECT_DATA.value

        if (
            enforce_annual_salary
            and job_data["interval"]
            and job_data["interval"] != "yearly"
            and job_data["min_amount"]
            and job_data["max_amount"]
        ):
            _convert_to_annual(job_data)
    elif country_enum == Country.USA:
        job_data["interval"], job_data["min_amount"], job_data["max_amount"], job_data["currency"] = extract_salary(
            job_data["description"],
            enforce_annual_salary=enforce_annual_salary,
        )
        job_data["salary_source"] = SalarySource.DESCRIPTION.value

    job_data["salary_source"] = job_data["salary_source"] if job_data.get("min_amount") else None
    return job_data


def scrape_jobs(
    site_name: str | list[str] | Site | list[Site] | None = None,
    search_term: str | None = None,
    google_search_term: str | None = None,
    location: str | None = None,
    distance: int | None = 50,
    is_remote: bool = False,
    job_type: str | None = None,
    easy_apply: bool | None = None,
    results_wanted: int = 15,
    country_indeed: str = "usa",
    hyperlinks: bool = False,
    proxies: list[str] | str | None = None,
    ca_cert: str | None = None,
    description_format: str = "markdown",
    linkedin_fetch_description: bool | None = False,
    linkedin_company_ids: list[int] | None = None,
    linkedin_experience_levels: list[LinkedInExperienceLevel] | None = None,
    offset: int | None = 0,
    hours_old: int | None = None,
    enforce_annual_salary: bool = False,
    logger: logging.Logger | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Simultaneously scrapes job data from multiple job sites.
    :return: pandas dataframe containing job data
    """
    SCRAPER_MAPPING = {
        Site.LINKEDIN: LinkedInScraper,
        Site.INDEED: IndeedScraper,
        Site.ZIP_RECRUITER: ZipRecruiterScraper,
        Site.GLASSDOOR: GlassdoorScraper,
        Site.GOOGLE: GoogleJobsScraper,
    }

    job_type_enum = _get_enum_from_value(job_type)
    country_enum = Country.from_string(country_indeed)
    site_types = _get_site_type(site_name)

    scraper_input = ScraperInput(
        site_type=site_types,
        country=country_enum,
        search_term=search_term,
        google_search_term=google_search_term,
        location=location,
        distance=distance,
        is_remote=is_remote,
        job_type=job_type_enum,
        easy_apply=easy_apply,
        description_format=description_format,
        linkedin_fetch_description=linkedin_fetch_description,
        results_wanted=results_wanted,
        linkedin_company_ids=linkedin_company_ids,
        linkedin_experience_levels=linkedin_experience_levels,
        offset=offset,
        hours_old=hours_old,
        logger=logger,
    )

    def scrape_site(site: Site) -> tuple[str, JobResponse]:
        scraper_class = SCRAPER_MAPPING[site]
        site_logger = logger if logger else create_logger(site.value)
        scraper = scraper_class(logger=site_logger, proxies=proxies, ca_cert=ca_cert)
        scraped_data: JobResponse = scraper.scrape(scraper_input)
        site_name_display = site.value.capitalize().replace("_", "") # e.g. ZipRecruiter
        site_logger.info(f"{site_name_display} scrape processing completed by scrape_site wrapper.")
        return site.value, scraped_data

    site_to_jobs_dict = {}
    with ThreadPoolExecutor() as executor:
        future_to_site = {executor.submit(scrape_site, site): site for site in scraper_input.site_type}
        for future in as_completed(future_to_site):
            site_value, scraped_data = future.result()
            site_to_jobs_dict[site_value] = scraped_data

    jobs_dfs = []
    for site, job_response in site_to_jobs_dict.items():
        for job in job_response.jobs:
            job_data = job.dict()
            job_data["site"] = site
            processed_job = _process_job_data(job_data, enforce_annual_salary, country_enum)
            jobs_dfs.append(pd.DataFrame([processed_job]))

    if not jobs_dfs:
        return pd.DataFrame()

    # Filter out all-NA columns from each DataFrame before concatenation
    filtered_dfs = [df.dropna(axis=1, how="all") for df in jobs_dfs]
    jobs_df = pd.concat(filtered_dfs, ignore_index=True)

    # Desired column order
    desired_order = [
        "id",
        "site",
        "job_url_hyper" if hyperlinks else "job_url",
        "job_url_direct",
        "title",
        "company",
        "location",
        "date_posted",
        "job_type",
        "salary_source",
        "interval",
        "min_amount",
        "max_amount",
        "currency",
        "is_remote",
        "job_level",
        "job_function",
        "listing_type",
        "emails",
        "description",
        "company_industry",
        "company_url",
        "company_logo",
        "company_url_direct",
        "company_addresses",
        "company_num_employees",
        "company_revenue",
        "company_description",
    ]

    # Ensure all desired columns are present, adding missing ones as empty
    for column in desired_order:
        if column not in jobs_df.columns:
            jobs_df[column] = None

    # Reorder and sort the DataFrame
    jobs_df = jobs_df[desired_order]
    return jobs_df.sort_values(by=["site", "date_posted"], ascending=[True, False]).reset_index(drop=True)
