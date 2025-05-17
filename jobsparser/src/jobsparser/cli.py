import click
from jobspy2 import scrape_jobs, LinkedInExperienceLevel
import pandas as pd
import os
import time
import importlib.metadata

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
def main(search_term, location, site, results_wanted, distance, job_type, country,
         fetch_description, proxies, batch_size, sleep_time, max_retries, hours_old, output_dir, linkedin_experience_level):
    """Scrape jobs from various job sites with customizable parameters."""
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename
    counter = 0
    while os.path.exists(f"{output_dir}/jobs_{counter}.csv"):
        counter += 1
    csv_filename = f"{output_dir}/jobs_{counter}.csv"

    offset = 0
    all_jobs = []

    while len(all_jobs) < results_wanted:
        retry_count = 0
        while retry_count < max_retries:
            click.echo(f"Fetching jobs {offset} to {offset + batch_size}")
            try:
                jobs = scrape_jobs(
                    site_name=list(site)[0],
                    search_term=search_term,
                    location=location,
                    distance=distance,
                    linkedin_fetch_description=fetch_description,
                    job_type=job_type,
                    country_indeed=country,
                    results_wanted=min(batch_size, results_wanted - len(all_jobs)),
                    offset=offset,
                    proxies=proxies,
                    hours_old=hours_old,
                    linkedin_experience_levels=linkedin_experience_level
                )

                all_jobs.extend(jobs.to_dict("records"))
                offset += batch_size

                if len(all_jobs) >= results_wanted:
                    break

                click.echo(f"Scraped {len(all_jobs)} jobs")
                sleep_duration = sleep_time * (retry_count + 1)
                click.echo(f"Sleeping for {sleep_duration} seconds")
                time.sleep(sleep_duration)
                break

            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                retry_count += 1
                sleep_duration = sleep_time * (retry_count + 1)
                click.echo(f"Sleeping for {sleep_duration} seconds before retry")
                time.sleep(sleep_duration)
                if retry_count >= max_retries:
                    click.echo("Max retries reached. Exiting.", err=True)
                    break

    jobs_df = pd.DataFrame(all_jobs)
    jobs_df.to_csv(csv_filename, index=False)
    click.echo(f"Successfully saved {len(all_jobs)} jobs to {csv_filename}")

if __name__ == '__main__':
    main() 