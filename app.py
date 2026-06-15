"""
═══════════════════════════════════════════════════════════════════════════════
 PROJECT SAURON — Semiconductor Supply Chain Command Center
 ──────────────────────────────────────────────────────────────────────────────
 B2B intelligence platform mapping the TSMC multi-tier supply chain
 (Tier 1 → Tier 2 → Tier 3) and scoring Taiwanese Tier 2/3 suppliers on
 their likelihood of migrating to Phoenix, Arizona (TSMC Fab 21 ecosystem).

 Architecture:
   • NetworkX        — 3-tier directed supply graph + centrality analytics
   • Folium          — Geospatial "Eye of Sauron" views (Global / Hsinchu / Phoenix)
   • Pandas          — Flat, Google-Sheets-ready dataset + CSV export
   • Plotly          — Hierarchical network tree + scoring visualizations
   • OSINT stubs     — ImportYeti (BoL/customs), OpenCorporates, Google Places

 Run:
   pip install -r requirements.txt
   streamlit run app.py

 NOTE: All company data below is MOCK / illustrative. Real company names are
 used for realism, but coordinates, revenues, dependence percentages and
 scores are synthetic placeholders pending live OSINT integration.
═══════════════════════════════════════════════════════════════════════════════
"""

import math
import random
import re
from datetime import date
from pathlib import Path

import folium
import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from folium.plugins import AntPath
from streamlit_folium import st_folium

import osint  # live OSINT API clients (Google Places, ImportYeti, OpenCorporates)

