# jobsparser

A simple CLI tool to scrape jobs from multiple job sites (LinkedIn, Indeed, Google) using a modified version of [JobSpy](https://github.com/Bunsly/JobSpy).

Relevant article: [Automate Your Job Search: Scraping 400+ LinkedIn Jobs with Python](https://www.franciscomoretti.com/blog/automate-your-job-search)

## Installation

From PyPI:
```bash
pip install jobsparser
```

From source:
```bash
git clone https://github.com/FranciscoMoretti/jobsparser
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
    --search-term "Junior Frontend Developer" \
    --search-term "Junior Software Engineer" \
    --location "London" \
    --site linkedin \
    --results-wanted 200 \
    --distance 50 \
    --job-type fulltime \
    --output-dir "my_jobs" \
    --hours-old 168 \
    --linkedin-experience-level "internship" \
    --linkedin-experience-level "entry_level"
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
- `--country`: Country code for Indeed search (default: usa)
- `--fetch-description`: Fetch full job description (default: true)
- `--proxies`: Proxy addresses to use (can be specified multiple times)
- `--batch-size`: Results per batch (default: 30)
- `--sleep-time`: Base sleep time between batches (default: 100)
- `--max-retries`: Maximum retry attempts per batch (default: 3)
- `--output-dir`: Directory for CSV files (default: data)
- `--hours-old`: Hours old for job search (default: None)
- `--linkedin-experience-level`: Experience levels for LinkedIn search (internship, entry_level, associate, mid_senior, director, executive)

## License

MIT License - see [LICENSE](LICENSE) for details.
