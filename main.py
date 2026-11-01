# python .\PMFBY_Dashboard_State_Data_Download_V5.py

# It defaults to:

# Year: 2026
# Season: Kharif
# Scheme: PMFBY + WBCIS
# States: All available
# Level: District
# Output: one consolidated CSV in data

# python .\PMFBY_Dashboard_State_Data_Download_V7.py --output all_states.csv
# python .\PMFBY_Dashboard_State_Data_Download_V7.py --year 2026 --season Kharif --scheme PMFBY --drill-to-district --output all_states.csv
# python .\PMFBY_Dashboard_State_Data_Download_V7.py --year 2026 --season Kharif --scheme BOTH --drill-to-district --output all_states.csv


import argparse
import csv
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

DASHBOARD_URL = "https://pmfby.gov.in/adminStatistics/dashboard"
WAIT_SECONDS = 30
MAX_STATE_RETRIES = 3
RETRY_WAIT_SECONDS = 3

SELECTORS = {
    "state_wise_report_link": '//a[@title="State Wise Report"]',
    "year_dropdown": '//label[normalize-space()="Year"]/following-sibling::select',
    "season_dropdown": '//label[normalize-space()="Season"]/following-sibling::select',
    "scheme_dropdown": '//label[normalize-space()="Scheme"]/following-sibling::select',
    "results_table": "table.adminStatics__dashboardTableDT___1cEkH",
}

SEASON_CODES = {"Kharif": "01", "Rabi": "02"}
SCHEME_CODES = {"PMFBY": "04", "WBCIS": "02"}


@dataclass
class FilterSpec:
    year: str
    season: str
    scheme: str
    state: Optional[str] = None


def sanitize_filename_part(text: str) -> str:
    text = str(text).strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_-]", "", text)


def get_data_folder() -> str:
    """Create and return a data folder beside this Python script."""
    script_folder = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(script_folder, "data")
    os.makedirs(data_folder, exist_ok=True)
    return data_folder


def build_default_output(year: str, season: str, scheme: str) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = (
        f"pmfby_district_data_{sanitize_filename_part(year)}_"
        f"{sanitize_filename_part(season)}_{sanitize_filename_part(scheme)}_"
        f"{timestamp}.csv"
    )
    return os.path.join(get_data_folder(), filename)


def build_csv_filename(spec: FilterSpec) -> str:
    parts = ["pmfby"]
    if spec.state:
        parts.append(sanitize_filename_part(spec.state))
    parts.extend(
        [
            sanitize_filename_part(spec.year),
            sanitize_filename_part(spec.season),
            sanitize_filename_part(spec.scheme),
        ]
    )
    return os.path.join(get_data_folder(), "_".join(parts) + ".csv")


def resolve_output_path(output: Optional[str], year: str, season: str, scheme: str) -> str:
    if not output:
        return build_default_output(year, season, scheme)
    if os.path.dirname(output):
        path = os.path.abspath(output)
    else:
        path = os.path.join(get_data_folder(), output)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return path


def make_driver(headless: bool = True):
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--log-level=3")

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(3)
    driver.set_page_load_timeout(60)
    return driver


def _is_xpath(selector: str) -> bool:
    return selector.startswith("//") or selector.startswith("(")


def wait_visible(driver, selector: str, timeout: int = WAIT_SECONDS):
    by = By.XPATH if _is_xpath(selector) else By.CSS_SELECTOR
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, selector))
    )


def wait_clickable(driver, selector: str, timeout: int = WAIT_SECONDS):
    by = By.XPATH if _is_xpath(selector) else By.CSS_SELECTOR
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, selector))
    )


def wait_for_table_rows(driver, timeout: int = WAIT_SECONDS):
    return WebDriverWait(driver, timeout).until(
        lambda d: d.find_element(By.CSS_SELECTOR, SELECTORS["results_table"])
        if d.find_elements(By.CSS_SELECTOR, SELECTORS["results_table"] + " tbody tr")
        else False
    )


def select_dropdown_by_value(driver, selector: str, value: str):
    element = wait_visible(driver, selector)
    Select(element).select_by_value(value)
    time.sleep(1.5)


def click_row_link_by_title(driver, name: str):
    table = wait_for_table_rows(driver)
    old_html = table.get_attribute("innerHTML")

    element = WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script(
            """
            const table = document.querySelector(arguments[0]);
            if (!table) return null;
            return Array.from(table.querySelectorAll('tbody a[title]')).find(
                a => (a.getAttribute('title') || '').trim() === arguments[1]
            ) || null;
            """,
            SELECTORS["results_table"],
            name,
        )
    )

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)

    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.find_element(
            By.CSS_SELECTOR, SELECTORS["results_table"]
        ).get_attribute("innerHTML")
        != old_html
    )
    wait_for_table_rows(driver)
    time.sleep(1)


