## This is working code for PMFBY Premium Calculator


from __future__ import annotations

import csv
import re
import time
import traceback
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

HOME_URL = "https://pmfby.gov.in/"
SEASON = "Kharif"  # Kharif / Rabi
YEAR = "2026" # Rabi then 2026-2027
SCHEME = "Weather Based Crop Insurance Scheme" # Weather Based Crop Insurance Scheme / Pradhan Mantri Fasal Bima Yojana
SCHEME1 = "WBCIS" # WBCIS / PMFBY
STATE = "ANDHRA PRADESH"  # "ANDHRA PRADESH", "ANDAMAN & NICOBAR ISLANDS"
AREA_HECTARE = "1"
HEADLESS = False
REPROCESS_EXISTING = False
MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_MS = 30000
NAVIGATION_TIMEOUT_MS = 60000
RESULT_TIMEOUT_MS = 45000
OUTPUT_DIR = Path("pmfby_output1")
OUTPUT_CSV = OUTPUT_DIR / f"Premium_Rate_{STATE.lower().replace(' ', '_')}_{SEASON.lower()}_{YEAR}_{SCHEME1}.csv"
FAILURE_CSV = OUTPUT_DIR / f"Premium_Rate_{STATE.lower().replace(' ', '_')}_{SEASON.lower()}_{YEAR}_{SCHEME1}_failures.csv"

OUTPUT_COLUMNS = [
    "season", "year", "scheme", "state", "district", "crop", "area_hectare",
    "insurance_company", "sum_insured_rs_per_hectare", "farmer_share_percent",
    "actuarial_rate_percent", "cutoff_date_actual", "premium_paid_by_farmer_rs",
    "premium_paid_by_government_rs", "sum_insured_rs", "cutoff_date_csc",
    "cutoff_date_aide", "data_entry_date_bank", "premium_debit_date_bank",
    "challan_date_bank", "scraped_at", "status", "remarks"
]
FAILURE_COLUMNS = ["season", "year", "scheme", "state", "district", "crop", "attempt", "error", "failed_at"]


def clean_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value: str) -> str:
    value = clean_text(value).lower().replace("₹", " rs ").replace("%", " percent ")
    return clean_text(re.sub(r"[^a-z0-9]+", " ", value))


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def append_csv(path: Path, row: dict, columns: list[str]) -> None:
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in columns})


def completed_pairs() -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if REPROCESS_EXISTING or not OUTPUT_CSV.exists():
        return done
    with OUTPUT_CSV.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if clean_text(row.get("status")).lower() == "success":
                done.add((clean_text(row.get("district")).casefold(), clean_text(row.get("crop")).casefold()))
    return done


def first_visible(locator: Locator) -> Optional[Locator]:
    for index in range(locator.count()):
        item = locator.nth(index)
        try:
            if item.is_visible():
                return item
        except Exception:
            pass
    return None


def click(locator: Locator) -> None:
    locator.scroll_into_view_if_needed(timeout=5000)
    try:
        locator.click(timeout=10000)
    except Exception:
        locator.click(timeout=10000, force=True)


