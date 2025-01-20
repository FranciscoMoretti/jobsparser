# jobsparser

A simple CLI tool to scrape jobs from multiple job sites (LinkedIn, Indeed, Glassdoor) using [JobSpy](https://github.com/Bunsly/JobSpy).

## Installation

From PyPI (coming soon):
```bash
pip install jobsparser
```

From source:
```bash
git clone https://github.com/fran/jobsparser
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
    --search-term "Data Scientist" \
    --location "New York" \
    --site linkedin --site indeed --site glassdoor \
    --results-wanted 200 \
    --distance 50 \
    --job-type fulltime \
    --output-dir "my_jobs"
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
- `--batch-size`: Results per batch (default: 30)
- `--sleep-time`: Base sleep time between batches (default: 100)
- `--output-dir`: Directory for CSV files (default: data)

## License

MIT License - see [LICENSE](LICENSE) for details.