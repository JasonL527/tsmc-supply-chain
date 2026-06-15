"""
osint.py — live OSINT API clients for PROJECT SAURON.

Each client makes a REAL HTTP call when its API key is configured (via
st.secrets or environment variables), and otherwise returns clearly-labelled
MOCK data so the demo keeps working with no keys. Every return dict carries:

    configured : bool   — was an API key present?
    live       : bool   — did we actually hit the network and get data back?
    error      : str    — populated on failure (live path only)

Configure keys in `.streamlit/secrets.toml` (see secrets.toml.example):

    GOOGLE_MAPS_API_KEY     = "..."     # Places API (New) — Text Search
    OPENCORPORATES_API_TOKEN= "..."     # https://api.opencorporates.com (v0.4)
    IMPORTYETI_API_BASE     = "..."     # see caveat in importyeti_shipments()
    IMPORTYETI_API_KEY      = "..."

NOTE ON TESTING: the mock fallbacks and the response parsers are unit-tested,
but the live endpoints are written to each provider's documented contract and
have NOT been exercised here (no keys). Verify field mappings against your plan
before trusting production output.
"""
from __future__ import annotations

import os
from typing import Any

try:
    import requests
except ImportError:                       # requests is in requirements.txt
    requests = None                       # mock-only mode

try:
    import streamlit as st
except ImportError:                       # allow importing outside Streamlit
    st = None


# ──────────────────────────────────────────────────────────────────────────────
# config helpers
# ──────────────────────────────────────────────────────────────────────────────
def _secret(key: str, default: str = "") -> str:
    """Read a secret from st.secrets first, then the environment."""
    if st is not None:
        try:
            if key in st.secrets:
                return str(st.secrets[key])
        except Exception:
            pass
    return os.environ.get(key, default)


def api_status() -> dict[str, bool]:
    """Which integrations have a key configured (for the UI status row)."""
    return {
        "google_places": bool(_secret("GOOGLE_MAPS_API_KEY")),
        "opencorporates": bool(_secret("OPENCORPORATES_API_TOKEN")),
        "importyeti": bool(_secret("IMPORTYETI_API_BASE") and _secret("IMPORTYETI_API_KEY")),
        "requests_available": requests is not None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Google Places (New) — Text Search → geocode a company by name
# ──────────────────────────────────────────────────────────────────────────────
def geocode_company(name: str, country: str = "", *, timeout: int = 20) -> dict[str, Any]:
    """
    Resolve a company name → {lat, lon, formatted_address} via Places API (New).

    Enable "Places API (New)" + billing in Google Cloud, then set
    GOOGLE_MAPS_API_KEY. Cache aggressively upstream — this is billed per call.
    """
    key = _secret("GOOGLE_MAPS_API_KEY")
    query = ", ".join(p for p in (name, country) if p)
    if not key or requests is None:
        return {
            "configured": False, "live": False, "source": "places (MOCK)",
            "query": query, "lat": 24.7805, "lon": 121.0102,
            "formatted_address": "Hsinchu Science Park, Hsinchu, Taiwan (MOCK)",
            "hint": "Set GOOGLE_MAPS_API_KEY in .streamlit/secrets.toml for live geocoding.",
        }
    try:
        resp = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.location,places.formattedAddress,places.displayName",
            },
            json={"textQuery": query, "maxResultCount": 1},
            timeout=timeout,
        )
        resp.raise_for_status()
        return _parse_places(resp.json(), query)
    except Exception as e:                 # network / quota / parse failure
        return {"configured": True, "live": False, "source": "places (New)",
                "query": query, "error": f"{type(e).__name__}: {e}"}


