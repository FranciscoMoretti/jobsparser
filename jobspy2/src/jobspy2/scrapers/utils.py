from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from itertools import cycle
from typing import Any

import numpy as np
import requests
import tls_client
from bs4.element import Tag
from markdownify import markdownify as md
from requests.adapters import HTTPAdapter, Retry

from ..jobs import CompensationInterval, JobType


def create_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"JobSpy:{name}")
    logger.propagate = False
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        console_handler = logging.StreamHandler()
        log_fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        formatter = logging.Formatter(log_fmt)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


class RotatingProxySession:
    def __init__(self, proxies: list[str] | str | None = None) -> None:
        if isinstance(proxies, str):
            self.proxy_cycle: Iterator[dict[str, str]] | None = cycle([self.format_proxy(proxies)])
        elif isinstance(proxies, list):
            self.proxy_cycle = cycle([self.format_proxy(proxy) for proxy in proxies]) if proxies else None
        else:
            self.proxy_cycle = None

    @staticmethod
    def format_proxy(proxy: str) -> dict[str, str]:
        """Utility method to format a proxy string into a dictionary."""
        if proxy.startswith("http://") or proxy.startswith("https://"):
            return {"http": proxy, "https": proxy}
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}


class RequestsRotating(RotatingProxySession, requests.Session):
    def __init__(
        self,
        proxies: list[str] | str | None = None,
        has_retry: bool = False,
        delay: int = 1,
        clear_cookies: bool = False,
    ) -> None:
        RotatingProxySession.__init__(self, proxies=proxies)
        requests.Session.__init__(self)
        self.clear_cookies = clear_cookies
        self.allow_redirects = True
        self.setup_session(has_retry, delay)

    def setup_session(self, has_retry: bool, delay: int) -> None:
        if has_retry:
            retries = Retry(
                total=3,
                connect=3,
                status=3,
                status_forcelist=[500, 502, 503, 504, 429],
                backoff_factor=delay,
            )
            adapter = HTTPAdapter(max_retries=retries)
            self.mount("http://", adapter)
            self.mount("https://", adapter)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if self.clear_cookies:
            self.cookies.clear()

        if self.proxy_cycle:
            next_proxy = next(self.proxy_cycle)
            if next_proxy["http"] != "http://localhost":
                self.proxies = next_proxy
            else:
                self.proxies = {}
        return requests.Session.request(self, method, url, **kwargs)


class TLSRotating(RotatingProxySession, tls_client.Session):
    def __init__(self, proxies: list[str] | str | None = None) -> None:
        RotatingProxySession.__init__(self, proxies=proxies)
        tls_client.Session.__init__(self, random_tls_extension_order=True)

    def execute_request(self, *args: Any, **kwargs: Any) -> requests.Response:
        if self.proxy_cycle:
            next_proxy = next(self.proxy_cycle)
            if next_proxy["http"] != "http://localhost":
                self.proxies = next_proxy
            else:
                self.proxies = {}
        response = tls_client.Session.execute_request(self, *args, **kwargs)
        response.ok = response.status_code in range(200, 400)
        return response


def create_session(
    *,
    proxies: list[str] | str | None = None,
    ca_cert: str | None = None,
    is_tls: bool = True,
    has_retry: bool = False,
    delay: int = 1,
    clear_cookies: bool = False,
) -> requests.Session:
    """
    Creates a requests session with optional tls, proxy, and retry settings.
    :return: A session object
    """
    if is_tls:
        session = TLSRotating(proxies=proxies)
    else:
        session = RequestsRotating(
            proxies=proxies,
            has_retry=has_retry,
            delay=delay,
            clear_cookies=clear_cookies,
        )

    if ca_cert:
        session.verify = ca_cert

    return session


def markdown_converter(description_html: str | None) -> str | None:
    if description_html is None:
        return None
    markdown = md(description_html)
    return markdown.strip() if markdown else None


def extract_emails_from_text(text: str | None) -> list[str] | None:
    if not text:
        return None
    email_regex = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    return email_regex.findall(text)


def get_enum_from_job_type(job_type_str: str | None) -> JobType | None:
    """
    Given a string, returns the corresponding JobType enum member if a match is found.
    """
    if not job_type_str:
        return None
    res = None
    for job_type in JobType:
        if job_type_str in job_type.value:
            res = job_type
    return res


def currency_parser(cur_str: str) -> float:
    # Remove any non-numerical characters
    # except for ',' '.' or '-' (e.g. EUR)
    cur_str = re.sub("[^-0-9.,]", "", cur_str)
    # Remove any 000s separators (either , or .)
    cur_str = re.sub("[.,]", "", cur_str[:-3]) + cur_str[-3:]

    if "." in list(cur_str[-3:]):
        num = float(cur_str)
    elif "," in list(cur_str[-3:]):
        num = float(cur_str.replace(",", "."))
    else:
        num = float(cur_str)

    return np.round(num, 2)