def wait_stable(page: Page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass


def handle_captcha(page: Page) -> None:
    text = clean_text(page.locator("body").inner_text()).lower()
    if any(term in text for term in ("captcha", "recaptcha", "verify you are human")):
        if HEADLESS:
            raise RuntimeError("Human verification detected. Run with HEADLESS=False.")
        input("Complete human verification in the browser, then press Enter: ")


def click_text(page: Page, names: list[str], timeout_ms: int = 20000) -> None:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for name in names:
            pattern = re.compile(re.escape(name), re.I)
            for loc in (page.get_by_role("button", name=pattern), page.get_by_role("link", name=pattern), page.locator("button", has_text=pattern), page.locator("a", has_text=pattern)):
                item = first_visible(loc)
                if item:
                    click(item)
                    return
        page.wait_for_timeout(400)
    raise RuntimeError(f"Could not click: {names}")


def find_field(page: Page, labels: list[str]) -> Locator:
    controls = "select, input, [role='combobox'], mat-select, .ng-select, .p-dropdown"
    for label in labels:
        pattern = re.compile(re.escape(label), re.I)
        item = first_visible(page.get_by_label(pattern, exact=False))
        if item:
            return item
        item = first_visible(page.get_by_role("combobox", name=pattern))
        if item:
            return item
        for index in range(page.locator(controls).count()):
            field = page.locator(controls).nth(index)
            try:
                if not field.is_visible():
                    continue
            except Exception:
                continue
            attrs = " ".join(clean_text(field.get_attribute(a)) for a in ("placeholder", "aria-label", "title", "name"))
            if pattern.search(attrs):
                return field
        labels_found = page.locator("label, mat-label, .form-label, .control-label").filter(has_text=pattern)
        for index in range(labels_found.count()):
            lab = labels_found.nth(index)
            for xpath in ("following::select[1]", "following::input[1]", "following::*[@role='combobox'][1]", "following::mat-select[1]", "following::*[contains(@class,'ng-select')][1]"):
                item = first_visible(lab.locator(f"xpath={xpath}"))
                if item:
                    return item
    raise RuntimeError(f"Field not found: {labels}")


def wait_enabled(field: Locator) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        disabled = False
        try:
            disabled = field.is_disabled()
        except Exception:
            pass
        if not disabled and clean_text(field.get_attribute("aria-disabled")).lower() != "true":
            return
        time.sleep(0.3)
    raise RuntimeError("Field remained disabled")


def valid_option(text: str) -> bool:
    key = normalize(text)
    return bool(key) and key not in {"select", "select one", "please select", "choose", "all", "none", "no data", "no options"} and not key.startswith("select ")


def select_value(page: Page, labels: list[str], value: str) -> None:
    field = find_field(page, labels)
    wait_enabled(field)
    tag = clean_text(field.evaluate("e => e.tagName")).lower()
    if tag == "select":
        try:
            field.select_option(label=value)
            page.wait_for_timeout(500)
            return
        except Exception:
            pass
        for index in range(field.locator("option").count()):
            option = field.locator("option").nth(index)
            if clean_text(option.inner_text()).casefold() == clean_text(value).casefold():
                option_value = option.get_attribute("value")
                if option_value is not None:
                    field.select_option(value=option_value)
                else:
                    field.select_option(index=index)
                page.wait_for_timeout(500)
                return
        raise RuntimeError(f"Option not found: {value}")
    click(field)
    page.wait_for_timeout(400)
    pattern = re.compile(rf"^\s*{re.escape(clean_text(value))}\s*$", re.I)
    for selector in ("[role='option']", "mat-option", ".ng-option", ".p-dropdown-item", ".dropdown-item", "ul[role='listbox'] li"):
        item = first_visible(page.locator(selector).filter(has_text=pattern))
        if item:
            click(item)
            page.wait_for_timeout(500)
            return
    page.keyboard.type(value, delay=30)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)


def dropdown_options(page: Page, labels: list[str]) -> list[str]:
    field = find_field(page, labels)
    wait_enabled(field)
    tag = clean_text(field.evaluate("e => e.tagName")).lower()
    values: list[str] = []
    if tag == "select":
        for index in range(field.locator("option").count()):
            text = clean_text(field.locator("option").nth(index).inner_text())
            if valid_option(text):
                values.append(text)
    else:
        click(field)
        page.wait_for_timeout(500)
        for selector in ("[role='listbox'] [role='option']", "mat-option", ".ng-option", ".p-dropdown-item", ".dropdown-item", "ul[role='listbox'] li"):
            found = []
            for index in range(page.locator(selector).count()):
                option = page.locator(selector).nth(index)
                try:
                    if option.is_visible():
                        text = clean_text(option.inner_text())
                        if valid_option(text):
                            found.append(text)
                except Exception:
                    pass
            if found:
                values = found
                break
        page.keyboard.press("Escape")
    return list(dict.fromkeys(values))


