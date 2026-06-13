# External data sources

## 1. ETO Advanced Semiconductor Supply Chain Dataset  (`eto/`)
- **Provider:** Emerging Technology Observatory (ETO), Georgetown CSET.
- **Repo:** https://github.com/georgetown-cset/eto-chip-explorer
- **Snapshot vendored:** `providers.csv`, `provision.csv`, `inputs.csv`,
  `stages.csv`, `sequence.csv`, `technical_notes.md` (fetched 2026-06-13).
- **What it gives us:** 374 real organizations across the global semiconductor
  supply chain, with **real market-share provision relationships** (e.g. ASML
  = 100% of EUV lithography tools) and cited sources. This is genuine supply
  intelligence — the market-share figures are NOT mock.
- **Attribution:** Data derived from CSET, *The Semiconductor Supply Chain:
  Assessing National Competitiveness* (2021), augmented by ETO (2022, 2024).
  Please credit ETO/CSET when redistributing. Refer to ETO's dataset docs for
  the upstream license/terms: https://eto.tech/dataset-docs/chipexplorer

## 2. TSIA — Taiwan Semiconductor Industry Association member directory (`tsia/`)
- **Source:** https://www.tsia.org.tw/MemberList?nodeID=26
- **Coverage:** FULL — all **220 members** across 11 pages.
- **How:** `scripts/scrape_tsia.py` drives a headless Chromium (Playwright)
  through the site's ASP.NET `__doPostBack` pagination, capturing each member's
  number, Traditional-Chinese name, and own website URL →
  `tsia/members_scraped.csv`.
- **English names:** `scripts/build_tsia_members.py` maps each member to an
  English name + segment. 144 are **verified** (confirmed against the member's
  website domain / well-known identity); 76 are **unverified**, rendered as a
  domain-derived brand with a trailing `*`. The authoritative Traditional-Chinese
  name is always in `local_name`, and `website` lets you confirm identity.
- **Regenerate:** `python scripts/scrape_tsia.py && python scripts/build_tsia_members.py`

## 3. SEMI member directory — NOT INGESTED
- **Source:** https://www.semi.org/en/resources/member-directory
- **Status:** Returns HTTP 403 (Cloudflare bot protection). The directory is
  also gated to logged-in members. Cannot be scraped; left out deliberately.
  Wire it via an authenticated SEMI member login + the OpenCorporates stub if
  membership access becomes available.