def _parse_places(payload: dict, query: str) -> dict[str, Any]:
    places = payload.get("places") or []
    if not places:
        return {"configured": True, "live": True, "source": "places (New)",
                "query": query, "error": "no match", "lat": None, "lon": None}
    loc = places[0].get("location", {})
    return {
        "configured": True, "live": True, "source": "places (New)", "query": query,
        "lat": loc.get("latitude"), "lon": loc.get("longitude"),
        "formatted_address": places[0].get("formattedAddress", ""),
        "matched_name": (places[0].get("displayName") or {}).get("text", ""),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 2. ImportYeti / Bill-of-Lading customs data — who ships to Arizona
# ──────────────────────────────────────────────────────────────────────────────
def importyeti_shipments(company: str, dest_state: str = "AZ", *, timeout: int = 30) -> dict[str, Any]:
    """
    US Customs Bill-of-Lading lookup for a supplier → shipments to `dest_state`.

    ⚠️ CAVEAT: ImportYeti does not publish an official public REST API. This
    client is endpoint-agnostic: point IMPORTYETI_API_BASE at whatever BoL data
    source you have access to — ImportYeti Enterprise, or a provider with a real
    API such as Panjiva (S&P), ImportGenius, or Trademo — and adjust the field
    mapping in _parse_bol() to that provider's JSON shape.
    """
    base = _secret("IMPORTYETI_API_BASE")
    key = _secret("IMPORTYETI_API_KEY")
    if not base or not key or requests is None:
        return {
            "configured": False, "live": False, "source": "importyeti (MOCK)",
            "query": company, "dest_state": dest_state,
            "shipments_last_12mo": 17, "top_consignee": "TSMC ARIZONA CORP",
            "top_hs_code": "8486.90 — parts of semiconductor mfg machines",
            "signal": "ACTIVE AZ-BOUND FREIGHT DETECTED (mock)",
            "hint": "Set IMPORTYETI_API_BASE + IMPORTYETI_API_KEY for live BoL data.",
        }
    try:
        resp = requests.get(
            f"{base.rstrip('/')}/shipments",
            params={"supplier": company, "consignee_state": dest_state},
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return _parse_bol(resp.json(), company, dest_state)
    except Exception as e:
        return {"configured": True, "live": False, "source": "importyeti",
                "query": company, "dest_state": dest_state,
                "error": f"{type(e).__name__}: {e}"}


def _parse_bol(payload: dict, company: str, dest_state: str) -> dict[str, Any]:
    rows = payload.get("shipments", payload.get("data", []))
    consignees: dict[str, int] = {}
    for r in rows:
        c = r.get("consignee") or r.get("consignee_name") or "—"
        consignees[c] = consignees.get(c, 0) + 1
    top = max(consignees.items(), key=lambda kv: kv[1], default=("—", 0))[0]
    return {
        "configured": True, "live": True, "source": "importyeti",
        "query": company, "dest_state": dest_state,
        "shipments_last_12mo": len(rows), "top_consignee": top,
        "signal": ("ACTIVE AZ-BOUND FREIGHT DETECTED" if rows else "no shipments found"),
        "shipments": rows[:25],
    }


# ──────────────────────────────────────────────────────────────────────────────
# 3. OpenCorporates — company registry + new AZ/DE subsidiary filings
# ──────────────────────────────────────────────────────────────────────────────
def opencorporates_search(name: str, jurisdiction: str = "", *, timeout: int = 30) -> dict[str, Any]:
    """
    Search the OpenCorporates registry (v0.4). With OPENCORPORATES_API_TOKEN set
    this hits the live API; a new us_az / us_de entity is a hard migration signal.
    """
    token = _secret("OPENCORPORATES_API_TOKEN")
    if not token or requests is None:
        return {
            "configured": False, "live": False, "source": "opencorporates (MOCK)",
            "query": name,
            "matches": [
                {"name": f"{name} Co., Ltd.", "jurisdiction": "tw", "status": "Active"},
                {"name": f"{name} USA LLC", "jurisdiction": "us_az", "status": "Active",
                 "incorporation_date": "2025-09-12"},
            ],
            "us_subsidiary_signal": True,
            "hint": "Set OPENCORPORATES_API_TOKEN for live registry data.",
        }
    try:
        params = {"q": name, "api_token": token, "per_page": 30}
        if jurisdiction:
            params["jurisdiction_code"] = jurisdiction
        resp = requests.get("https://api.opencorporates.com/v0.4/companies/search",
                            params=params, timeout=timeout)
        resp.raise_for_status()
        return _parse_opencorporates(resp.json(), name)
    except Exception as e:
        return {"configured": True, "live": False, "source": "opencorporates",
                "query": name, "error": f"{type(e).__name__}: {e}"}


def _parse_opencorporates(payload: dict, name: str) -> dict[str, Any]:
    companies = (payload.get("results", {}) or {}).get("companies", [])
    matches = []
    us_signal = False
    for item in companies:
        c = item.get("company", {})
        juris = c.get("jurisdiction_code", "")
        if juris in ("us_az", "us_de"):
            us_signal = True
        matches.append({
            "name": c.get("name"),
            "jurisdiction": juris,
            "company_number": c.get("company_number"),
            "status": c.get("current_status") or c.get("status"),
            "incorporation_date": c.get("incorporation_date"),
            "address": c.get("registered_address_in_full"),
            "url": c.get("opencorporates_url"),
        })
    return {
        "configured": True, "live": True, "source": "opencorporates",
        "query": name, "matches": matches, "us_subsidiary_signal": us_signal,
    }