def fill_area(page: Page) -> None:
    field = find_field(page, ["Area (In Hectare)", "Area In Hectare", "Area"])
    wait_enabled(field)
    field.fill(AREA_HECTARE)
    field.evaluate("e => {e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); e.blur();}")


def open_calculator(page: Page) -> None:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    wait_stable(page)
    handle_captcha(page)
    click_text(page, ["Calculate Now"], 30000)
    wait_stable(page)
    handle_captcha(page)
    find_field(page, ["Season"])


def apply_base(page: Page) -> None:
    select_value(page, ["Season"], SEASON)
    select_value(page, ["Year"], YEAR)
    select_value(page, ["Scheme"], SCHEME)
    select_value(page, ["State"], STATE)
    page.wait_for_timeout(1000)


def table_rows(table: Locator) -> list[list[str]]:
    rows = []
    for r in range(table.locator("tr").count()):
        cells = table.locator("tr").nth(r).locator("th, td")
        values = [clean_text(cells.nth(c).inner_text()) for c in range(cells.count())]
        if any(values):
            rows.append(values)
    return rows


def all_tables(page: Page) -> list[list[list[str]]]:
    result = []
    for index in range(page.locator("table").count()):
        table = page.locator("table").nth(index)
        try:
            if table.is_visible():
                result.append(table_rows(table))
        except Exception:
            pass
    return result


def find_record(tables: list[list[list[str]]], required: list[str]) -> dict[str, str]:
    required_norm = [normalize(x) for x in required]
    for rows in tables:
        for h in range(max(0, len(rows) - 1)):
            headers = rows[h]
            joined = " | ".join(normalize(x) for x in headers)
            if all(term in joined for term in required_norm):
                for d in range(h + 1, len(rows)):
                    if any(rows[d]):
                        return {normalize(header): clean_text(rows[d][i]) if i < len(rows[d]) else "" for i, header in enumerate(headers)}
    return {}


def value(record: dict[str, str], candidates: list[str]) -> str:
    for candidate in map(normalize, candidates):
        if candidate in record:
            return clean_text(record[candidate])
    for key, val in record.items():
        if any(candidate in key or key in candidate for candidate in map(normalize, candidates)):
            return clean_text(val)
    return ""


def wait_results(page: Page) -> None:
    deadline = time.time() + RESULT_TIMEOUT_MS / 1000
    while time.time() < deadline:
        handle_captcha(page)
        text = clean_text(page.locator("body").inner_text()).lower()
        if sum(term in text for term in ("insurance company", "premium paid by farmer", "sum insured")) >= 2:
            page.wait_for_timeout(800)
            return
        if any(term in text for term in ("no data found", "no record found", "something went wrong", "service unavailable")):
            raise RuntimeError("Portal returned no data or an error")
        page.wait_for_timeout(600)
    raise RuntimeError("Premium result timeout")