def navigate_to(driver, spec: FilterSpec):
    driver.get(DASHBOARD_URL)
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

    report_link = wait_clickable(driver, SELECTORS["state_wise_report_link"])
    try:
        report_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", report_link)
    time.sleep(2)

    select_dropdown_by_value(driver, SELECTORS["year_dropdown"], spec.year)
    select_dropdown_by_value(
        driver, SELECTORS["season_dropdown"], SEASON_CODES[spec.season]
    )
    select_dropdown_by_value(
        driver, SELECTORS["scheme_dropdown"], SCHEME_CODES[spec.scheme]
    )
    wait_for_table_rows(driver)

    if spec.state:
        click_row_link_by_title(driver, spec.state)


def extract_table_rows(driver) -> Tuple[List[str], List[List[str]]]:
    try:
        table_element = wait_for_table_rows(driver)
    except TimeoutException:
        return [], []

    soup = BeautifulSoup(table_element.get_attribute("outerHTML"), "html.parser")
    headers = [th.get_text(" ", strip=True) for th in soup.select("thead th")]

    rows: List[List[str]] = []
    for tr in soup.select("tbody tr"):
        values: List[str] = []
        for td in tr.find_all("td"):
            anchor = td.find("a")
            if anchor and anchor.get("title"):
                values.append(anchor.get("title").strip())
            else:
                values.append(td.get_text(" ", strip=True))
        if values:
            rows.append(values)
    return headers, rows


def row_names(driver) -> List[str]:
    """Return only real clickable state names, excluding numeric totals."""
    table = wait_for_table_rows(driver)
    links = table.find_elements(By.CSS_SELECTOR, "tbody a[title]")

    states: List[str] = []
    for link in links:
        name = (link.get_attribute("title") or "").strip()
        if name and any(character.isalpha() for character in name) and name not in states:
            states.append(name)
    return states


def drop_grand_total(
    headers: List[str], rows: List[List[str]]
) -> Tuple[List[str], List[List[str]]]:
    filtered = [
        row
        for row in rows
        if not any(str(cell).strip().lower() == "grand total" for cell in row)
    ]
    return headers, filtered


