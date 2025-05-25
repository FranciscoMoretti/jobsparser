# `jobsparser`

A simple CLI tool to scrape jobs from multiple job sites (LinkedIn, Indeed, Glassdoor).

Relevant article: [Automate Your Job Search: Scraping 400+ LinkedIn Jobs with Python](https://www.franciscomoretti.com/blog/automate-your-job-search)

## Installation

From PyPI:
```bash
pip install -U jobsparser
```

From source (if you've cloned this monorepo):
```bash
cd jobsparser
pip install .
```

## Usage

Basic usage:
```bash
jobsparser --search-term "Python Developer" --location "London"
```

Use multiple job sites:
```bash
jobsparser --search-term "Frontend Engineer" --location "Remote" --site linkedin --site indeed
```

Advanced usage:
```bash
jobsparser \
     --search-term "junior web developer" \
     --search-term "junior software engineer" \
     --search-term "junior frontend engineer" \
     --location "London" \
     --site linkedin \
     --site indeed \
     --site google \
     --results-wanted 50 \
     --job-type fulltime \
     --output-dir "my_jobs" \
     --hours-old 168 \
     --linkedin-experience-level "internship" \
     --linkedin-experience-level "entry_level" \
     --country UK
```

See all options:
```bash
jobsparser --help
```

## Features

- Scrape jobs from LinkedIn, Indeed, and Glassdoor
- Customizable search parameters:
  - Job type (fulltime, parttime, contract, internship)
  - Search radius (distance)
  - Number of results
  - Location and country
- Automatic retries and rate limiting
- CSV output with unique filenames
- Progress tracking and status updates

## Options

- `--search-term`: Job search query (required)
- `--location`: Job location (required)
- `--site`: Job sites to search (default: linkedin)
- `--results-wanted`: Total number of results (default: 100)
- `--distance`: Search radius in miles/km (default: 25)
- `--job-type`: Type of job (default: fulltime)
- `--country`: Country code for Indeed search (default: UK)
- `--fetch-description`: Fetch full job description (default: true)
- `--proxies`: Proxy addresses to use (can be specified multiple times)
- `--batch-size`: Results per batch (default: 30)
- `--sleep-time`: Base sleep time between batches (default: 100)
- `--max-retries`: Maximum retry attempts per batch (default: 3)
- `--output-dir`: Directory for CSV files (default: data)
- `--hours-old`: Hours old for job search (default: None)
- `--linkedin-experience-level`: Experience levels for LinkedIn search (internship, entry_level, associate, mid_senior, director, executive)


## Monorepo Overview

This repository contains the following packages:

*   **`jobsparser/`**: A CLI tool to scrape jobs from multiple job sites.
*   **`jobspy2/`**: A Python library that extends the original [JobSpy](https://github.com/Bunsly/JobSpy) library, used by `jobsparser`.

## License

The `jobsparser` package is licensed under the MIT License. See `jobsparser/LICENSE` for details. 

