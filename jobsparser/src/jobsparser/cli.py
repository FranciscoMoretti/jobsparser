import click
from jobspy2 import scrape_jobs, LinkedInExperienceLevel
import pandas as pd
import os
import time
import importlib.metadata
import logging
import concurrent.futures

# Custom Logging Handler using Click
class ClickColorHandler(logging.Handler):
    def __init__(self, prefix: str, color: str):
        super().__init__()
        self.prefix = prefix
        self.color = color

    def emit(self, record):
        try:
            msg = self.format(record)
            # Determine if error for click.echo's err=True
            is_error = record.levelno >= logging.ERROR
            click.echo(click.style(f"{self.prefix}{msg}", fg=self.color), err=is_error)
        except Exception:
            self.handleError(record)

# Function to get version
def get_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    try:
        version = importlib.metadata.version("jobsparser")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown" # Fallback if package not installed
    click.echo(f"jobsparser, version {version}")
    ctx.exit()

def _scrape_single_site(
    site_name: str,
    search_term: str,
    location: str,
    distance: int,
    linkedin_fetch_description: bool,
    job_type: str,
    country_indeed: str,
    results_wanted_for_site: int,
    proxies: list[str] | None,
    hours_old: int | None,
    linkedin_experience_levels: list | None,
    logger: logging.Logger, # Main logger for this function's operations
    batch_size: int,
    sleep_time: int,
    max_retries: int,
):
    """Scrapes jobs for a single site with retries, batching, and sleep."""
    offset = 0
    site_all_jobs = []
    found_all_available_jobs_for_site = False

    while len(site_all_jobs) < results_wanted_for_site and not found_all_available_jobs_for_site:
        retry_count = 0
        while retry_count < max_retries:
            logger.info(f"Fetching jobs: {offset} to {offset + batch_size}")
            try:
                iteration_results_wanted = min(batch_size, results_wanted_for_site - len(site_all_jobs))
                jobs_df_scraped = scrape_jobs(
                    site_name=site_name,
                    search_term=search_term,
                    location=location,
                    distance=distance,
                    linkedin_fetch_description=linkedin_fetch_description,
                    job_type=job_type,
                    country_indeed=country_indeed,
                    results_wanted=iteration_results_wanted,
                    offset=offset,
                    proxies=proxies,
                    hours_old=hours_old,
                    linkedin_experience_levels=linkedin_experience_levels,
                    logger=logger # Pass the parent logger for jobspy to use
                )
                if jobs_df_scraped is None or jobs_df_scraped.empty:
                    new_jobs = []
                else:
                    new_jobs = jobs_df_scraped.to_dict("records")
                
                site_all_jobs.extend(new_jobs)
                offset += iteration_results_wanted

                if len(new_jobs) < iteration_results_wanted:
                    logger.info(f"Scraped {len(site_all_jobs)} jobs.")
                    logger.info(f"No more jobs available. Wanted {results_wanted_for_site} jobs, got {len(site_all_jobs)}")
                    found_all_available_jobs_for_site = True
                    break

                if len(site_all_jobs) >= results_wanted_for_site:
                    logger.info(f"Reached desired {len(site_all_jobs)} jobs for this site.")
                    break
                    
                logger.info(f"Scraped {len(site_all_jobs)} jobs.")
                current_sleep_duration = sleep_time 
                logger.info(f"Sleeping for {current_sleep_duration} seconds before next batch.")
                time.sleep(current_sleep_duration)
                break 

            except Exception as e:
                logger.error(f"Error scraping: {e}", exc_info=True) # Add exc_info for traceback
                retry_count += 1
                sleep_duration_on_error = sleep_time * (retry_count + 1) # Exponential backoff
                logger.warning(f"Sleeping for {sleep_duration_on_error} seconds before retry (attempt {retry_count}/{max_retries})")
                time.sleep(sleep_duration_on_error)
                if retry_count >= max_retries:
                    logger.error(f"Max retries reached. Moving on.")
                    found_all_available_jobs_for_site = True 
                    break 
    
    logger.info(f"Finished scraping. Total jobs found: {len(site_all_jobs)}")
    return site_all_jobs