def append_rows(
    spec: FilterSpec,
    headers: List[str],
    rows: List[List[str]],
    csv_path: str,
):
    if not rows:
        return

    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    meta_headers = ["Year", "Season", "Scheme", "State (selected)"]
    meta_values = [spec.year, spec.season, spec.scheme, spec.state or ""]
    max_columns = max(len(row) for row in rows)
    data_headers = (
        headers
        if len(headers) == max_columns
        else [f"Col{i + 1}" for i in range(max_columns)]
    )

    file_exists = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
    with open(csv_path, "a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(meta_headers + data_headers)
        for row in rows:
            padded_row = row + [""] * (max_columns - len(row))
            writer.writerow(meta_values + padded_row)


def validate_district_rows(state: str, rows: List[List[str]]):
    if not rows:
        raise RuntimeError(f"No district rows returned for {state}")
    if len(rows) == 1 and any(str(value).strip() == state for value in rows[0]):
        raise RuntimeError(f"Dashboard did not drill down into {state}")


def download_state_with_retry(
    driver,
    state_spec: FilterSpec,
    csv_path: str,
    max_retries: int = MAX_STATE_RETRIES,
) -> Tuple[bool, int, str]:
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            navigate_to(driver, state_spec)
            headers, rows = extract_table_rows(driver)
            headers, rows = drop_grand_total(headers, rows)
            validate_district_rows(state_spec.state or "", rows)
            append_rows(state_spec, headers, rows, csv_path)
            return True, len(rows), ""
        except (
            TimeoutException,
            NoSuchElementException,
            WebDriverException,
            RuntimeError,
        ) as error:
            last_error = f"{type(error).__name__}: {str(error).strip() or 'dashboard timeout'}"
            if attempt < max_retries:
                print(
                    f"  [{state_spec.scheme}] Retrying {state_spec.state} "
                    f"({attempt + 1}/{max_retries})..."
                )
                time.sleep(RETRY_WAIT_SECONDS * attempt)

    return False, 0, last_error


def run_single_scheme_job(
    driver,
    spec: FilterSpec,
    drill_to_district: bool = False,
    csv_path: Optional[str] = None,
    max_retries: int = MAX_STATE_RETRIES,
):
    if not drill_to_district:
        output_path = csv_path or build_csv_filename(spec)

        if spec.state:
            success, row_count, error = download_state_with_retry(
                driver, spec, output_path, max_retries
            )
            if not success:
                raise RuntimeError(
                    f"Could not download {spec.state} after all retries: {error}"
                )
            print(
                f"  [{spec.scheme}] Saved {spec.state}: "
                f"{row_count} district rows -> {output_path}"
            )
            return

        navigate_to(driver, spec)
        headers, rows = extract_table_rows(driver)
        headers, rows = drop_grand_total(headers, rows)
        append_rows(spec, headers, rows, output_path)
        print(f"  [{spec.scheme}] Saved {len(rows)} state-summary rows -> {output_path}")
        return

    base_spec = FilterSpec(spec.year, spec.season, spec.scheme, None)
    navigate_to(driver, base_spec)
    states = row_names(driver)
    print(f"[{spec.scheme}] Found {len(states)} states")

    incomplete: List[Tuple[str, str]] = []
    for state in states:
        state_spec = FilterSpec(spec.year, spec.season, spec.scheme, state)
        output_path = csv_path or build_csv_filename(state_spec)
        success, row_count, error = download_state_with_retry(
            driver, state_spec, output_path, max_retries
        )
        if success:
            print(
                f"  [{spec.scheme}] Saved {state}: "
                f"{row_count} district rows -> {output_path}"
            )
        else:
            incomplete.append((state, error))

    if incomplete:
        print(f"[{spec.scheme}] Rechecking {len(incomplete)} incomplete state(s)...")
        unresolved: List[Tuple[str, str]] = []

        for state, _ in incomplete:
            state_spec = FilterSpec(spec.year, spec.season, spec.scheme, state)
            output_path = csv_path or build_csv_filename(state_spec)
            success, row_count, error = download_state_with_retry(
                driver, state_spec, output_path, max_retries
            )
            if success:
                print(
                    f"  [{spec.scheme}] Saved {state}: "
                    f"{row_count} district rows -> {output_path}"
                )
            else:
                unresolved.append((state, error))

        if unresolved:
            details = "; ".join(f"{state} ({error})" for state, error in unresolved)
            raise RuntimeError(f"Download incomplete after all retries: {details}")

    print(f"[{spec.scheme}] Completed all {len(states)} states successfully.")


def normalize_schemes(raw_scheme: str) -> List[str]:
    """Normalize a single-scheme or combined-scheme command-line value."""
    value = raw_scheme.strip().upper().replace(" ", "")

    both_values = {
        "BOTH",
        "ALL",
        "PMFBY&WBCIS",
        "WBCIS&PMFBY",
        "PMFBY+WBCIS",
        "WBCIS+PMFBY",
    }

    if value in both_values:
        return ["PMFBY", "WBCIS"]

    if value in SCHEME_CODES:
        return [value]

    raise argparse.ArgumentTypeError(
        "--scheme must be PMFBY, WBCIS, BOTH, PMFBY&WBCIS, or PMFBY+WBCIS"
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download PMFBY dashboard state/district statistics"
    )
    parser.add_argument("--year", default="2026", help="Default: 2026")
    parser.add_argument(
        "--season",
        default="Kharif",
        choices=["Kharif", "Rabi"],
        help="Default: Kharif",
    )
    parser.add_argument(
        "--scheme",
        default="BOTH",
        help="PMFBY, WBCIS, BOTH, or PMFBY&WBCIS. Default: BOTH",
    )
    parser.add_argument(
        "--state",
        default=None,
        help='Example: "MAHARASHTRA". If omitted, all states are downloaded.',
    )
    parser.add_argument(
        "--drill-to-district",
        action="store_true",
        help="Download district data for all available states.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="CSV filename/path. A bare filename is saved in the data folder.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=MAX_STATE_RETRIES,
        help=f"Retries per state in each pass. Default: {MAX_STATE_RETRIES}",
    )
    parser.add_argument(
        "--headed", action="store_true", help="Run with visible Chrome window."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    schemes = normalize_schemes(args.scheme)
    max_retries = max(1, min(args.retries, 10))

    # No state supplied means all available states at district level.
    if args.state is None:
        args.drill_to_district = True

    if args.drill_to_district and args.state:
        print("Note: --state is ignored because --drill-to-district was supplied.")
        args.state = None

    output_path = resolve_output_path(
        args.output, args.year, args.season, args.scheme.upper()
    )

    print("=" * 65)
    print("PMFBY DASHBOARD DATA DOWNLOADER")
    print("=" * 65)
    print(f"Year       : {args.year}")
    print(f"Season     : {args.season}")
    print(f"Scheme     : {args.scheme.upper()}")
    print(f"State      : {args.state or 'ALL AVAILABLE STATES'}")
    print(f"Level      : {'DISTRICT' if args.drill_to_district else 'STATE'}")
    print(f"Output     : {output_path}")
    print(f"Retries    : {max_retries}")
    print("=" * 65)

    driver = make_driver(headless=not args.headed)
    try:
        for scheme in schemes:
            print(f"\nStarting scheme: {scheme}")
            spec = FilterSpec(
                year=args.year,
                season=args.season,
                scheme=scheme,
                state=None if args.drill_to_district else args.state,
            )
            # Pass retry count directly by temporarily using the validated default.
            run_single_scheme_job(
                driver,
                spec,
                drill_to_district=args.drill_to_district,
                csv_path=output_path,
                max_retries=max_retries,
            )
    finally:
        driver.quit()

    print("\n" + "=" * 65)
    print("DOWNLOAD COMPLETED")
    print("=" * 65)
    print(f"CSV saved to:\n{output_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
