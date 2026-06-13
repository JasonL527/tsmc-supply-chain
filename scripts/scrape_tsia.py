"""
Scrape the full TSIA member directory (all pages) via Playwright.

TSIA's site is ASP.NET Web Forms: pagination happens through __doPostBack
form submissions, not URL params — so we drive a real (headless) browser and
click the "Next" pager link, carrying the server viewstate forward each time.

Each member row exposes: member number, company name (Traditional Chinese),
and the company's own website URL — the website is captured because its domain
is the most reliable basis for an English-name mapping later.

Usage:
    ./.venv/bin/python scripts/scrape_tsia.py
Output:
    data/tsia/members_scraped.csv   (member_id, local_name, website)
"""
import csv
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.tsia.org.tw/MemberList?nodeID=26"
OUT = Path(__file__).resolve().parent.parent / "data" / "tsia" / "members_scraped.csv"
NEXT_POSTBACK = "ctl00$ContentPlaceHolder1$lnkbtnNext"
MAX_PAGES = 20  # safety cap (directory is ~10 pages)


def extract_rows(page):
    """Return list of (member_id, chinese_name, website) for the current page."""
    return page.eval_on_selector_all(
        'td[data-title="公司名稱："]',
        """cells => cells.map(td => {
            const a = td.querySelector('a');
            const tr = td.closest('tr');
            const idCell = tr ? tr.querySelector('td[data-title="會員編號："]') : null;
            return [
                idCell ? idCell.textContent.trim() : '',
                (a ? a.textContent : td.textContent).trim(),
                a ? (a.getAttribute('href') || '') : ''
            ];
        })""",
    )


def first_member_id(page):
    rows = extract_rows(page)
    return rows[0][0] if rows else None


def main():
    seen, ordered = set(), []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(30000)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector('td[data-title="公司名稱："]')

        for pg in range(1, MAX_PAGES + 1):
            rows = extract_rows(page)
            new = 0
            for mid, name, site in rows:
                key = mid or name
                if key and key not in seen:
                    seen.add(key)
                    ordered.append((mid, name, site))
                    new += 1
            print(f"  page {pg}: {len(rows)} rows ({new} new) — total {len(ordered)}")

            # Is there an enabled "Next" link? (disabled when on the last page)
            has_next = page.evaluate(
                """() => {
                    const a = [...document.querySelectorAll('a')].find(
                        el => el.getAttribute('href') &&
                              el.getAttribute('href').includes('lnkbtnNext'));
                    return !!a;
                }"""
            )
            if not has_next:
                print("  no further Next link — stopping.")
                break

            before = first_member_id(page)
            page.evaluate(f"() => __doPostBack('{NEXT_POSTBACK}', '')")
            try:
                page.wait_for_function(
                    """before => {
                        const tr = document.querySelector('td[data-title="會員編號："]');
                        return tr && tr.textContent.trim() !== before;
                    }""",
                    arg=before,
                    timeout=15000,
                )
            except Exception:
                print("  page did not advance — stopping.")
                break
            time.sleep(0.8)  # be polite

        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["member_id", "local_name", "website"])
        w.writerows(ordered)
    print(f"\nSaved {len(ordered)} members → {OUT}")


if __name__ == "__main__":
    main()
