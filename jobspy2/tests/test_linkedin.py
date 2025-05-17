import pandas as pd

from jobspy2 import scrape_jobs


def test_linkedin():
    result = scrape_jobs(
        site_name="linkedin",
        search_term="frontend engineer",
        results_wanted=5,
        linkedin_experience_levels=["entry_level", "associate"],
    )
    assert isinstance(result, pd.DataFrame) and len(result) == 5, "Result should be a non-empty DataFrame"


if __name__ == "__main__":
    test_linkedin()