@click.command()
@click.option(
    "--version",
    is_flag=True,
    callback=get_version,
    expose_value=False,
    is_eager=True,
    help="Show the version and exit.",
)
@click.option('--search-term', required=True, multiple=True, help='Job search query (can be specified multiple times)')
@click.option('--location', required=True, help='Job location')
@click.option('--site', multiple=True, type=click.Choice(['linkedin', 'indeed', 'glassdoor', 'zip_recruiter', 'google']), default=['linkedin'], help='Job sites to search')
@click.option('--results-wanted', default=15, help='Total number of results to fetch per site')
@click.option('--distance', default=50, help='Distance radius for job search')
@click.option('--job-type', type=click.Choice(['fulltime', 'parttime', 'contract', 'internship']), default=None, help='Type of job')
@click.option('--indeed-country', default='usa', help='Country code for Indeed search')
@click.option('--fetch-description/--no-fetch-description', default=False, help='Fetch full job description for LinkedIn')
@click.option('--proxies', multiple=True, default=None, help="Proxy addresses to use. Can be specified multiple times. E.g. --proxies '208.195.175.46:65095' --proxies '208.195.175.45:65095'")
@click.option('--batch-size', default=30, help='Number of results to fetch in each batch')
@click.option('--sleep-time', default=100, help='Base sleep time between batches in seconds')
@click.option('--max-retries', default=3, help='Maximum retry attempts per batch')
@click.option('--hours-old', default=None, type=int, help='Hours old for job search')
@click.option('--output-dir', default='data', help='Directory to save output CSV')
@click.option('--linkedin-experience-level', multiple=True, type=click.Choice([level.value for level in LinkedInExperienceLevel]), default=None, help='Experience levels for LinkedIn')
@click.option('-v', '--verbose', count=True, help="Verbosity: -v for DEBUG, default INFO for this script's logs.", default=0)
def main(search_term, location, site, results_wanted, distance, job_type, indeed_country,
         fetch_description, proxies, batch_size, sleep_time, max_retries, hours_old, output_dir, linkedin_experience_level, verbose):
    """Scrape jobs from various job sites with customizable parameters."""
    
    # Determine overall log level for this script's loggers
    if verbose == 0: # No -v flags
        cli_log_level = logging.INFO
    elif verbose >= 1: # -v or -vv etc
        cli_log_level = logging.DEBUG

    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename
    counter = 0
    while os.path.exists(f"{output_dir}/jobs_{counter}.csv"):
        counter += 1
    csv_filename = f"{output_dir}/jobs_{counter}.csv"

    all_jobs_collected = []
    
    site_colors = ["cyan", "green", "yellow", "magenta", "blue", "red"]

    if not site:
        click.echo("No job sites specified. Exiting.")
        return

    # Basic formatter for our handlers
    formatter = logging.Formatter('%(message)s') # Simple message, prefix is handled by ClickColorHandler
    root_logger = logging.getLogger("jobsparser.cli.main_summary")
    root_logger.setLevel(cli_log_level)
    # Final summary (could use a general/root logger for this)
    if not root_logger.hasHandlers(): # Basic handler for summary if none exists
        summary_handler = logging.StreamHandler()
        summary_handler.setFormatter(logging.Formatter('[JOBSPARSER] %(message)s')) # Default format
        root_logger.addHandler(summary_handler)
        root_logger.propagate = False

    root_logger.info("Starting job scraping...")

    # Process each search term sequentially
    for idx, current_search_term in enumerate(search_term):
        if idx > 0:  # Skip sleep before first search term
            root_logger.info(f"Sleeping for {sleep_time} seconds before next search term...")
            time.sleep(sleep_time)
            
        root_logger.info(f"Processing search term: {current_search_term}")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(site)) as executor:
            future_to_site_logger_map = {}
            for i, site_name_str in enumerate(site):
                color_index = i % len(site_colors)
                current_color = site_colors[color_index]
                prefix = f"[{site_name_str.upper()}] "
                
                # Create and configure a logger for this specific site
                site_logger_name = f"jobsparser.cli.{site_name_str}"
                site_logger = logging.getLogger(site_logger_name)
                site_logger.setLevel(cli_log_level) # Set level based on verbosity

                # Clear existing handlers to prevent duplication if re-run
                if site_logger.hasHandlers():
                    site_logger.handlers.clear()

                handler = ClickColorHandler(prefix=prefix, color=current_color)
                handler.setFormatter(formatter)
                site_logger.addHandler(handler)
                site_logger.propagate = False # Don't send to root logger if we have specific handling

                site_logger.info(f"Submitting task to scrape {results_wanted} jobs.")
                
                future = executor.submit(
                    _scrape_single_site,
                    site_name=site_name_str,
                    search_term=current_search_term,
                    location=location,
                    distance=distance,
                    linkedin_fetch_description=fetch_description,
                    job_type=job_type,
                    country_indeed=indeed_country,
                    results_wanted_for_site=results_wanted,
                    proxies=list(proxies) if proxies else None,
                    hours_old=hours_old,
                    linkedin_experience_levels=list(linkedin_experience_level) if linkedin_experience_level else None,
                    logger=site_logger,
                    batch_size=batch_size,
                    sleep_time=sleep_time,
                    max_retries=max_retries,
                )
                future_to_site_logger_map[future] = site_logger

            for future in concurrent.futures.as_completed(future_to_site_logger_map):
                completed_site_logger = future_to_site_logger_map[future]
                try:
                    jobs_from_site = future.result()
                    all_jobs_collected.extend(jobs_from_site)
                    completed_site_logger.info(f"Completed. Found {len(jobs_from_site)} jobs.")
                except Exception as exc:
                    completed_site_logger.error(f"Task generated an exception: {exc}", exc_info=True)

    if not all_jobs_collected:
        root_logger.warning("No jobs found after scraping all sites. Check parameters or site availability.")
        return

    # Convert to DataFrame and remove duplicates
    jobs_df = pd.DataFrame(all_jobs_collected)
    jobs_df = jobs_df.drop_duplicates(subset=['job_url'], keep='first')
    jobs_df.to_csv(csv_filename, index=False)
    root_logger.info(f"Successfully saved {len(jobs_df)} unique jobs from {len(site)} site(s) to {csv_filename}")

if __name__ == '__main__':
    main() 