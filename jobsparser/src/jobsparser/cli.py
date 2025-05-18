import click
from jobspy2 import scrape_jobs, LinkedInExperienceLevel
import pandas as pd
import os
import time
import importlib.metadata
import logging
import concurrent.futures
import threading # Added for threading.local

# Thread-local storage for logging context
log_context = threading.local()

class SiteContextFormatter(logging.Formatter):
    """A custom logging formatter that adds a colored prefix based on thread-local context."""
    
    # Store the original format string and datefmt
    def __init__(self, fmt=None, datefmt=None, style='%', validate=True, *, defaults=None):
        super().__init__(fmt, datefmt, style, validate, defaults=defaults)
        self._original_fmt = fmt
        self._original_datefmt = datefmt

    def format(self, record):
        # Standard formatting first
        # Temporarily remove our custom attributes if they exist, to avoid issues with super().format()
        prefix_attr = hasattr(record, 'custom_prefix')
        color_attr = hasattr(record, 'custom_color')
        
        # Use the original format string passed during __init__
        # Create a temporary formatter with the original settings to format the base message
        temp_formatter = logging.Formatter(self._original_fmt, self._original_datefmt)
        log_string = temp_formatter.format(record)

        # Get prefix and color from thread-local context
        prefix = getattr(log_context, 'prefix', None)
        color = getattr(log_context, 'color', 'reset')

        if prefix:
            return click.style(f"{prefix}{log_string}", fg=color)
        return log_string

