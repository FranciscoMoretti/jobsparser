import pandas as pd

from jobspy2 import scrape_jobs


def test_indeed():
    result = scrape_jobs(
        site_name="indeed",
        search_term="engineer",
        results_wanted=5,
    )
    assert isinstance(result, pd.DataFrame) and len(result) == 5, "Result should be a non-empty DataFrame"
