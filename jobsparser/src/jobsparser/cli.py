import click
from jobspy2 import scrape_jobs, LinkedInExperienceLevel
import pandas as pd
import os
import time
import importlib.metadata
import logging
import concurrent.futures

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
    log_level: int,
    batch_size: int,
    sleep_time: int,
    max_retries: int,
    # Parameters for colored/prefixed logging (to be used later)
    # logging_prefix: str = "", 
    # logging_color: str = "reset" 
):
    """Scrapes jobs for a single site with retries, batching, and sleep."""
    offset = 0
    site_all_jobs = []
    found_all_available_jobs_for_site = False

    while len(site_all_jobs) < results_wanted_for_site and not found_all_available_jobs_for_site:
        retry_count = 0
        while retry_count < max_retries:
            # TODO: Replace click.echo with a logging mechanism that uses prefix/color
            click.echo(f"Fetching jobs for {site_name}: {offset} to {offset + batch_size}")
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
                    log_level=log_level
                )
                if jobs_df_scraped is None or jobs_df_scraped.empty:
                    new_jobs = []
                else:
                    new_jobs = jobs_df_scraped.to_dict("records")
                
                site_all_jobs.extend(new_jobs)
                offset += len(new_jobs) # Correctly increment offset by number of jobs actually found

                if len(new_jobs) < iteration_results_wanted:
                    click.echo(f"Scraped {len(site_all_jobs)} jobs for {site_name}")
                    click.echo(f"No more jobs available for {site_name}. Wanted {results_wanted_for_site} jobs, got {len(site_all_jobs)}")
                    found_all_available_jobs_for_site = True
                    break

                if len(site_all_jobs) >= results_wanted_for_site:
                    break
                    
                click.echo(f"Scraped {len(site_all_jobs)} jobs for {site_name}")
                # Sleep logic will be adjusted when running in parallel, for now, keep as is
                # Consider if sleep is needed here or at a higher level when parallelizing
                current_sleep_duration = sleep_time # Base sleep, retries will increase it
                click.echo(f"Sleeping for {current_sleep_duration} seconds before next batch for {site_name}")
                time.sleep(current_sleep_duration)
                break # Successful batch, break retry loop

            except Exception as e:
                click.echo(f"Error scraping {site_name}: {e}", err=True)
                retry_count += 1
                sleep_duration_on_error = sleep_time * (retry_count + 1) # Exponential backoff
                click.echo(f"Sleeping for {sleep_duration_on_error} seconds before retry for {site_name} (attempt {retry_count}/{max_retries})")
                time.sleep(sleep_duration_on_error)
                if retry_count >= max_retries:
                    click.echo(f"Max retries reached for {site_name}. Moving on.", err=True)
                    found_all_available_jobs_for_site = True # Mark as done if max retries hit
                    break 
    
    click.echo(f"Finished scraping for {site_name}. Total jobs found: {len(site_all_jobs)}")
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
@click.option('-v', '--verbose', count=True, help="Verbosity level: -v for DEBUG. Default is INFO.", default=0)
def main(search_term, location, site, results_wanted, distance, job_type, country,
         fetch_description, proxies, batch_size, sleep_time, max_retries, hours_old, output_dir, linkedin_experience_level, verbose):
    """Scrape jobs from various job sites with customizable parameters."""
    
    # Map Click's count verbose to the levels used by set_logger_level
    # 0 (default from click, no -v): WARNING
    # 1 (-v): DEBUG
    if verbose == 0: # No -v flags
        log_level = logging.INFO # INFO in set_logger_level
    elif verbose == 1: # -v
        log_level = logging.DEBUG # DEBUG in set_logger_level


    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename
    counter = 0
    while os.path.exists(f"{output_dir}/jobs_{counter}.csv"):
        counter += 1
    csv_filename = f"{output_dir}/jobs_{counter}.csv"

    # Placeholder for where the new function will be called and results aggregated
    # For now, let's assume we are still processing one site to keep it runnable,
    # but we'll use the new function.
    
    all_jobs_collected = [] # This will store jobs from all sites later

    if site: # If any site is specified
        # For now, just process the first site to test the extracted function
        # Parallel processing will be added next
        first_site_name = list(site)[0] 
        click.echo(f"Starting scrape for site: {first_site_name}")
        
        # Note: `results_wanted` from CLI is per site in the new design
        # `linkedin_experience_level` needs to be passed correctly
        
        jobs_from_site = _scrape_single_site(
            site_name=first_site_name,
            search_term=search_term,
            location=location,
            distance=distance,
            linkedin_fetch_description=fetch_description,
            job_type=job_type,
            country_indeed=country,
            results_wanted_for_site=results_wanted, # results_wanted is now per site
            proxies=list(proxies) if proxies else None,
            hours_old=int(hours_old) if hours_old else None,
            linkedin_experience_levels=list(linkedin_experience_level) if linkedin_experience_level else None,
            log_level=log_level,
            batch_size=batch_size,
            sleep_time=sleep_time,
            max_retries=max_retries
        )
        all_jobs_collected.extend(jobs_from_site)
    else:
        click.echo("No job sites specified. Exiting.")
        return

    if not all_jobs_collected:
        click.echo("No jobs found after scraping. Check parameters or site availability.")
        return

    jobs_df = pd.DataFrame(all_jobs_collected)
    jobs_df.to_csv(csv_filename, index=False)
    click.echo(f"Successfully saved {len(all_jobs_collected)} jobs to {csv_filename}")

if __name__ == '__main__':
    main() 