# ──────────────────────────────────────────────────────────────────────────────
# 0. PAGE CONFIG + COMMAND-CENTER AESTHETIC
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PROJECT SAURON · Supply Chain Command Center",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .stApp { background: radial-gradient(ellipse at top, #0b0f1d 0%, #05070d 60%); }
      [data-testid="stSidebar"] { background: #0a0e17; border-right: 1px solid #1c2333; }
      [data-testid="stMetric"] {
          background: #0b101d; border: 1px solid #1c2333;
          border-radius: 10px; padding: 12px 16px;
      }
      [data-testid="stMetricValue"] { color: #ff6b35; font-family: 'Courier New', monospace; }
      [data-testid="stMetricLabel"] { color: #8d99ae; }
      h1, h2, h3 { color: #e8e9f3; }
      .sauron-title {
          font-family: 'Courier New', monospace; font-size: 2.0rem; font-weight: 800;
          letter-spacing: 2px; color: #e8e9f3;
          text-shadow: 0 0 18px rgba(255, 75, 43, 0.55);
      }
      .sauron-sub { color: #8d99ae; font-family: 'Courier New', monospace; letter-spacing: 1px; }
      .stTabs [data-baseweb="tab"] { color: #8d99ae; }
      .stTabs [aria-selected="true"] { color: #ff6b35; }
      div[data-testid="stExpander"] { background: #0b101d; border: 1px solid #1c2333; border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────────────────
# 0b. SIMPLE LOGIN GATE
# ──────────────────────────────────────────────────────────────────────────────
# Credentials live in st.secrets under a [passwords] table (username = password).
# If no [passwords] table is configured the gate is DISABLED (open access) so the
# app keeps working before you set it up — add the secret to switch it on.
def check_password() -> bool:
    import hmac

    try:
        users = dict(st.secrets.get("passwords", {}))
    except Exception:
        users = {}
    if not users:                      # no credentials configured → open access
        return True
    if st.session_state.get("auth_ok"):
        return True

    def _verify():
        u = st.session_state.get("login_user", "")
        p = st.session_state.get("login_pass", "")
        ok = u in users and hmac.compare_digest(str(p), str(users[u]))
        st.session_state["auth_ok"] = ok
        st.session_state["auth_failed"] = not ok
        if ok:
            st.session_state.pop("login_pass", None)   # don't retain the password

    st.markdown(
        "<div class='sauron-title'>👁️ PROJECT SAURON</div>"
        "<div class='sauron-sub'>RESTRICTED · SIGN IN TO CONTINUE</div><br>",
        unsafe_allow_html=True,
    )
    with st.form("login"):
        st.text_input("Username", key="login_user")
        st.text_input("Password", type="password", key="login_pass")
        st.form_submit_button("Sign in", on_click=_verify, type="primary")
    if st.session_state.get("auth_failed"):
        st.error("Incorrect username or password.")
    return False


if not check_password():
    st.stop()

# ──────────────────────────────────────────────────────────────────────────────
# 1. OSINT API CLIENTS  — see osint.py for the live Google Places / ImportYeti /
#    OpenCorporates clients. They hit the real endpoints when a key is set in
#    st.secrets and return labelled mock data otherwise. The interactive UI for
#    them lives in the "OSINT HARVESTING PIPELINE" expander near the bottom.
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Geocoding via Google Places…")
def geocode_cached(name: str, country: str) -> dict:
    """Cache geocode results — Places is billed per request."""
    return osint.geocode_company(name, country)


def apply_geo_overrides(df: pd.DataFrame, overrides: dict) -> pd.DataFrame:
    """Apply session geocode overrides {company_id: (lat, lon, addr)} onto df."""
    if not overrides:
        return df
    df = df.copy()
    for cid, (lat, lon, _addr) in overrides.items():
        m = df["company_id"] == cid
        if m.any() and lat is not None and lon is not None:
            df.loc[m, ["lat", "lon", "geo_precision"]] = [lat, lon, "geocoded"]
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 2. CONSTANTS & ANCHOR COORDINATES
# ──────────────────────────────────────────────────────────────────────────────
TSMC_HQ = (24.7740, 121.0110)        # Fab 12, Hsinchu Science Park
FAB21 = (33.6730, -112.0520)         # TSMC Fab 21, North Phoenix, AZ
HSINCHU_CENTER = (24.7800, 121.0150)
PHOENIX_CENTER = (33.6200, -112.0700)

C_RED = "#ff3b3b"      # prime targets / announced
C_ORANGE = "#ff9f1c"   # strong candidates
C_YELLOW = "#ffd166"   # watchlist
C_GREY = "#5c677d"     # domestic anchors
C_CYAN = "#3fc1c9"     # tier-3 supply lines
C_BLUE = "#4361ee"     # inbound global supply

DATA_DIR = Path(__file__).parent / "data"

# Representative semiconductor-hub coordinates per ISO-3 country code. Used to
# place ETO / TSIA companies that have no precise HQ geocode (geo_precision =
# "country-approx"); upgrade to exact via the Google Places stub later.
COUNTRY_GEO = {
    "TWN": (24.78, 121.01, "Taiwan"),       "USA": (37.37, -121.97, "USA"),
    "CHN": (31.23, 121.47, "China"),        "KOR": (37.20, 127.07, "South Korea"),
    "JPN": (35.68, 139.76, "Japan"),        "DEU": (51.05, 13.74, "Germany"),
    "NLD": (51.41, 5.46, "Netherlands"),    "GBR": (52.20, 0.13, "UK"),
    "FRA": (45.18, 5.72, "France"),         "SGP": (1.35, 103.82, "Singapore"),
    "ITA": (45.46, 9.19, "Italy"),          "CHE": (47.38, 8.54, "Switzerland"),
    "ISR": (32.79, 35.02, "Israel"),        "MYS": (5.41, 100.33, "Malaysia"),
    "AUT": (46.61, 13.85, "Austria"),       "BEL": (50.88, 4.70, "Belgium"),
    "IRL": (53.35, -6.26, "Ireland"),       "CAN": (45.42, -75.70, "Canada"),
    "SWE": (59.33, 18.06, "Sweden"),        "FIN": (60.17, 24.94, "Finland"),
}

# Keywords that mark a global-supply input as AI-accelerator critical.
AI_INPUT_KEYWORDS = (
    "euv", "advanced packaging", "adv. pkg", "cowos", "hbm", "high bandwidth",
    "assembly", "packaging", "substrate", "photoresist", "resist", "cmp",
    "lithography", "etch", "deposition", "atomic layer", "wafer", "logic",
    "gpu", "advanced cpu", "interconnect", "bonding", "test",
)

# Real Tier-2 direct suppliers / partners of TSMC (mock metrics).
# phoenix: confirmed/announced AZ site coordinates (None = no site yet).
TIER2_REAL = [
    dict(name="ASE Group", category="OSAT / Advanced Packaging",
         product="CoWoS & SiP assembly, final test", city="Kaohsiung", country="Taiwan",
         lat=22.7310, lon=120.2840, cowos=True, euv=False, upc=False,
         capital=0.85, labor=0.60, revenue=21800, employees=96000,
         us_presence=True, tsmc_dep=35, phoenix=None),
    dict(name="Siliconware Precision (SPIL)", category="OSAT / Advanced Packaging",
         product="Flip-chip BGA, CoWoS back-end", city="Taichung", country="Taiwan",
         lat=24.2180, lon=120.6170, cowos=True, euv=False, upc=False,
         capital=0.82, labor=0.62, revenue=4100, employees=24000,
         us_presence=False, tsmc_dep=55, phoenix=None),
    dict(name="Gudeng Precision", category="EUV Infrastructure",
         product="EUV pods, FOUPs, reticle carriers", city="New Taipei", country="Taiwan",
         lat=24.9930, lon=121.4510, cowos=False, euv=True, upc=False,
         capital=0.75, labor=0.45, revenue=320, employees=1200,
         us_presence=True, tsmc_dep=75, phoenix=None),
    dict(name="Entegris", category="Ultra-Pure Materials Handling",
         product="FOUPs, sub-nm filtration, UHP fluid handling", city="Billerica (MA)", country="USA",
         lat=42.5540, lon=-71.2690, cowos=False, euv=True, upc=True,
         capital=0.88, labor=0.35, revenue=3500, employees=8000,
         us_presence=True, tsmc_dep=25, phoenix=None),
    dict(name="ASML", category="Lithography Systems",
         product="EUV scanners (NXE / EXE High-NA)", city="Veldhoven", country="Netherlands",
         lat=51.4030, lon=5.4570, cowos=False, euv=True, upc=False,
         capital=0.95, labor=0.30, revenue=30000, employees=42000,
         us_presence=True, tsmc_dep=30, phoenix=None),
    dict(name="Applied Materials", category="Deposition / Etch Tools",
         product="CVD, PVD, CMP, implant systems", city="Santa Clara (CA)", country="USA",
         lat=37.3670, lon=-121.9670, cowos=True, euv=False, upc=False,
         capital=0.92, labor=0.35, revenue=27000, employees=35000,
         us_presence=True, tsmc_dep=20, phoenix=None),
    dict(name="Tokyo Electron", category="Coat / Develop / Etch Tools",
         product="EUV coater-developer tracks, etch", city="Tokyo", country="Japan",
         lat=35.6520, lon=139.7410, cowos=False, euv=True, upc=False,
         capital=0.90, labor=0.38, revenue=15000, employees=17000,
         us_presence=True, tsmc_dep=22, phoenix=None),
    dict(name="Sunlit Chemical", category="Ultra-Pure Chemicals",
         product="Electronic-grade HF, H2SO4, NH4OH", city="Taipei", country="Taiwan",
         lat=25.0480, lon=121.5170, cowos=False, euv=False, upc=True,
         capital=0.80, labor=0.50, revenue=450, employees=900,
         us_presence=True, tsmc_dep=70, phoenix=(33.8150, -112.1150)),
    dict(name="LCY Chemical", category="Ultra-Pure Chemicals",
         product="Electronic-grade IPA, solvents", city="Taipei", country="Taiwan",
         lat=25.0410, lon=121.5650, cowos=False, euv=False, upc=True,
         capital=0.78, labor=0.48, revenue=1300, employees=2800,
         us_presence=True, tsmc_dep=60, phoenix=(33.4350, -112.0100)),
    dict(name="Chang Chun Group", category="Specialty Chemicals",
         product="H2O2, copper foil, epoxy resins", city="Taipei", country="Taiwan",
         lat=25.0460, lon=121.5310, cowos=False, euv=False, upc=True,
         capital=0.76, labor=0.52, revenue=4800, employees=11000,
         us_presence=False, tsmc_dep=40, phoenix=None),
    dict(name="Topco Scientific", category="Materials Distribution / Quartz",
         product="Quartzware, wafer reclaim, parts cleaning", city="Taipei", country="Taiwan",
         lat=25.0800, lon=121.5650, cowos=False, euv=False, upc=False,
         capital=0.60, labor=0.55, revenue=1500, employees=2400,
         us_presence=True, tsmc_dep=65, phoenix=None),
    dict(name="Unimicron", category="ABF Substrates",
         product="ABF substrates, CoWoS interposer carriers", city="Taoyuan", country="Taiwan",
         lat=24.9540, lon=121.2250, cowos=True, euv=False, upc=False,
         capital=0.80, labor=0.55, revenue=3600, employees=22000,
         us_presence=False, tsmc_dep=45, phoenix=None),
    dict(name="Kinsus Interconnect", category="IC Substrates",
         product="FC-BGA / FC-CSP substrates", city="Taoyuan", country="Taiwan",
         lat=24.9990, lon=121.2990, cowos=True, euv=False, upc=False,
         capital=0.78, labor=0.58, revenue=1100, employees=6500,
         us_presence=False, tsmc_dep=35, phoenix=None),
    dict(name="Foxsemicon (FITI)", category="Fab Equipment Modules",
         product="Tool chassis, fab automation, OEM modules", city="Zhunan", country="Taiwan",
         lat=24.6860, lon=120.8800, cowos=False, euv=False, upc=False,
         capital=0.75, labor=0.55, revenue=900, employees=4200,
         us_presence=True, tsmc_dep=80, phoenix=None),
    dict(name="Amkor Technology", category="OSAT / Advanced Packaging",
         product="Advanced packaging & test (AZ campus)", city="Tempe (AZ)", country="USA",
         lat=33.3310, lon=-111.8940, cowos=True, euv=False, upc=False,
         capital=0.84, labor=0.58, revenue=6500, employees=31000,
         us_presence=True, tsmc_dep=30, phoenix=(33.7660, -112.3100)),
    dict(name="Marketech International", category="Cleanroom / Facility Integration",
         product="Cleanroom build-out, hookup, UHP piping", city="Taipei", country="Taiwan",
         lat=25.0570, lon=121.6120, cowos=False, euv=False, upc=False,
         capital=0.55, labor=0.72, revenue=2200, employees=3800,
         us_presence=True, tsmc_dep=70, phoenix=None),
    # ── AI-accelerator critical path (HBM, wafers, photoresist, test, substrates) ──
    dict(name="SK Hynix", category="HBM Memory",
         product="HBM3E/HBM4 stacks for AI accelerators", city="Icheon", country="South Korea",
         lat=37.2750, lon=127.4350, cowos=False, euv=True, upc=False,
         capital=0.93, labor=0.32, revenue=30000, employees=31000,
         us_presence=True, tsmc_dep=15, phoenix=None),
    dict(name="Micron Technology", category="HBM Memory",
         product="HBM3E, GDDR for AI / datacenter", city="Boise (ID)", country="USA",
         lat=43.6150, lon=-116.2023, cowos=False, euv=True, upc=False,
         capital=0.92, labor=0.33, revenue=25000, employees=48000,
         us_presence=True, tsmc_dep=12, phoenix=None),
    dict(name="Samsung Electronics", category="HBM Memory",
         product="HBM3E + advanced foundry", city="Hwaseong", country="South Korea",
         lat=37.2000, lon=127.0700, cowos=False, euv=True, upc=False,
         capital=0.94, labor=0.30, revenue=60000, employees=75000,
         us_presence=True, tsmc_dep=5, phoenix=None),
    dict(name="Disco Corporation", category="Wafer Dicing & Grinding",
         product="Precision dicing & grinding for CoWoS", city="Tokyo", country="Japan",
         lat=35.6100, lon=139.6300, cowos=True, euv=False, upc=False,
         capital=0.85, labor=0.40, revenue=2800, employees=6500,
         us_presence=True, tsmc_dep=35, phoenix=None),
    dict(name="Shin-Etsu Chemical", category="Silicon Wafers",
         product="300mm prime wafers, EUV photoresist", city="Tokyo", country="Japan",
         lat=35.6700, lon=139.7600, cowos=False, euv=True, upc=True,
         capital=0.88, labor=0.42, revenue=16000, employees=25000,
         us_presence=True, tsmc_dep=20, phoenix=None),
    dict(name="SUMCO", category="Silicon Wafers",
         product="300mm epitaxial & polished wafers", city="Tokyo", country="Japan",
         lat=35.6600, lon=139.7300, cowos=False, euv=False, upc=True,
         capital=0.86, labor=0.45, revenue=3000, employees=9000,
         us_presence=True, tsmc_dep=25, phoenix=None),
    dict(name="Tokyo Ohka Kogyo (TOK)", category="Photoresist",
         product="EUV & ArF photoresist", city="Kawasaki", country="Japan",
         lat=35.5300, lon=139.7000, cowos=False, euv=True, upc=True,
         capital=0.80, labor=0.45, revenue=1300, employees=4000,
         us_presence=True, tsmc_dep=28, phoenix=None),
    dict(name="JSR Corporation", category="Photoresist",
         product="EUV photoresist, CMP slurry", city="Tokyo", country="Japan",
         lat=35.6580, lon=139.7510, cowos=False, euv=True, upc=True,
         capital=0.82, labor=0.43, revenue=2500, employees=9000,
         us_presence=True, tsmc_dep=22, phoenix=None),
    dict(name="Ibiden", category="ABF Substrates",
         product="ABF substrates for AI GPU packages", city="Ogaki", country="Japan",
         lat=35.3590, lon=136.6120, cowos=True, euv=False, upc=False,
         capital=0.84, labor=0.50, revenue=3000, employees=13000,
         us_presence=False, tsmc_dep=30, phoenix=None),
    dict(name="Shinko Electric", category="IC Substrates",
         product="FC-BGA substrates, lead frames", city="Nagano", country="Japan",
         lat=36.6510, lon=138.1810, cowos=True, euv=False, upc=False,
         capital=0.81, labor=0.52, revenue=1800, employees=6000,
         us_presence=False, tsmc_dep=28, phoenix=None),
    dict(name="Advantest", category="Test Systems",
         product="ATE for AI SoC & HBM test", city="Tokyo", country="Japan",
         lat=35.6900, lon=139.6900, cowos=False, euv=False, upc=False,
         capital=0.78, labor=0.45, revenue=4800, employees=7500,
         us_presence=True, tsmc_dep=30, phoenix=None),
    dict(name="Lam Research", category="Deposition / Etch Tools",
         product="Etch, deposition, EUV dry resist", city="Fremont (CA)", country="USA",
         lat=37.5490, lon=-121.9880, cowos=False, euv=True, upc=False,
         capital=0.90, labor=0.36, revenue=14000, employees=17000,
         us_presence=True, tsmc_dep=20, phoenix=None),
]

# Tier-3 catalog: (category, product, cowos, euv, upc, capital-range, labor-range)
TIER3_CATALOG = [
    ("Raw Quartz & Crucibles", "Synthetic quartz tubes, rods & crucibles", 0, 0, 0, (0.55, 0.75), (0.45, 0.65)),
    ("Specialty Resins & Encapsulants", "Underfill & molding compounds for CoWoS", 1, 0, 0, (0.60, 0.80), (0.40, 0.60)),
    ("Precision CNC Machining", "Vacuum chamber & robot-arm components", 0, 0, 0, (0.50, 0.70), (0.60, 0.85)),
    ("UHP Valves & Fittings", "Ultra-high-purity gas delivery hardware", 0, 0, 1, (0.60, 0.80), (0.45, 0.60)),
    ("Technical Ceramics", "Electrostatic chucks, ceramic end-effectors", 1, 0, 0, (0.70, 0.85), (0.40, 0.55)),
    ("FFKM Seals & O-Rings", "Perfluoroelastomer seals for etch chambers", 0, 0, 0, (0.60, 0.80), (0.40, 0.60)),
    ("Photoresist Precursors", "PAGs & monomers for EUV photoresist", 0, 1, 1, (0.75, 0.90), (0.30, 0.50)),
    ("CMP Slurry & Abrasives", "Ceria/silica slurry for CoWoS planarization", 1, 0, 1, (0.70, 0.85), (0.35, 0.55)),
    ("UHP Filtration Media", "Sub-nm liquid filtration membranes", 0, 0, 1, (0.75, 0.90), (0.30, 0.50)),
    ("EUV Pod Components", "Carbon-composite pod shells & latches", 0, 1, 0, (0.65, 0.85), (0.40, 0.60)),
    ("Wafer Carrier Molding", "FOUP / FOSB precision injection molding", 0, 1, 0, (0.55, 0.75), (0.50, 0.70)),
    ("Specialty Gas Cabinets", "Gas cabinets, VMBs, abatement skids", 0, 0, 1, (0.55, 0.75), (0.55, 0.75)),
    ("Cleanroom Systems", "FFUs, HEPA assemblies, panel systems", 0, 0, 0, (0.45, 0.65), (0.60, 0.85)),
    ("UHP Stainless Piping", "Electropolished 316L tube, orbital welding", 0, 0, 1, (0.50, 0.70), (0.60, 0.80)),
    ("Precision Optics Polishing", "Sub-angstrom mirror polishing & metrology", 0, 1, 0, (0.80, 0.95), (0.30, 0.50)),
    ("Chemical Logistics", "UHP chemical drumming, ISO tanks, last-mile", 0, 0, 1, (0.40, 0.60), (0.70, 0.90)),
]

# Plausible Tier-2 customers for each Tier-3 category
PARENT_POOL = {
    "Raw Quartz & Crucibles": ["Topco Scientific", "Foxsemicon (FITI)", "Tokyo Electron", "Shin-Etsu Chemical", "SUMCO"],
    "Specialty Resins & Encapsulants": ["ASE Group", "Siliconware Precision (SPIL)", "Unimicron", "Kinsus Interconnect", "Ibiden", "Shinko Electric"],
    "Precision CNC Machining": ["Foxsemicon (FITI)", "Applied Materials", "Tokyo Electron", "ASML", "Lam Research", "Disco Corporation", "Advantest"],
    "UHP Valves & Fittings": ["Marketech International", "Foxsemicon (FITI)", "Applied Materials", "Lam Research"],
    "Technical Ceramics": ["Applied Materials", "Tokyo Electron", "Foxsemicon (FITI)", "Disco Corporation", "Lam Research"],
    "FFKM Seals & O-Rings": ["Applied Materials", "Tokyo Electron", "Marketech International", "Lam Research"],
    "Photoresist Precursors": ["Chang Chun Group", "Entegris", "Sunlit Chemical", "Tokyo Ohka Kogyo (TOK)", "JSR Corporation", "Shin-Etsu Chemical"],
    "CMP Slurry & Abrasives": ["Entegris", "Chang Chun Group", "LCY Chemical", "JSR Corporation"],
    "UHP Filtration Media": ["Entegris", "Sunlit Chemical", "LCY Chemical"],
    "EUV Pod Components": ["Gudeng Precision"],
    "Wafer Carrier Molding": ["Gudeng Precision", "Entegris"],
    "Specialty Gas Cabinets": ["Marketech International", "Foxsemicon (FITI)"],
    "Cleanroom Systems": ["Marketech International", "Foxsemicon (FITI)"],
    "UHP Stainless Piping": ["Marketech International", "Sunlit Chemical"],
    "Precision Optics Polishing": ["ASML", "Gudeng Precision"],
    "Chemical Logistics": ["Sunlit Chemical", "LCY Chemical", "Chang Chun Group"],
}

# AI-accelerator critical-path categories — what actually gates GPU/TPU output:
# advanced packaging (CoWoS), HBM, advanced logic (EUV), advanced substrates,
# leading-edge wafers/photoresist, and the Tier-3 inputs feeding them.
AI_SUPPLY_CATEGORIES = {
    "Foundry (Anchor)", "OSAT / Advanced Packaging", "ABF Substrates", "IC Substrates",
    "Lithography Systems", "EUV Infrastructure", "HBM Memory", "Silicon Wafers",
    "Photoresist", "Test Systems", "Deposition / Etch Tools", "Coat / Develop / Etch Tools",
    "Wafer Dicing & Grinding", "Specialty Resins & Encapsulants", "CMP Slurry & Abrasives",
    "Technical Ceramics", "Photoresist Precursors", "EUV Pod Components",
    "Precision Optics Polishing", "Wafer Carrier Molding",
}


def is_ai_supply(category: str, cowos: bool, euv: bool, tier: int) -> bool:
    """A company is on the AI-accelerator path if it touches CoWoS/EUV, is the
    foundry anchor, or sits in an AI-critical category (HBM, substrates, etc.)."""
    return bool(tier == 1 or cowos or euv or category in AI_SUPPLY_CATEGORIES)

# Geographic clusters for Tier-3 generation: (label, lat, lon, weight)
TIER3_CLUSTERS = [
    ("Hsinchu", 24.7800, 121.0200, 0.40),
    ("Taichung", 24.1600, 120.6500, 0.15),
    ("Tainan (STSP)", 23.0900, 120.2800, 0.13),
    ("Kaohsiung", 22.6500, 120.3200, 0.10),
    ("Taoyuan", 24.9700, 121.2700, 0.12),
    ("Osaka", 34.6900, 135.5000, 0.06),
    ("Kumamoto", 32.8000, 130.7100, 0.04),
]

NAME_PREFIX = ["Hsin", "Yong", "Jin", "Tai", "Kuo", "Wei", "Feng", "Da", "Sheng", "Chia",
               "Lien", "Ruey", "Teng", "Hua", "Cheng", "Long", "Ming", "Quan", "Bao", "Yu"]
NAME_MID = ["Sheng", "Hong", "Jia", "Wang", "Tien", "Pin", "Lin", "Tsai", "Kang", "Fu",
            "Hsiang", "Chuan", "Ye", "Mao", "Hsi", "Ting", "An", "Ho", "Chi", "Sung"]
CATEGORY_WORD = {
    "Raw Quartz & Crucibles": "Quartz", "Specialty Resins & Encapsulants": "Polymer",
    "Precision CNC Machining": "Precision", "UHP Valves & Fittings": "Fluidtech",
    "Technical Ceramics": "Ceramics", "FFKM Seals & O-Rings": "Sealing",
    "Photoresist Precursors": "Fine Chemical", "CMP Slurry & Abrasives": "Abrasives",
    "UHP Filtration Media": "Membrane", "EUV Pod Components": "Composite",
    "Wafer Carrier Molding": "Molding", "Specialty Gas Cabinets": "Gas Systems",
    "Cleanroom Systems": "Cleantech", "UHP Stainless Piping": "Stainless",
    "Precision Optics Polishing": "Optics", "Chemical Logistics": "Logistics",
}

N_TIER3 = 38  # 1 (TSMC) + 28 (Tier 2) + 38 (Tier 3) = 67 companies


# ──────────────────────────────────────────────────────────────────────────────
# 3. MOCK DATA GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def generate_dataset(seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []

    # ── Tier 1 anchor ──
    rows.append(dict(
        company_id="T1-00", name="TSMC", tier=1,
        category="Foundry (Anchor)", product="Leading-edge logic wafers (N3/N2), CoWoS",
        city="Hsinchu", country="Taiwan", lat=TSMC_HQ[0], lon=TSMC_HQ[1],
        supplies_to="—", supplies_to_id=None,
        cowos=True, euv=True, upc=True,
        capital_intensity=0.98, labor_intensity=0.30,
        revenue_musd=88000, employees=77000,
        tsmc_dependence_pct=100, us_presence=True,
        phoenix_lat=FAB21[0], phoenix_lon=FAB21[1],
        ai_supply_chain=True,
    ))

    # ── Tier 2 (real players, mock metrics) ──
    name_to_id = {}
    for i, t2 in enumerate(TIER2_REAL):
        cid = f"T2-{i + 1:02d}"
        name_to_id[t2["name"]] = cid
        px, py = (t2["phoenix"] if t2["phoenix"] else (np.nan, np.nan))
        rows.append(dict(
            company_id=cid, name=t2["name"], tier=2,
            category=t2["category"], product=t2["product"],
            city=t2["city"], country=t2["country"], lat=t2["lat"], lon=t2["lon"],
            supplies_to="TSMC", supplies_to_id="T1-00",
            cowos=t2["cowos"], euv=t2["euv"], upc=t2["upc"],
            capital_intensity=t2["capital"], labor_intensity=t2["labor"],
            revenue_musd=t2["revenue"], employees=t2["employees"],
            tsmc_dependence_pct=t2["tsmc_dep"], us_presence=t2["us_presence"],
            phoenix_lat=px, phoenix_lon=py,
            ai_supply_chain=is_ai_supply(t2["category"], t2["cowos"], t2["euv"], 2),
        ))

    # ── Tier 3 (generated sub-suppliers) ──
    used_names = set()
    for i in range(N_TIER3):
        cat, product, cowos, euv, upc, cap_rng, lab_rng = TIER3_CATALOG[i % len(TIER3_CATALOG)]

        # unique plausible name
        for _ in range(50):
            nm = f"{rng.choice(NAME_PREFIX)}{rng.choice(NAME_MID)} {CATEGORY_WORD[cat]} Co."
            if nm not in used_names:
                used_names.add(nm)
                break

        # weighted geographic cluster + jitter (dense around science parks)
        r = rng.random()
        acc = 0.0
        for label, clat, clon, w in TIER3_CLUSTERS:
            acc += w
            if r <= acc:
                city, lat, lon = label, clat, clon
                break
        lat += rng.uniform(-0.055, 0.055)
        lon += rng.uniform(-0.055, 0.055)
        country = "Japan" if city in ("Osaka", "Kumamoto") else "Taiwan"

        parent = rng.choice(PARENT_POOL[cat])
        rows.append(dict(
            company_id=f"T3-{i + 1:02d}", name=nm, tier=3,
            category=cat, product=product,
            city=city, country=country, lat=round(lat, 4), lon=round(lon, 4),
            supplies_to=parent, supplies_to_id=name_to_id[parent],
            cowos=bool(cowos), euv=bool(euv), upc=bool(upc),
            capital_intensity=round(rng.uniform(*cap_rng), 2),
            labor_intensity=round(rng.uniform(*lab_rng), 2),
            revenue_musd=int(rng.uniform(8, 400)),
            employees=int(rng.uniform(30, 900)),
            tsmc_dependence_pct=int(rng.uniform(30, 95)),
            us_presence=rng.random() < 0.12,
            phoenix_lat=np.nan, phoenix_lon=np.nan,
            ai_supply_chain=is_ai_supply(cat, bool(cowos), bool(euv), 3),
        ))

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# 3b. EXTERNAL DATA INGESTION  (ETO Chip Explorer + TSIA) with de-duplication
# ──────────────────────────────────────────────────────────────────────────────
# Provenance: real company names + (for ETO) real market-share relationships.
# Metrics we cannot source (capex/labor intensity, revenue) remain illustrative,
# consistent with the rest of the app. See data/SOURCES.md for attribution.

_SUFFIX_RE = re.compile(
    r"\b(corporation|corp|incorporated|inc|co|ltd|limited|llc|group|holding|holdings|"
    r"company|plc|ag|nv|bv|sa|gmbh|kk|intl|international|taiwan|usa|america|"
    r"technology|technologies|electronics|electronic|semiconductor|semiconductors|"
    r"microelectronics|manufacturing|mfg|industrial|industries|industry)\b"
)
_KNOWN_FOUNDRIES = {"tsmc", "samsung", "umc", "smic", "globalfoundries", "powerchip",
                    "vanguard", "intel", "hua hong", "episil", "tower", "dbhitek"}
_KNOWN_FABLESS = {"nvidia", "amd", "qualcomm", "broadcom", "mediatek", "apple", "arm",
                  "realtek", "sunplus", "marvell", "cadence", "synopsys", "graphcore",
                  "cerebras", "google", "tesla", "hisilicon", "cambricon", "xilinx"}


def normalize_name(s: str) -> str:
    """Collapse a company name to a dedup key (drop suffixes/parentheticals/punct)."""
    s = str(s).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_ai_input(text: str) -> bool:
    t = str(text).lower()
    return any(k in t for k in AI_INPUT_KEYWORDS)


def _flags_from_input(text: str):
    """Infer (cowos, euv, upc) advanced-tech flags from an input/segment name."""
    t = str(text).lower()
    cowos = any(k in t for k in ("packaging", "assembly", "cowos", "substrate", "bonding", "interposer"))
    euv = any(k in t for k in ("euv", "lithography", "photoresist", "resist", "mask"))
    upc = any(k in t for k in ("chemical", "cmp", "slurry", "gas", "clean", "etch", "deposition", "material"))
    return cowos, euv, upc


def _role_and_intensity(role: str):
    """Default (capital, labor) intensity by coarse role — illustrative."""
    return {
        "Foundry / IDM": (0.95, 0.30), "Equipment": (0.90, 0.35),
        "Materials": (0.80, 0.45), "ATP / Packaging": (0.82, 0.58),
        "Design / IP": (0.70, 0.40), "Memory": (0.92, 0.33),
    }.get(role, (0.78, 0.48))


@st.cache_data(show_spinner=False)
def load_eto() -> pd.DataFrame:
    """Real organizations + their headline market-share provision from ETO."""
    pdir = DATA_DIR / "eto"
    if not (pdir / "providers.csv").exists():
        return pd.DataFrame()
    providers = pd.read_csv(pdir / "providers.csv")
    provision = pd.read_csv(pdir / "provision.csv")
    inputs = pd.read_csv(pdir / "inputs.csv")
    itype = dict(zip(inputs["input_id"], inputs["type"]))

    orgs = providers[providers["provider_type"] == "organization"].copy()
    # drop generic placeholders (e.g. "Various companies") — not real entities
    orgs = orgs[~orgs["provider_name"].str.contains(
        r"various|^other$|unknown|n/a|misc", case=False, na=False)]
    prov = provision.copy()
    prov["itype"] = prov["provided_id"].map(itype)

    recs = []
    for _, o in orgs.iterrows():
        name = str(o["provider_name"]).strip()
        sub = prov[prov["provider_name"] == name]
        # headline = the input where this org holds the largest known share
        headline, share, types = "Semiconductor supply", np.nan, []
        if len(sub):
            types = sub["itype"].dropna().tolist()
            ranked = sub.sort_values("share_provided", ascending=False, na_position="last")
            headline = str(ranked.iloc[0]["provided_name"])
            share = ranked.iloc[0]["share_provided"]
        key = normalize_name(name)
        if key in _KNOWN_FOUNDRIES:
            role = "Foundry / IDM"
        elif key in _KNOWN_FABLESS or "design_resource" in types:
            role = "Design / IP"
        elif any("assembly" in str(h).lower() or "packaging" in str(h).lower() for h in [headline]):
            role = "ATP / Packaging"
        elif "tool_resource" in types:
            role = "Equipment"
        elif "material_resource" in types:
            role = "Materials"
        else:
            role = "Supply-base"
        recs.append(dict(
            src_name=name, country_code=str(o["country"]) if pd.notna(o["country"]) else "",
            role=role, headline=headline, market_share_pct=share,
        ))
    return pd.DataFrame(recs)


@st.cache_data(show_spinner=False)
def load_tsia() -> pd.DataFrame:
    """TSIA member directory — page 1 (partial). Chinese original preserved."""
    f = DATA_DIR / "tsia" / "members.csv"
    if not f.exists():
        return pd.DataFrame()
    return pd.read_csv(f)


@st.cache_data(show_spinner="Ingesting ETO + TSIA data…")
def build_unified_dataset(seed: int = 42) -> pd.DataFrame:
    """Merge curated TSMC tree + ETO + TSIA into one deduped frame.

    Curated rows are authoritative (precise coords, Phoenix intel, tier tree).
    External rows enrich a match (adds market share + source tag) or are appended
    as global supply-base nodes (country-approx coords, outside the curated tree).
    """
    df = generate_dataset(seed).copy()
    # annotate curated rows with the new provenance columns
    df["data_source"] = "Curated"
    df["local_name"] = ""
    df["role"] = df["category"]
    df["market_share_pct"] = np.nan
    df["geo_precision"] = "site"
    df["in_core_tree"] = True
    df["name_verified"] = True
    df["website"] = ""
    df["affiliate"] = False

    by_key = {normalize_name(n): i for i, n in zip(df.index, df["name"])}
    rng = random.Random(seed + 7)
    new_rows = []
    next_id = 1

    def enrich(idx, source, share=np.nan, local=""):
        cur = df.at[idx, "data_source"]
        if source not in cur:
            df.at[idx, "data_source"] = f"{cur} + {source}"
        if pd.notna(share) and pd.isna(df.at[idx, "market_share_pct"]):
            df.at[idx, "market_share_pct"] = share
        if local and not df.at[idx, "local_name"]:
            df.at[idx, "local_name"] = local

    # ── ETO organizations ──
    eto = load_eto()
    for _, e in eto.iterrows():
        key = normalize_name(e["src_name"])
        if not key:
            continue
        if key in by_key:
            if by_key[key] is not None:                 # match an existing curated row
                enrich(by_key[key], "ETO", e["market_share_pct"])
            # else: duplicate within ETO already reserved — drop the second copy
            continue
        cc = e["country_code"]
        geo = COUNTRY_GEO.get(cc)
        if geo:
            lat = geo[0] + rng.uniform(-0.25, 0.25)
            lon = geo[1] + rng.uniform(-0.25, 0.25)
            country = geo[2]
        else:
            lat, lon, country = np.nan, np.nan, (cc or "Unknown")
        cowos, euv, upc = _flags_from_input(e["headline"])
        cap, lab = _role_and_intensity(e["role"])
        ai = is_ai_input(e["headline"]) or e["role"] in ("Foundry / IDM", "ATP / Packaging") or euv or cowos
        rid = f"E-{next_id:03d}"
        next_id += 1
        new_rows.append(dict(
            company_id=rid, name=str(e["src_name"]), tier=2,
            category=e["role"], product=str(e["headline"]),
            city=country, country=country, lat=lat, lon=lon,
            supplies_to=f"{e['headline']} (global market)", supplies_to_id=None,
            cowos=cowos, euv=euv, upc=upc,
            capital_intensity=cap, labor_intensity=lab,
            revenue_musd=np.nan, employees=np.nan,
            tsmc_dependence_pct=np.nan, us_presence=(cc == "USA"),
            phoenix_lat=np.nan, phoenix_lon=np.nan, ai_supply_chain=bool(ai),
            data_source="ETO", local_name="", role=e["role"],
            market_share_pct=e["market_share_pct"],
            geo_precision=("country-approx" if geo else "ungeocoded"),
            in_core_tree=False, name_verified=True, website="", affiliate=False,
        ))
        by_key[key] = None  # reserve so later sources dedup against it

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else df
    by_key = {normalize_name(n): i for i, n in zip(df.index, df["name"])}

    # ── TSIA members ──
    tsia = load_tsia()
    tsia_rows = []
    for _, t in tsia.iterrows():
        key = normalize_name(t["name"])
        if key in by_key and by_key[key] is not None:
            enrich(by_key[key], "TSIA", local=str(t["local_name"]))
            continue
        geo = COUNTRY_GEO.get(t["country"], COUNTRY_GEO["TWN"])
        lat = geo[0] + rng.uniform(-0.25, 0.25)
        lon = geo[1] + rng.uniform(-0.25, 0.25)
        seg = str(t["segment"])
        nv = t["name_verified"] in (True, "True")
        cowos, euv, upc = _flags_from_input(seg)
        ai = is_ai_input(seg) or "foundry" in seg.lower() or "memory" in seg.lower()
        rid = f"S-{len(tsia_rows) + 1:03d}"
        tsia_rows.append(dict(
            company_id=rid, name=str(t["name"]), tier=2,
            category=seg, product=seg, city=geo[2], country=geo[2],
            lat=lat, lon=lon, supplies_to="TSIA member (Taiwan)", supplies_to_id=None,
            cowos=cowos, euv=euv, upc=upc,
            capital_intensity=0.80, labor_intensity=0.45,
            revenue_musd=np.nan, employees=np.nan,
            tsmc_dependence_pct=np.nan, us_presence=False,
            phoenix_lat=np.nan, phoenix_lon=np.nan, ai_supply_chain=bool(ai),
            data_source="TSIA", local_name=str(t["local_name"]), role=seg,
            market_share_pct=np.nan, geo_precision="country-approx", in_core_tree=False,
            name_verified=nv, website=str(t.get("website", "")),
            affiliate=(t.get("affiliate") in (True, "True")),
        ))
        by_key[key] = None

    if tsia_rows:
        df = pd.concat([df, pd.DataFrame(tsia_rows)], ignore_index=True)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 4. NETWORKX GRAPH + AI CRITICALITY / MIGRATION SCORING ENGINE
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def build_graph_and_scores(df: pd.DataFrame):
    """Build the directed supply graph (supplier → customer) and score every node.

    Centrality is computed on the curated TSMC tree only (in_core_tree); the
    ETO/TSIA global supply base has no modeled directed edges to TSMC, so adding
    them as isolated nodes would distort everyone's centrality."""
    core = df[df["in_core_tree"]] if "in_core_tree" in df.columns else df
    G = nx.DiGraph()
    for _, r in core.iterrows():
        G.add_node(r["company_id"], name=r["name"], tier=r["tier"], category=r["category"])
    for _, r in core.iterrows():
        if r["supplies_to_id"]:
            G.add_edge(r["company_id"], r["supplies_to_id"])

    centrality = nx.degree_centrality(G.to_undirected())
    betweenness = nx.betweenness_centrality(G.to_undirected())

    def score_row(r) -> int:
        """
        US MIGRATION LIKELIHOOD (1-100)
        ───────────────────────────────
        Base                              +20
        CoWoS advanced packaging          +25   (heaviest: AZ's biggest gap)
        EUV handling / infrastructure     +22
        Ultra-pure chemicals              +20   (can't ship UHP HF across the Pacific)
        Capital- vs labor-intensity       ±15   (capex travels; cheap labor doesn't)
        TSMC revenue dependence           +0–10 (anchor gravity)
        Existing US presence              +8    (beachhead established)
        Network centrality                +0–10 (chokepoint suppliers get pulled)
        Revenue scale                     +0–5  (ability to fund a US plant)
        Market-share criticality          +0–10 (ETO real share — dominance ⇒ pull)
        """
        s = 20.0
        if r["cowos"]:
            s += 25
        if r["euv"]:
            s += 22
        if r["upc"]:
            s += 20
        s += float(np.clip((r["capital_intensity"] - r["labor_intensity"]) * 30, -15, 15))
        if pd.notna(r["tsmc_dependence_pct"]):
            s += r["tsmc_dependence_pct"] * 0.10
        if r["us_presence"]:
            s += 8
        s += min(centrality.get(r["company_id"], 0) * 60, 10)
        if pd.notna(r["revenue_musd"]):
            s += min(math.log10(max(r["revenue_musd"], 1)) / 4, 1) * 5
        # Real ETO market share: a dominant global supplier is a chokepoint TSMC
        # cannot easily re-source, so Phoenix must pull it along.
        if pd.notna(r.get("market_share_pct")):
            s += min(float(r["market_share_pct"]) / 10.0, 10)
        return int(np.clip(s, 1, 100))

    scores, statuses = [], []
    for _, r in df.iterrows():
        if r["tier"] == 1:
            scores.append(100)
            statuses.append("⚓ TIER-1 ANCHOR (Fab 21 live)")
            continue
        sc = score_row(r)
        scores.append(sc)
        if pd.notna(r["phoenix_lat"]):
            statuses.append("🟥 ANNOUNCED AZ SITE")
        elif r["country"] == "USA":
            statuses.append("🇺🇸 US-DOMICILED")
        elif sc >= 70 and r["country"] == "Taiwan":
            statuses.append("🟧 PRIME MIGRATION TARGET")
        elif sc >= 55:
            statuses.append("🟨 STRONG CANDIDATE")
        elif sc >= 40:
            statuses.append("🟦 WATCHLIST")
        else:
            statuses.append("⬜ DOMESTIC ANCHOR")

    out = df.copy()
    out["migration_score"] = scores
    out["status"] = statuses
    bt = {k: round(v, 4) for k, v in betweenness.items()}
    return out, bt


def build_graph(df: pd.DataFrame) -> nx.DiGraph:
    """Rebuild the curated-tree DiGraph (not cached — avoids pickle issues)."""
    core = df[df["in_core_tree"]] if "in_core_tree" in df.columns else df
    G = nx.DiGraph()
    for _, r in core.iterrows():
        G.add_node(r["company_id"], name=r["name"], tier=r["tier"], category=r["category"])
    for _, r in core.iterrows():
        if r["supplies_to_id"]:
            G.add_edge(r["company_id"], r["supplies_to_id"])
    return G


def score_color(score: int) -> str:
    if score >= 70:
        return C_RED
    if score >= 55:
        return C_ORANGE
    if score >= 40:
        return C_YELLOW
    return C_GREY


# ──────────────────────────────────────────────────────────────────────────────
# 5. GEOSPATIAL HELPERS — curved arcs & map builders
# ──────────────────────────────────────────────────────────────────────────────
def curved_points(p1, p2, curvature=0.20, n=50):
    """Quadratic-Bezier arc between two (lat, lon) points; bulges 'great-circle' north."""
    lat1, lon1 = p1
    lat2, lon2 = p2
    dlat, dlon = lat2 - lat1, lon2 - lon1
    dist = math.hypot(dlat, dlon)
    if dist < 1e-9:
        return [p1, p2]
    # unit perpendicular (arcs poleward for eastbound trans-Pacific routes)
    ux, uy = dlon / dist, -dlat / dist
    clat = (lat1 + lat2) / 2 + ux * dist * curvature
    clon = (lon1 + lon2) / 2 + uy * dist * curvature
    ts = np.linspace(0, 1, n)
    return [
        ((1 - t) ** 2 * lat1 + 2 * (1 - t) * t * clat + t ** 2 * lat2,
         (1 - t) ** 2 * lon1 + 2 * (1 - t) * t * clon + t ** 2 * lon2)
        for t in ts
    ]


def gshift(lon: float) -> float:
    """Shift Americas longitudes east (+360) so Pacific-centered arcs render correctly."""
    return lon + 360 if lon < -30 else lon


def popup_html(r) -> str:
    c = score_color(int(r["migration_score"]))
    src = r.get("data_source", "Curated")
    dep = (f"TSMC dependence: {int(r['tsmc_dependence_pct'])}%<br>"
           if pd.notna(r.get("tsmc_dependence_pct")) else "")
    share = (f"<span style='color:#3fc1c9'>ETO market share: "
             f"<b>{float(r['market_share_pct']):.1f}%</b></span><br>"
             if pd.notna(r.get("market_share_pct")) else "")
    geo = ("<span style='color:#7a8699;font-size:10px'>⚲ country-approx location</span><br>"
           if r.get("geo_precision") == "country-approx" else "")
    local = (f"<span style='color:#8d99ae'>{r['local_name']}</span><br>"
             if r.get("local_name") else "")
    return (
        "<div style='font-family:monospace;background:#0b0f1a;color:#e6e6e6;"
        "padding:10px;min-width:230px;border-radius:6px'>"
        f"<b style='color:{c};font-size:13px'>{r['name']}</b><br>"
        f"{local}"
        f"<span style='color:#8d99ae'>Tier {r['tier']} · {r['category']}</span><br>"
        f"<span style='color:#8d99ae'>{r['product']}</span><br><br>"
        f"Migration score: <b style='color:{c}'>{int(r['migration_score'])}/100</b><br>"
        f"Status: {r['status']}<br>"
        f"{share}"
        f"Supplies → {r['supplies_to']}<br>"
        f"{dep}{geo}"
        f"<span style='color:#5c677d;font-size:10px'>source: {src}</span>"
        "</div>"
    )


def add_company_marker(m, r, lat, lon, radius_scale=1.0):
    if pd.isna(lat) or pd.isna(lon):   # ungeocoded external rows
        return
    sc = int(r["migration_score"])
    # country-approx markers get a hollow ring to distinguish from precise sites
    approx = r.get("geo_precision") == "country-approx"
    folium.CircleMarker(
        location=(lat, lon),
        radius=(3 + sc / 14) * radius_scale,
        color=score_color(sc),
        weight=1.5,
        fill=True,
        fill_color=score_color(sc),
        fill_opacity=0.15 if approx else (0.75 if r["tier"] < 3 else 0.55),
        tooltip=f"{r['name']} · {sc}/100",
        popup=folium.Popup(popup_html(r), max_width=300),
    ).add_to(m)


def add_sauron_eye(m, loc, label="TSMC FAB 21"):
    """The Eye: concentric surveillance rings + glowing pupil at Fab 21."""
    for radius, op in [(28, 0.9), (18, 0.6), (9, 0.35)]:
        folium.CircleMarker(loc, radius=radius, color=C_RED, weight=1,
                            fill=False, opacity=op).add_to(m)
    folium.Marker(
        loc,
        tooltip=label,
        icon=folium.DivIcon(html=(
            "<div style='font-size:26px;text-shadow:0 0 14px #ff3b3b,0 0 30px #ff3b3b;'>👁️</div>"
        )),
    ).add_to(m)


def base_map(center, zoom, min_zoom=2):
    return folium.Map(location=center, zoom_start=zoom, tiles="CartoDB dark_matter",
                      min_zoom=min_zoom, control_scale=True)


def build_global_map(df: pd.DataFrame, show_arcs: bool) -> folium.Map:
    """A. Global Macro — Asia↔US logistics corridors, Pacific-centered."""
    m = base_map([30, 180], 3)

    for _, r in df.iterrows():
        add_company_marker(m, r, r["lat"], gshift(r["lon"]))

    fab21_shifted = (FAB21[0], gshift(FAB21[1]))
    add_sauron_eye(m, fab21_shifted)
    folium.Marker(
        (TSMC_HQ[0], TSMC_HQ[1]), tooltip="TSMC HQ · Hsinchu Science Park",
        icon=folium.DivIcon(html="<div style='font-size:20px;text-shadow:0 0 10px #ffd166;'>🏯</div>"),
    ).add_to(m)

    if show_arcs:
        # Arcs are drawn only for the curated TSMC tree — the ETO/TSIA global
        # supply base shows as markers, not speculative migration corridors.
        core = df[df["in_core_tree"]] if "in_core_tree" in df.columns else df
        # Outbound migration corridors: Taiwan → Phoenix
        tw = core[(core["country"] == "Taiwan") & (core["tier"] > 1)]
        for _, r in tw.iterrows():
            announced = pd.notna(r["phoenix_lat"])
            if not announced and r["migration_score"] < 60:
                continue
            pts = curved_points((r["lat"], r["lon"]), fab21_shifted, curvature=0.18)
            if announced:
                AntPath(pts, color=C_RED, weight=2.5, opacity=0.85,
                        delay=800, dash_array=[12, 24], pulse_color=C_YELLOW,
                        tooltip=f"{r['name']} → Fab 21 (ANNOUNCED)").add_to(m)
            else:
                folium.PolyLine(pts, color=C_ORANGE, weight=1.6, opacity=0.55,
                                dash_array="6,10",
                                tooltip=f"{r['name']} → Fab 21 (projected, {int(r['migration_score'])}/100)"
                                ).add_to(m)

        # Inbound global supply: foreign curated Tier-2 → TSMC Hsinchu
        for _, r in core[(core["country"] != "Taiwan") & (core["tier"] == 2)].iterrows():
            pts = curved_points((r["lat"], gshift(r["lon"])), TSMC_HQ, curvature=0.15)
            folium.PolyLine(pts, color=C_BLUE, weight=1.2, opacity=0.40, dash_array="2,8",
                            tooltip=f"{r['name']} → TSMC Hsinchu (inbound supply)").add_to(m)
    return m


def build_hsinchu_map(df: pd.DataFrame, show_arcs: bool) -> folium.Map:
    """B. Micro Hsinchu — dense cluster around the Hsinchu Science Park."""
    m = base_map(HSINCHU_CENTER, 11, min_zoom=7)

    folium.Circle(TSMC_HQ, radius=3500, color=C_YELLOW, weight=1.5,
                  fill=True, fill_opacity=0.06,
                  tooltip="Hsinchu Science Park (HSP)").add_to(m)
    add_sauron_eye(m, TSMC_HQ, label="TSMC HQ · Fab 12")

    in_tw = df[(df["lat"].between(21.5, 25.6)) & (df["lon"].between(119.5, 122.5))]
    for _, r in in_tw.iterrows():
        if r["tier"] > 1:
            add_company_marker(m, r, r["lat"], r["lon"], radius_scale=0.9)

    if show_arcs:
        idx = df.set_index("company_id")
        for _, r in in_tw.iterrows():
            if not r["supplies_to_id"] or r["supplies_to_id"] not in idx.index:
                continue
            p = idx.loc[r["supplies_to_id"]]
            # only local arcs (skip lines flying off to NL / US parents)
            if not (21.5 < p["lat"] < 25.6 and 119.5 < p["lon"] < 122.5):
                continue
            pts = curved_points((r["lat"], r["lon"]), (p["lat"], p["lon"]), curvature=0.28, n=30)
            color = C_ORANGE if r["tier"] == 2 else C_CYAN
            folium.PolyLine(pts, color=color, weight=1.8 if r["tier"] == 2 else 1.1,
                            opacity=0.65 if r["tier"] == 2 else 0.40,
                            tooltip=f"{r['name']} → {r['supplies_to']}").add_to(m)
    return m


def build_phoenix_map(df: pd.DataFrame, show_arcs: bool) -> folium.Map:
    """C. Micro Phoenix — Fab 21 + announced sites + projected landing zones."""
    m = base_map(PHOENIX_CENTER, 10, min_zoom=7)

    add_sauron_eye(m, FAB21, label="TSMC FAB 21 · North Phoenix")
    folium.Circle(FAB21, radius=30000, color=C_RED, weight=1, fill=False,
                  opacity=0.35, dash_array="4,10",
                  tooltip="30 km supplier gravity radius").add_to(m)

    # Announced AZ sites (hard intel)
    announced = df[df["phoenix_lat"].notna() & (df["tier"] > 1)]
    for _, r in announced.iterrows():
        loc = (r["phoenix_lat"], r["phoenix_lon"])
        folium.Marker(
            loc, tooltip=f"{r['name']} — ANNOUNCED AZ SITE",
            popup=folium.Popup(popup_html(r), max_width=300),
            icon=folium.DivIcon(html=(
                f"<div style='font-size:18px;text-shadow:0 0 10px {C_RED};'>🏭</div>")),
        ).add_to(m)
        if show_arcs:
            AntPath(curved_points(loc, FAB21, curvature=0.30, n=30),
                    color=C_RED, weight=2.2, opacity=0.8, delay=700,
                    dash_array=[10, 20], pulse_color=C_YELLOW,
                    tooltip=f"{r['name']} ⇄ Fab 21").add_to(m)

    # Projected landing zones: top curated Taiwan candidates without a site yet
    core = df[df["in_core_tree"]] if "in_core_tree" in df.columns else df
    cands = core[(core["country"] == "Taiwan") & (core["tier"] > 1)
                 & (core["phoenix_lat"].isna()) & (core["migration_score"] >= 60)]
    cands = cands.nlargest(10, "migration_score").reset_index(drop=True)
    for i, r in cands.iterrows():
        ang = 2 * math.pi * i / max(len(cands), 1)
        rad = 0.10 + (i % 3) * 0.05
        loc = (FAB21[0] + rad * math.sin(ang), FAB21[1] + rad * 1.2 * math.cos(ang))
        folium.CircleMarker(
            loc, radius=4 + r["migration_score"] / 12,
            color=score_color(int(r["migration_score"])), weight=1.5,
            fill=True, fill_opacity=0.25, dash_array="3,6",
            tooltip=f"PROJECTED LANDING ZONE · {r['name']} ({int(r['migration_score'])}/100)",
            popup=folium.Popup(popup_html(r), max_width=300),
        ).add_to(m)
        if show_arcs:
            folium.PolyLine(curved_points(loc, FAB21, curvature=0.30, n=25),
                            color=C_ORANGE, weight=1.2, opacity=0.45, dash_array="5,9",
                            tooltip=f"{r['name']} → Fab 21 (projected)").add_to(m)

    # Existing AZ-area HQs (e.g. Amkor Tempe)
    az = df[(df["country"] == "USA") & (df["lat"].between(32.5, 34.6)) & (df["lon"].between(-113.5, -110.5))]
    for _, r in az.iterrows():
        add_company_marker(m, r, r["lat"], r["lon"])
    return m


# ──────────────────────────────────────────────────────────────────────────────
# 5b. STAKEHOLDER CONSTELLATION — who-helped-the-move relationship map
# ──────────────────────────────────────────────────────────────────────────────
# Public, professional-capacity info only. No private contact details. Named
# individuals are limited to public figures; private-company execution staff are
# left as "research via LinkedIn / press" placeholders, never fabricated.
SIDE_COLOR = {"US": "#4361ee", "Taiwan": "#ff6b35", "Media": "#9b5de5"}
TYPE_SYMBOL = {"Person": "circle", "Org": "square", "Program": "diamond",
               "Role": "diamond-open"}


@st.cache_data(show_spinner=False)
def load_stakeholders() -> pd.DataFrame:
    f = DATA_DIR / "stakeholders.csv"
    return pd.read_csv(f) if f.exists() else pd.DataFrame()


def build_constellation_figure(df_s: pd.DataFrame) -> go.Figure:
    """Radial constellation: center → category hubs → member nodes."""
    cats = list(dict.fromkeys(df_s["category"]))
    pos, hub_pos = {}, {}
    edge_x, edge_y = [], []
    center = (0.0, 0.0)
    R1 = 1.0
    for i, cat in enumerate(cats):
        th = 2 * math.pi * i / max(len(cats), 1) - math.pi / 2
        hub = (R1 * math.cos(th), R1 * math.sin(th))
        hub_pos[cat] = hub
        edge_x += [center[0], hub[0], None]
        edge_y += [center[1], hub[1], None]
        members = df_s[df_s["category"] == cat]
        k = len(members)
        rr = 0.34 + 0.03 * k
        for j, (_, m) in enumerate(members.iterrows()):
            phi = 2 * math.pi * j / max(k, 1) + th
            p = (hub[0] + rr * math.cos(phi), hub[1] + rr * math.sin(phi))
            pos[m["id"]] = p
            edge_x += [hub[0], p[0], None]
            edge_y += [hub[1], p[1], None]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", hoverinfo="skip",
                             line=dict(color="#2a3550", width=1), showlegend=False))
    # category hubs
    fig.add_trace(go.Scatter(
        x=[hub_pos[c][0] for c in cats], y=[hub_pos[c][1] for c in cats],
        mode="markers+text", text=cats, textposition="middle center",
        textfont=dict(size=9, color="#e8e9f3"),
        marker=dict(size=46, color="#0b101d", line=dict(color="#ff9f1c", width=1.5)),
        hoverinfo="skip", showlegend=False))
    # center
    fig.add_trace(go.Scatter(
        x=[0], y=[0], mode="markers+text", text=["TSMC AZ<br>MOVE"],
        textposition="middle center", textfont=dict(size=10, color="#05070d"),
        marker=dict(size=58, color="#ff3b3b", line=dict(color="#ffd166", width=2)),
        hoverinfo="skip", showlegend=False))
    # member nodes, one trace per side (for the legend)
    for side, color in SIDE_COLOR.items():
        sub = df_s[df_s["side"] == side]
        if not len(sub):
            continue
        fig.add_trace(go.Scatter(
            x=[pos[i][0] for i in sub["id"]], y=[pos[i][1] for i in sub["id"]],
            mode="markers+text", name=side, text=sub["name"],
            textposition="top center", textfont=dict(size=8, color="#8d99ae"),
            marker=dict(size=15, color=color,
                        symbol=[TYPE_SYMBOL.get(t, "circle") for t in sub["type"]],
                        line=dict(color="#0b101d", width=1)),
            customdata=np.stack([sub["role"], sub["organization"], sub["outreach"],
                                 sub["status"], sub["notes"]], axis=-1),
            hovertemplate=("<b>%{text}</b><br>%{customdata[0]}<br>"
                           "Org: %{customdata[1]}<br>Outreach: %{customdata[2]}<br>"
                           "Status: %{customdata[3]}<br><i>%{customdata[4]}</i><extra></extra>"),
        ))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=680, margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(visible=False, range=[-1.7, 1.7]),
        yaxis=dict(visible=False, range=[-1.7, 1.7], scaleanchor="x"),
        legend=dict(orientation="h", y=1.04, font=dict(color="#8d99ae")),
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# 6. NETWORK TREE FIGURE (Plotly, hierarchical 3-tier layout)
# ──────────────────────────────────────────────────────────────────────────────
def build_tree_figure(df: pd.DataFrame) -> go.Figure:
    # The "deep tree" is the curated TSMC backbone; the ETO/TSIA global supply
    # base lives on the map + database, not in this directed 3-tier view.
    if "in_core_tree" in df.columns:
        df = df[df["in_core_tree"]]
    tsmc_id = "T1-00"
    t2 = df[df["tier"] == 2].sort_values("category").reset_index(drop=True)
    t3 = df[df["tier"] == 3]

    pos = {tsmc_id: (50.0, 2.0)}
    xs = np.linspace(2, 98, max(len(t2), 2))
    for x, (_, r) in zip(xs, t2.iterrows()):
        pos[r["company_id"]] = (float(x), 1.0)

    half = (96 / max(len(t2) - 1, 1)) / 2 * 0.92
    for pid, grp in t3.groupby("supplies_to_id"):
        px = pos.get(pid, (50.0, 1.0))[0]
        k = len(grp)
        offs = np.linspace(-half, half, k) if k > 1 else [0.0]
        for j, (off, (_, r)) in enumerate(zip(offs, grp.iterrows())):
            pos[r["company_id"]] = (px + float(off), 0.0 + (j % 3) * 0.07)

    edge_x, edge_y = [], []
    for _, r in df.iterrows():
        if r["supplies_to_id"] and r["supplies_to_id"] in pos and r["company_id"] in pos:
            x0, y0 = pos[r["company_id"]]
            x1, y1 = pos[r["supplies_to_id"]]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                             line=dict(color="#2a3550", width=1),
                             hoverinfo="skip", showlegend=False))

    for tier, size, show_text in [(1, 34, True), (2, 18, True), (3, 10, False)]:
        sub = df[df["tier"] == tier]
        fig.add_trace(go.Scatter(
            x=[pos[c][0] for c in sub["company_id"]],
            y=[pos[c][1] for c in sub["company_id"]],
            mode="markers+text" if show_text else "markers",
            text=sub["name"] if show_text else None,
            textposition="top center",
            textfont=dict(size=9, color="#8d99ae"),
            marker=dict(
                size=size,
                color=sub["migration_score"],
                colorscale=[[0, C_GREY], [0.5, C_YELLOW], [0.75, C_ORANGE], [1, C_RED]],
                cmin=0, cmax=100,
                line=dict(width=1, color="#0b101d"),
            ),
            name=f"Tier {tier}",
            customdata=np.stack([sub["name"], sub["category"], sub["migration_score"],
                                 sub["supplies_to"]], axis=-1),
            hovertemplate=("<b>%{customdata[0]}</b><br>%{customdata[1]}"
                           "<br>Migration score: %{customdata[2]}/100"
                           "<br>Supplies → %{customdata[3]}<extra></extra>"),
        ))

    for y, label in [(2.0, "TIER 1 · FOUNDRY"), (1.0, "TIER 2 · DIRECT SUPPLIERS"),
                     (0.0, "TIER 3 · SUB-SUPPLIERS")]:
        fig.add_annotation(x=-1, y=y, text=label, showarrow=False, xanchor="right",
                           font=dict(family="Courier New", size=10, color="#5c677d"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False, range=[-14, 102]),
        yaxis=dict(visible=False, range=[-0.5, 2.5]),
        height=640, margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", y=1.05, font=dict(color="#8d99ae")),
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# 7. UI — HEADER, SIDEBAR, KPIs, TABS, DATAFRAME, EXPORT
# ──────────────────────────────────────────────────────────────────────────────
df_raw = build_unified_dataset()
df, betweenness = build_graph_and_scores(df_raw)
G = build_graph(df_raw)
df = apply_geo_overrides(df, st.session_state.get("geo_overrides", {}))

st.markdown(
    "<div class='sauron-title'>👁️ PROJECT SAURON</div>"
    "<div class='sauron-sub'>SEMICONDUCTOR SUPPLY CHAIN COMMAND CENTER · "
    "TAIWAN → PHOENIX MIGRATION INTELLIGENCE</div><br>",
    unsafe_allow_html=True,
)

st.warning(
    "⚠️ **MIXED DATA — read before trusting a number.** Company names are real. "
    "**ETO market-share figures are real** (Georgetown CSET / ETO Chip Explorer, cited). "
    "Everything else — revenues, employee counts, capex/labor intensity, geocoordinates, "
    "migration scores, announced-site locations — is **illustrative placeholder**. "
    "ETO/TSIA companies are placed at *country-approx* coordinates (not precise HQs). "
    "Wire the OSINT stubs (ImportYeti / OpenCorporates / Google Places) to replace the rest.",
    icon=None,
)

# ── Sidebar controls ──
with st.sidebar:
    st.markdown("### 🎛️ COMMAND CONSOLE")
    view = st.radio(
        "Geospatial view",
        ["🌐 Global Macro (Asia ⇄ US)", "🏯 Micro: Hsinchu Cluster", "🌵 Micro: Phoenix / Fab 21"],
    )
    show_arcs = st.toggle("Show logistics arcs", value=True)
    st.divider()
    st.markdown("### 🔍 TARGET FILTERS")
    ai_only = st.toggle(
        "🤖 AI supply chain only",
        value=False,
        help="Show only the AI-accelerator critical path: CoWoS advanced packaging, "
             "HBM memory, EUV / advanced logic, advanced substrates, leading-edge "
             "wafers & photoresist, and their Tier-3 inputs.",
    )
    sources = st.multiselect(
        "Data source", ["Curated", "ETO", "TSIA"], default=[],
        help="Curated = hand-built TSMC tree · ETO = Georgetown CSET Chip Explorer "
             "(real market shares) · TSIA = Taiwan Semiconductor Industry Assoc. members.",
    )
    show_affiliates = st.toggle(
        "Show non-semiconductor members",
        value=False,
        help="TSIA's roster includes 25 non-supply-chain affiliates — banks, "
             "accounting/law firms, logistics, trade bodies and industry "
             "associations (incl. SEMI). Hidden by default.",
    )
    tiers = st.multiselect("Tier", [1, 2, 3], default=[1, 2, 3])
    cats = st.multiselect("Category", sorted(df["category"].unique()), default=[])
    countries = st.multiselect("Country", sorted(df["country"].unique()), default=[])
    min_score = st.slider("Min migration score", 0, 100, 0, 5)
    search = st.text_input("Search company / product")

# ── Apply filters (TSMC anchor always retained for map context) ──
mask = df["tier"].isin(tiers) & (df["migration_score"] >= min_score)
if not show_affiliates:
    mask &= ~df["affiliate"]
if ai_only:
    mask &= df["ai_supply_chain"]
if sources:
    mask &= df["data_source"].apply(lambda s: any(src in s for src in sources))
if cats:
    mask &= df["category"].isin(cats)
if countries:
    mask &= df["country"].isin(countries)
if search:
    s = search.lower()
    mask &= (df["name"].str.lower().str.contains(s)
             | df["product"].str.lower().str.contains(s))
df_f = df[mask]
df_map = pd.concat([df_f, df[df["tier"] == 1]]).drop_duplicates("company_id")

# ── KPI strip ──
scope = "🤖 AI supply chain" if ai_only else "full supply chain"
n_eto = int(df["data_source"].str.contains("ETO").sum())
n_tsia = int(df["data_source"].str.contains("TSIA").sum())
n_share = int(df["market_share_pct"].notna().sum())
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Companies tracked", f"{len(df_f)} / {len(df)}", help=f"Matching filter ({scope})")
k2.metric("From ETO / TSIA", f"{n_eto} / {n_tsia}",
          help="Real orgs ingested from Georgetown CSET ETO Chip Explorer and the "
               "TSIA member directory (deduped against the curated set)")
k3.metric("Real ETO market shares", n_share,
          help="Companies carrying a real, cited ETO market-share figure")
k4.metric("AI supply-chain nodes", int(df["ai_supply_chain"].sum()))
k5.metric("Prime targets (≥70, TW)",
          int(((df["migration_score"] >= 70) & (df["country"] == "Taiwan") & (df["tier"] > 1)).sum()))
k6.metric("Announced AZ sites", int((df["phoenix_lat"].notna() & (df["tier"] > 1)).sum()))

st.divider()

# ── Tabs ──
tab_map, tab_tree, tab_engine, tab_people = st.tabs(
    ["🗺️ GEOSPATIAL INTEL", "🕸️ DEEP TREE NETWORK", "🎯 SCORING ENGINE",
     "🌐 STAKEHOLDER CONSTELLATION"]
)

with tab_map:
    if view.startswith("🌐"):
        st.caption("GLOBAL MACRO · Pacific-centered. Red animated arcs = announced AZ migrations · "
                   "orange dashed = projected (score ≥ 60) · blue = inbound global supply to Hsinchu.")
        m = build_global_map(df_map, show_arcs)
    elif view.startswith("🏯"):
        st.caption("MICRO HSINCHU · Yellow ring = Hsinchu Science Park. Cyan arcs = Tier-3 → Tier-2 "
                   "supply, orange arcs = Tier-2 → TSMC.")
        m = build_hsinchu_map(df_map, show_arcs)
    else:
        st.caption("MICRO PHOENIX · The Eye sits on Fab 21. Factory icons = announced sites; dashed "
                   "circles = projected landing zones for top Taiwanese candidates.")
        m = build_phoenix_map(df_map, show_arcs)
    st_folium(m, height=580, use_container_width=True,
              returned_objects=[], key=f"map_{view[:4]}")

with tab_tree:
    st.caption("3-tier directed supply graph (NetworkX → Plotly). Node color & size = migration score.")
    st.plotly_chart(build_tree_figure(df_f if len(df_f) > 1 else df), width="stretch")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Graph nodes", G.number_of_nodes())
    g2.metric("Supply edges", G.number_of_edges())
    g3.metric("Graph density", f"{nx.density(G):.3f}")
    top_bt = max(((k, v) for k, v in betweenness.items() if k != "T1-00"),
                 key=lambda kv: kv[1], default=(None, 0))
    top_name = df.loc[df["company_id"] == top_bt[0], "name"].iloc[0] if top_bt[0] else "—"
    g4.metric("Top chokepoint (betweenness)", top_name)

with tab_engine:
    c_left, c_right = st.columns([1, 1.4])
    with c_left:
        st.markdown("#### ⚙️ US MIGRATION LIKELIHOOD — weight stack")
        st.markdown(
            """
| Factor | Weight | Rationale |
|---|---|---|
| Base | +20 | Every TSMC supplier feels Fab 21 gravity |
| **CoWoS advanced packaging** | **+25** | Arizona's biggest ecosystem gap |
| **EUV handling / infra** | **+22** | Pods, optics, carriers must be local |
| **Ultra-pure chemicals** | **+20** | UHP HF/IPA can't cross the Pacific economically |
| Capital vs labor intensity | ±15 | Capex migrates; labor arbitrage doesn't |
| TSMC revenue dependence | +0–10 | Anchor-client pull |
| Existing US presence | +8 | Beachhead already established |
| Network centrality | +0–10 | Chokepoints get dragged along |
| Revenue scale | +0–5 | Ability to fund a US plant |
            """
        )
        st.caption("Clipped to 1–100. ≥70 PRIME · 55–69 STRONG · 40–54 WATCHLIST · <40 DOMESTIC.")
    with c_right:
        top = df[df["tier"] > 1].nlargest(15, "migration_score").iloc[::-1]
        fig = go.Figure(go.Bar(
            x=top["migration_score"], y=top["name"], orientation="h",
            marker=dict(color=[score_color(s) for s in top["migration_score"]]),
            text=top["migration_score"], textposition="outside",
            hovertemplate="<b>%{y}</b> · %{x}/100<extra></extra>",
        ))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", height=520,
                          margin=dict(l=10, r=40, t=30, b=10),
                          xaxis=dict(range=[0, 108], title="Migration score"),
                          title="TOP 15 MIGRATION TARGETS")
        st.plotly_chart(fig, width="stretch")

with tab_people:
    df_s = load_stakeholders()
    if not len(df_s):
        st.info("No stakeholder data found (data/stakeholders.csv).")
    else:
        st.caption("WHO MADE THE MOVE POSSIBLE · a relationship map of the people & "
                   "organizations behind TSMC's Taiwan→Arizona shift — for outreach, "
                   "learning, and finding your own way in.")
        st.warning(
            "⚠️ **Public, professional info only — verify before outreach.** Named "
            "individuals are limited to public figures in public roles; private-company "
            "execution staff are shown as **research-via-LinkedIn placeholders, not "
            "invented names**. No private contact details are stored. Roles marked "
            "*verify* may be out of date. Outreach only through the public channels shown.",
            icon=None,
        )
        sides = st.multiselect("Side", ["US", "Taiwan", "Media"],
                               default=["US", "Taiwan", "Media"], key="con_side")
        cats_all = list(dict.fromkeys(df_s["category"]))
        cats_sel = st.multiselect("Category", cats_all, default=cats_all, key="con_cat")
        d = df_s[df_s["side"].isin(sides) & df_s["category"].isin(cats_sel)]

        p1, p2, p3, p4 = st.columns(4)
        p1.metric("People & orgs mapped", len(df_s))
        p2.metric("Public figures / orgs", int((df_s["status"] == "public-role").sum()))
        p3.metric("Need verification", int(df_s["status"].isin(["verify", "research-needed"]).sum()))
        p4.metric("Categories", df_s["category"].nunique())

        if len(d) > 1:
            st.plotly_chart(build_constellation_figure(d), width="stretch")
        else:
            st.info("Select at least one side/category to render the constellation.")

        st.markdown("#### 📇 Contact ledger")
        st.dataframe(
            d[["name", "type", "category", "side", "organization", "role", "outreach", "status", "notes"]],
            width="stretch", height=320, hide_index=True,
            column_config={"outreach": st.column_config.TextColumn("Outreach (public)"),
                           "status": st.column_config.TextColumn("Status")},
        )
        st.download_button(
            "📤 Export stakeholders (CSV)",
            data=d.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"sauron_stakeholders_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

        with st.expander("🧭 How to actually get involved — concrete, legitimate entry points"):
            st.markdown(
                """
You said you want in but aren't sure how. The fastest *legitimate* on-ramps, roughly in order:

- **SelectUSA (selectusa.gov)** — the U.S. government's own FDI program. It exists to connect
  people to US locations & incentives. The annual **SelectUSA Investment Summit** is the single
  densest room of the people on this map.
- **Arizona Commerce Authority (azcommerce.com)** & **GPEC (gpec.org)** — state/regional teams
  whose literal job is helping the TSMC ecosystem land in Phoenix. They take meetings.
- **AIT Commercial Section (ait.org.tw)** — the US commercial liaison *in Taiwan*; the bridge
  for Taiwanese suppliers heading to the US.
- **SEMI (semi.org)** — the industry association (already a node in your TSIA data). Join, go to
  SEMICON West / SEMICON Taiwan, work the supplier-migration track.
- **Learn first, fast** — the Media & Analysts cluster (Asianometry, TechInTaiwan, DigiTimes,
  CommonWealth) is your low-stakes way to build context before you spend relationship capital.
  A few well-prepared "grab a coffee, I'm trying to understand X" notes go a long way.

**Where *you* could plug in:** supplier site-selection & relocation advisory, cleanroom/facility
build-out coordination, TW↔AZ talent & logistics bridging, or simply being the person who maps
this ecosystem (which is what this dashboard already makes you). Pick one node, learn it deeply,
and become useful to it.
                """
            )

st.divider()

# ── Dataset + Google Sheets export ──
hdr_l, hdr_r = st.columns([3, 1])
with hdr_l:
    st.markdown("### 📡 TARGET DATABASE")
    n_star = int((~df_f["name_verified"]).sum())
    st.caption(f"{len(df_f)} of {len(df)} companies match current filters · "
               f"{n_star} name(s) marked * (unverified). Click any column header to sort.")
with hdr_r:
    with st.popover("ℹ️ About the * names", use_container_width=True):
        st.markdown(
            "**Names ending in `*` are unverified.** They are best-effort English "
            "renderings auto-derived from the company's own web **domain** (captured "
            "during the TSIA member-directory scrape) — not an official English name.\n\n"
            "The **authoritative** name is always the Traditional-Chinese original in the "
            "`local_name` column, and the `website` column lets you confirm identity "
            "directly.\n\n"
            "Verified names (no `*`) are confirmed against the company's website domain "
            "or well-known identity. To see only confident records, sort or filter on the "
            "`name_verified` column."
        )

EXPORT_COLS = ["company_id", "name", "name_verified", "local_name", "website",
               "data_source", "tier", "category", "role", "product", "city", "country",
               "geo_precision", "lat", "lon", "supplies_to", "ai_supply_chain",
               "cowos", "euv", "upc", "market_share_pct", "capital_intensity",
               "labor_intensity", "revenue_musd", "employees", "tsmc_dependence_pct",
               "us_presence", "migration_score", "status"]
df_view = df_f[EXPORT_COLS].sort_values("migration_score", ascending=False)

st.dataframe(
    df_view,
    width="stretch",
    height=420,
    hide_index=True,
    column_config={
        "migration_score": st.column_config.ProgressColumn(
            "US Migration Likelihood", min_value=0, max_value=100, format="%d"),
        "ai_supply_chain": st.column_config.CheckboxColumn("AI chain"),
        "name_verified": st.column_config.CheckboxColumn(
            "Name ✓", help="Unchecked = English name is an unverified * rendering "
                           "(see the local_name / website columns)."),
        "data_source": st.column_config.TextColumn("Source"),
        "local_name": st.column_config.TextColumn("Local name (authoritative)"),
        "website": st.column_config.LinkColumn("Website"),
        "market_share_pct": st.column_config.NumberColumn("ETO mkt share", format="%.1f%%"),
        "revenue_musd": st.column_config.NumberColumn("Revenue (M USD)", format="$%d M"),
        "tsmc_dependence_pct": st.column_config.NumberColumn("TSMC dep. %", format="%d%%"),
    },
)

# Flat schema + UTF-8 (with BOM for safe non-ASCII handling) → drag straight
# into Google Sheets via File → Import → Upload.
csv_bytes = df_view.to_csv(index=False).encode("utf-8-sig")
e1, e2 = st.columns([1, 3])
with e1:
    st.download_button(
        "📤 Export to Google Sheets (CSV)",
        data=csv_bytes,
        file_name=f"sauron_supply_chain_{date.today().isoformat()}.csv",
        mime="text/csv",
        type="primary",
        width="stretch",
    )
with e2:
    st.caption("UTF-8 · flat single-header schema · no merged cells or nested fields. "
               "In Google Sheets: **File → Import → Upload → Replace spreadsheet**.")

# ── Data provenance & attribution ──
with st.expander("📚 DATA SOURCES & ATTRIBUTION — what's real vs. illustrative"):
    st.markdown(
        """
- **ETO Chip Explorer** — *Emerging Technology Observatory, Georgetown CSET.*
  374 real organizations + **real, cited market-share relationships** (e.g. ASML
  = 100% of EUV tools). Derived from CSET, *The Semiconductor Supply Chain:
  Assessing National Competitiveness* (2021), augmented by ETO (2022/2024).
  Source repo: `github.com/georgetown-cset/eto-chip-explorer`. Credit ETO/CSET
  when redistributing.
- **TSIA** — Taiwan Semiconductor Industry Association member directory
  (`tsia.org.tw`). **Full directory: all 220 members** across 11 pages, scraped
  via Playwright (`scripts/scrape_tsia.py`) by driving the site's ASP.NET
  postback pagination. English names verified against each member's own website
  domain where possible; **unverified renderings are marked with `*`** and the
  authoritative Traditional-Chinese name is kept in `local_name`.
- **SEMI member directory** — **not ingested.** `semi.org` returns HTTP 403
  (bot protection) and gates the directory behind member login.
- **De-duplication** — external rows are matched to curated companies by a
  normalized-name key; a match *enriches* the curated row (adds market share +
  source tag) rather than creating a duplicate. ETO/TSIA companies are placed at
  **country-approx** coordinates (hollow rings on the map), upgradeable to precise
  HQs via the Google Places stub below.
- **Still illustrative:** revenues, employee counts, capex/labor intensity,
  migration scores, and all announced-site coordinates.
        """
    )

# ── OSINT harvesting pipeline — LIVE API clients (key-gated) ──
_status = osint.api_status()
_badge = lambda ok: "🟢 LIVE" if ok else "⚪ mock (no key)"
with st.expander("🔌 OSINT HARVESTING PIPELINE — live Google Places · ImportYeti · OpenCorporates"):
    st.caption(
        f"Status — 📍 Google Places: **{_badge(_status['google_places'])}**  ·  "
        f"🚢 ImportYeti/BoL: **{_badge(_status['importyeti'])}**  ·  "
        f"🏛️ OpenCorporates: **{_badge(_status['opencorporates'])}**. "
        "Add keys in `.streamlit/secrets.toml` (see `secrets.toml.example`) to go live; "
        "without a key each tool returns clearly-labelled mock data."
    )
    o1, o2, o3 = st.tabs(["📍 Geocode (Places)", "🚢 ImportYeti / BoL", "🏛️ OpenCorporates"])

    # ---- Google Places: geocode a country-approx company onto precise coords ----
    with o1:
        st.markdown("**Resolve a country-approx company to a precise location** — "
                    "the result is written back onto the map for this session.")
        approx = df[df["geo_precision"].isin(["country-approx", "ungeocoded"])]
        if len(approx):
            pick = st.selectbox("Company to geocode", approx["name"].tolist(), key="geo_pick")
            row = approx[approx["name"] == pick].iloc[0]
            if st.button("📍 Geocode via Google Places", key="geo_run"):
                res = geocode_cached(str(row["name"]), str(row["country"]))
                if res.get("lat") is not None and res.get("live"):
                    st.session_state.setdefault("geo_overrides", {})[row["company_id"]] = (
                        res["lat"], res["lon"], res.get("formatted_address", ""))
                    st.success(f"Pinned **{pick}** → {res.get('formatted_address','')} "
                               f"({res['lat']:.4f}, {res['lon']:.4f}). Map updated below ↑")
                    st.rerun()
                elif not res.get("configured"):
                    st.warning(res.get("hint", "No API key configured."))
                    st.json(res)
                else:
                    st.error(f"Geocode failed: {res.get('error', res)}")
        else:
            st.info("All companies already have precise coordinates.")
        if st.session_state.get("geo_overrides"):
            st.caption(f"✅ {len(st.session_state['geo_overrides'])} companies geocoded this session.")

    # ---- ImportYeti: who is shipping ocean freight to Arizona ----
    with o2:
        st.markdown("**Bill-of-Lading lookup** — is this supplier already shipping to Arizona?")
        iy_name = st.text_input("Supplier name", value="Gudeng Precision", key="iy_name")
        iy_state = st.text_input("Consignee state", value="AZ", key="iy_state")
        if st.button("🚢 Query customs data", key="iy_run"):
            st.json(osint.importyeti_shipments(iy_name, iy_state))

    # ---- OpenCorporates: new AZ/DE subsidiary filings ----
    with o3:
        st.markdown("**Registry search** — detect a new `us_az` / `us_de` subsidiary "
                    "(a hard migration signal).")
        oc_name = st.text_input("Company name", value="Sunlit Chemical", key="oc_name")
        oc_juris = st.text_input("Jurisdiction filter (optional, e.g. us_az)", value="", key="oc_juris")
        if st.button("🏛️ Search registries", key="oc_run"):
            res = osint.opencorporates_search(oc_name, oc_juris)
            if res.get("us_subsidiary_signal"):
                st.error("🟥 US (AZ/DE) subsidiary filing detected — migration signal.")
            st.json(res)

st.markdown(
    "<br><div style='color:#3a4358;font-family:monospace;font-size:11px'>"
    "PROJECT SAURON v0.3 · curated + ETO (real shares) + TSIA · deduped · "
    "live OSINT: Google Places · ImportYeti · OpenCorporates (key-gated) · "
    "one dashboard to find them, one dashboard to bring them all (to Phoenix)</div>",
    unsafe_allow_html=True,
)