def extract_result(page: Page, district: str, crop: str) -> dict:
    tables = all_tables(page)
    insurance = find_record(tables, ["insurance company", "sum insured", "farmer share"])
    premium = find_record(tables, ["crop", "area", "premium paid by farmer"])
    dates = find_record(tables, ["cut off date", "data entry date"])
    row = {
        "season": SEASON, "year": YEAR, "scheme": SCHEME, "state": STATE, "district": district,
        "crop": value(premium, ["Crop"]) or crop,
        "area_hectare": value(premium, ["Area(Hectare)", "Area Hectare", "Area"]) or AREA_HECTARE,
        "insurance_company": value(insurance, ["Insurance Company"]),
        "sum_insured_rs_per_hectare": value(insurance, ["Sum Insured (Rs)/Hectare", "Sum Insured Per Hectare"]),
        "farmer_share_percent": value(insurance, ["Farmer Share (%)", "Farmer Share"]),
        "actuarial_rate_percent": value(insurance, ["Acturial Rate (%)", "Actuarial Rate (%)"]),
        "cutoff_date_actual": value(insurance, ["Cut-off (Actual)", "Cut Off Actual"]),
        "premium_paid_by_farmer_rs": value(premium, ["Premium Paid By Farmer (Rs)", "Premium Paid By Farmer"]),
        "premium_paid_by_government_rs": value(premium, ["Premium Paid By Govt (Rs)", "Premium Paid By Government (Rs)"]),
        "sum_insured_rs": value(premium, ["Sum Insured (Rs)", "Sum Insured Rs"]),
        "cutoff_date_csc": value(dates, ["Cut Off Date (CSC)", "Cut-Off Date CSC"]),
        "cutoff_date_aide": value(dates, ["Cut Off Date (AIDE)", "Cut-Off Date AIDE"]),
        "data_entry_date_bank": value(dates, ["Data Entry Date (Bank)", "Data Entry Date Bank"]),
        "premium_debit_date_bank": value(dates, ["Premim Debit Date (Bank)", "Premium Debit Date (Bank)"]),
        "challan_date_bank": value(dates, ["Challan Date (Bank)", "Challan Date Bank"]),
        "scraped_at": timestamp(), "status": "success", "remarks": ""
    }
    if not any(row[k] for k in ("insurance_company", "sum_insured_rs_per_hectare", "premium_paid_by_farmer_rs", "sum_insured_rs")):
        raise RuntimeError("Result appeared, but premium fields could not be extracted")
    return row


def reset(page: Page) -> None:
    try:
        find_field(page, ["Season"])
        return
    except Exception:
        pass
    for name in ("Close", "Back", "OK"):
        item = first_visible(page.get_by_role("button", name=re.compile(rf"^{name}$", re.I)))
        if item:
            click(item)
            page.wait_for_timeout(400)
            return
    open_calculator(page)


def scrape(page: Page) -> None:
    done = completed_pairs()
    apply_base(page)
    districts = dropdown_options(page, ["District"])
    if not districts:
        raise RuntimeError("No Goa districts found")
    for district in districts:
        reset(page)
        apply_base(page)
        select_value(page, ["District"], district)
        page.wait_for_timeout(900)
        crops = dropdown_options(page, ["Crop"])
        print(f"{district}: {len(crops)} crops")
        for crop in crops:
            key = (district.casefold(), crop.casefold())
            if key in done:
                print(f"  SKIP {crop}")
                continue
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    reset(page)
                    apply_base(page)
                    select_value(page, ["District"], district)
                    page.wait_for_timeout(800)
                    select_value(page, ["Crop"], crop)
                    fill_area(page)
                    click_text(page, ["Check Premium", "Calculate Premium"])
                    wait_results(page)
                    row = extract_result(page, district, crop)
                    append_csv(OUTPUT_CSV, row, OUTPUT_COLUMNS)
                    done.add(key)
                    print(f"  SAVED {crop}: farmer={row['premium_paid_by_farmer_rs']}")
                    break
                except Exception as exc:
                    append_csv(FAILURE_CSV, {"season": SEASON, "year": YEAR, "scheme": SCHEME, "state": STATE, "district": district, "crop": crop, "attempt": attempt, "error": clean_text(str(exc)), "failed_at": timestamp()}, FAILURE_COLUMNS)
                    print(f"  Attempt {attempt} failed for {crop}: {exc}")
                    if attempt < MAX_ATTEMPTS:
                        open_calculator(page)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=HEADLESS, args=["--start-maximized"])
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="en-IN", timezone_id="Asia/Kolkata")
            context.set_default_timeout(DEFAULT_TIMEOUT_MS)
            context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
            page = context.new_page()
            open_calculator(page)
            scrape(page)
            print(f"Completed. CSV: {OUTPUT_CSV.resolve()}")
    except KeyboardInterrupt:
        print("Stopped. Completed rows remain in the CSV.")
    except Exception as exc:
        print(f"Fatal error: {exc}")
        traceback.print_exc()
    finally:
        if context:
            context.close()
        if browser:
            browser.close()


if __name__ == "__main__":
    main()