# Global logger, can be configured in main
logger = logging.getLogger()

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
    # log_level is for jobspy2 internal logging level,
    # our handler will filter based on main verbose setting
    jobspy_log_level: int, 
    batch_size: int,
    sleep_time: int,
    max_retries: int,
    logging_prefix: str, # Prefix is now mandatory for context
    logging_color: str  # Color is now mandatory for context
):
    """Scrapes jobs for a single site with retries, batching, and sleep."""
    # Set context for the logger in this thread
    log_context.prefix = logging_prefix
    log_context.color = logging_color

    # Configure the specific JobSpy logger for this site
    # jobspy2.scrapers.utils.create_logger uses f"JobSpy:{name}" where name is capitalized site value
    # e.g. JobSpy:Linkedin, JobSpy:Indeed, JobSpy:ZipRecruiter
    jobspy_logger_name_segment = site_name.capitalize()
    if site_name.lower() == "zip_recruiter": # jobspy2 has a special case for ZipRecruiter capitalization
        jobspy_logger_name_segment = "ZipRecruiter"
    
    jobspy_site_logger_name = f"JobSpy:{jobspy_logger_name_segment}"
    jobspy_site_logger = logging.getLogger(jobspy_site_logger_name)

    # Remove any default handlers jobspy2 might have added to this specific logger
    for h in list(jobspy_site_logger.handlers):
        jobspy_site_logger.removeHandler(h)
    
    # Add our custom formatted handler to this specific jobspy logger
    # Use the same formatter class but create a new instance to respect thread context
    # The formatter's format string should match what jobspy2's default was, or our desired one.
    # Let's use the one defined for our root handler for consistency of base message format.
    # The root handler's formatter string is `%(asctime)s - %(levelname)s - %(message)s`
    # If jobspy's own formatter was '%(asctime)s - %(levelname)s - %(name)s - %(message)s', using %(name)s is fine.
    site_handler = logging.StreamHandler()
    # The formatter for SiteContextFormatter uses its _original_fmt for the base log string
    # which is set when the root handler's formatter is created. So it will be consistent.
    site_formatter = SiteContextFormatter(fmt='%(asctime)s - %(levelname)s - %(name)s - %(message)s', datefmt='%H:%M:%S')
    site_handler.setFormatter(site_formatter)
    jobspy_site_logger.addHandler(site_handler)
    jobspy_site_logger.setLevel(jobspy_log_level)
    jobspy_site_logger.propagate = False # We've handled it; prevent double logging if root also had a simple handler for some reason

    offset = 0
    site_all_jobs = []
    found_all_available_jobs_for_site = False

    # Removed echo_style, will use logger.info, logger.error directly

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
                    log_level=jobspy_log_level 
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
                sleep_duration_on_error = sleep_time * (retry_count + 1) 
                logger.warning(f"Sleeping for {sleep_duration_on_error} seconds before retry (attempt {retry_count}/{max_retries})")
                time.sleep(sleep_duration_on_error)
                if retry_count >= max_retries:
                    logger.error(f"Max retries reached. Moving on.")
                    found_all_available_jobs_for_site = True 
                    break 
    
    logger.info(f"Finished scraping. Total jobs found: {len(site_all_jobs)}")
    # Clear context for this thread
    delattr(log_context, 'prefix')
    delattr(log_context, 'color')
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
@click.option('--search-term', required=True, help='Job search query')
@click.option('--location', required=True, help='Job location')
@click.option('--site', multiple=True, type=click.Choice(['linkedin', 'indeed', 'glassdoor']), default=['linkedin'], help='Job sites to search')
@click.option('--results-wanted', default=100, help='Total number of results to fetch')
@click.option('--distance', default=25, help='Distance radius for job search')
@click.option('--job-type', type=click.Choice(['fulltime', 'parttime', 'contract', 'internship']), default='fulltime', help='Type of job')
@click.option('--country', default='UK', help='Country code for Indeed search')
@click.option('--fetch-description/--no-fetch-description', default=True, help='Fetch full job description for LinkedIn')
@click.option('--proxies', multiple=True, default=None, help="Proxy addresses to use. Can be specified multiple times. E.g. --proxies '208.195.175.46:65095' --proxies '208.195.175.45:65095'")
@click.option('--batch-size', default=30, help='Number of results to fetch in each batch')
@click.option('--sleep-time', default=100, help='Base sleep time between batches in seconds')
@click.option('--max-retries', default=3, help='Maximum retry attempts per batch')
@click.option('--hours-old', default=None, help='Hours old for job search')
@click.option('--output-dir', default='data', help='Directory to save output CSV')
@click.option('--linkedin-experience-level', multiple=True, type=click.Choice([level.value for level in LinkedInExperienceLevel]), default=None, help='Experience levels to search for on LinkedIn')
@click.option('-v', '--verbose', count=True, help="Verbosity level: -v for INFO, -vv for DEBUG. Default is WARNING.", default=0)
def main(search_term, location, site, results_wanted, distance, job_type, country,
         fetch_description, proxies, batch_size, sleep_time, max_retries, hours_old, output_dir, linkedin_experience_level, verbose):
    """Scrape jobs from various job sites with customizable parameters."""
    
    # Configure logging
    # Remove existing handlers to avoid duplicate messages if script is re-run in same interpreter
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    # Root handler - primarily for logs from this script itself, or other libs propagating to root
    root_handler = logging.StreamHandler()
    # Pass the desired format string and datefmt to the constructor here
    root_formatter = SiteContextFormatter(fmt='%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    root_handler.setFormatter(root_formatter)
    logger.addHandler(root_handler)

    # jobspy2_log_level will be passed to scrape_jobs
    # logger.setLevel will control overall output
    jobspy2_internal_log_level = logging.INFO # Default for jobspy2
    if verbose == 0: # No -v: Our main logger shows WARNING and above
        logger.setLevel(logging.WARNING)
        jobspy2_internal_log_level = logging.WARNING # Tell jobspy2 to also be less verbose
    elif verbose == 1: # -v: Our main logger shows INFO and above
        logger.setLevel(logging.INFO)
        jobspy2_internal_log_level = logging.INFO
    elif verbose >= 2: # -vv or more: Our main logger shows DEBUG and above
        logger.setLevel(logging.DEBUG)
        jobspy2_internal_log_level = logging.DEBUG # Tell jobspy2 to be verbose

    # For jobspy2, it seems it uses the integer log levels directly.
    # We're setting our handler's level and also passing a suggested level to jobspy2.

    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename
    counter = 0
    while os.path.exists(f"{output_dir}/jobs_{counter}.csv"):
        counter += 1
    csv_filename = f"{output_dir}/jobs_{counter}.csv"

    all_jobs_collected = []
    
    site_colors = ["cyan", "green", "yellow", "magenta", "blue", "red"]

    if not site:
        # Use click.echo for direct user feedback not part of threaded logging
        click.echo("No job sites specified. Exiting.")
        return

    # Use logger for operational messages in main thread if desired, or click.echo for CLI interaction style
    logger.info(f"Starting job scraping for {len(site)} site(s).")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(site)) as executor:
        future_to_site = {}
        for i, site_name in enumerate(site):
            color_index = i % len(site_colors)
            current_color = site_colors[color_index]
            prefix = f"[{site_name.upper()}] "
            
            # This initial message can be a direct click.echo as it's a submission status
            click.echo(click.style(f"{prefix}Submitting task to scrape {results_wanted} jobs.", fg=current_color))
            
            future = executor.submit(
                _scrape_single_site,
                site_name=site_name,
                search_term=search_term,
                location=location,
                distance=distance,
                linkedin_fetch_description=fetch_description,
                job_type=job_type,
                country_indeed=country,
                results_wanted_for_site=results_wanted, 
                proxies=list(proxies) if proxies else None,
                hours_old=int(hours_old) if hours_old else None,
                linkedin_experience_levels=list(linkedin_experience_level) if linkedin_experience_level else None,
                jobspy_log_level=jobspy2_internal_log_level, 
                batch_size=batch_size,
                sleep_time=sleep_time,
                max_retries=max_retries,
                logging_prefix=prefix,
                logging_color=current_color
            )
            future_to_site[future] = (site_name, current_color, prefix) # Store color and prefix for completion message

        for future in concurrent.futures.as_completed(future_to_site):
            site_name_completed, completed_color, completed_prefix = future_to_site[future]
            try:
                jobs_from_site = future.result()
                all_jobs_collected.extend(jobs_from_site)
                # This completion message can also be a direct click.echo or styled logger message
                # Using click.echo here to maintain the style for overall progress updates
                click.echo(click.style(f"{completed_prefix}Completed. Found {len(jobs_from_site)} jobs.", fg=completed_color))
            except Exception as exc:
                # Log exceptions from futures using the root logger
                # The SiteContextFormatter on the root_handler won't have thread-specific prefix/color
                # So, we manually add the prefix for context here.
                # completed_prefix is available here
                logger.error(f"{completed_prefix}Task for site generated an exception: {exc}", exc_info=True)
    
    if not all_jobs_collected:
        click.echo("No jobs found after scraping all sites. Check parameters or site availability.") # User feedback
        logger.warning("No jobs found after scraping all sites.") # Log entry
        return

    jobs_df = pd.DataFrame(all_jobs_collected)
    jobs_df.to_csv(csv_filename, index=False)
    # Final user feedback
    click.echo(f"Successfully saved {len(all_jobs_collected)} jobs from {len(site)} site(s) to {csv_filename}")
    logger.info(f"Successfully saved {len(all_jobs_collected)} jobs from {len(site)} site(s) to {csv_filename}")

if __name__ == '__main__':
    main() 