def remove_attributes(tag: Tag) -> Tag:
    for attr in list(tag.attrs):
        del tag[attr]
    return tag


def extract_salary(
    salary_str: str | None,
    lower_limit: int = 1000,
    upper_limit: int = 700000,
    hourly_threshold: int = 350,
    monthly_threshold: int = 30000,
    enforce_annual_salary: bool = False,
) -> tuple[str | None, float | None, float | None, str | None]:
    """
    Extracts salary information from a string and returns the salary interval, min and max salary values, and currency.
    (TODO: Needs test cases as the regex is complicated and may not cover all edge cases)
    """
    if not salary_str:
        return None, None, None, None

    parsed_values = parse_salary_string(salary_str)
    if not parsed_values:
        return None, None, None, None

    min_salary, max_salary = parsed_values
    return calculate_salary_range(
        min_salary,
        max_salary,
        lower_limit,
        upper_limit,
        hourly_threshold,
        monthly_threshold,
        enforce_annual_salary,
    )


def parse_salary_string(salary_str: str) -> tuple[int, int] | None:
    min_max_pattern = r"\$(\d+(?:,\d+)?(?:\.\d+)?)([kK]?)\s*[-—–]\s*(?:\$)?(\d+(?:,\d+)?(?:\.\d+)?)([kK]?)"  # noqa: RUF001
    match = re.search(min_max_pattern, salary_str)
    if not match:
        return None

    def to_int(s: str) -> int:
        return int(float(s.replace(",", "")))

    min_salary = to_int(match.group(1))
    max_salary = to_int(match.group(3))

    # Handle 'k' suffix for min and max salaries independently
    if "k" in match.group(2).lower() or "k" in match.group(4).lower():
        min_salary *= 1000
        max_salary *= 1000

    return min_salary, max_salary


def calculate_salary_range(
    min_salary: int,
    max_salary: int,
    lower_limit: int,
    upper_limit: int,
    hourly_threshold: int,
    monthly_threshold: int,
    enforce_annual_salary: bool,
) -> tuple[str | None, float | None, float | None, str | None]:
    """
    Calculates the salary range based on the input parameters.
    Returns a tuple of (interval, min_salary, max_salary, currency).
    """
    interval, annual_min, annual_max = determine_interval_and_annual_values(
        min_salary, max_salary, hourly_threshold, monthly_threshold
    )

    if enforce_annual_salary and interval != CompensationInterval.YEARLY:
        return None, None, None, None

    if annual_min is not None and not is_valid_salary_range(
        annual_min, annual_max or annual_min, lower_limit, upper_limit
    ):
        return None, None, None, None

    return interval, min_salary, max_salary, "USD"


def determine_interval_and_annual_values(
    min_salary: int, max_salary: int, hourly_threshold: int, monthly_threshold: int
) -> tuple[str, float | None, float | None]:
    """
    Determines the salary interval and calculates annual values.
    Returns a tuple of (interval, annual_min, annual_max).
    """
    if min_salary < hourly_threshold:
        interval = CompensationInterval.HOURLY
        annual_min = min_salary * 2080  # 40 hours/week * 52 weeks
        annual_max = max_salary * 2080 if max_salary else None
    elif min_salary < monthly_threshold:
        interval = CompensationInterval.MONTHLY
        annual_min = min_salary * 12
        annual_max = max_salary * 12 if max_salary else None
    else:
        interval = CompensationInterval.YEARLY
        annual_min = min_salary
        annual_max = max_salary if max_salary else None

    return interval, annual_min, annual_max


def is_valid_salary_range(annual_min: float, annual_max: float, lower_limit: int, upper_limit: int) -> bool:
    """
    Checks if the salary range is valid based on the given limits.
    """
    return lower_limit <= annual_min <= upper_limit and lower_limit <= annual_max <= upper_limit


def extract_job_type(description: str | None) -> list[JobType]:
    """
    Extracts job type from job description.
    """
    if not description:
        return []

    job_types: list[JobType] = []
    for job_type in JobType:
        if any(keyword.lower() in description.lower() for keyword in job_type.value):
            job_types.append(job_type)

    return job_types


def setup_logger(logger_name: str) -> logging.Logger:
    """
    Sets up a logger with the given name.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


class InvalidLogLevelError(Exception):
    """Raised when an invalid log level is provided."""

    def __init__(self, level_name: str) -> None:
        self.message = f"Invalid log level: {level_name!r}"
        super().__init__(self.message)


def set_log_level(level_name: str) -> None:
    """
    Sets the log level for all loggers.
    """
    level = getattr(logging, level_name.upper(), None)
    if level is None:
        raise InvalidLogLevelError(level_name)

    for logger_name in logging.root.manager.loggerDict:
        if logger_name.startswith("JobSpy:"):
            logging.getLogger(logger_name).setLevel(level)
