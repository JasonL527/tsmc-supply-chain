"""
Turn the raw TSIA scrape into the app-ready members.csv.

For each scraped member we attach an English name + segment. Names verified
against the company's own website domain (captured during the scrape) or
well-known identity are marked name_verified=True. Everything else falls back
to a domain-derived brand, marked name_verified=False → the app renders these
with an asterisk and a disclaimer.

Run after scrape_tsia.py:
    ./.venv/bin/python scripts/build_tsia_members.py
"""
import csv
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "data" / "tsia"
SCRAPED = HERE / "members_scraped.csv"
OUT = HERE / "members.csv"

# member_id -> (english_name, segment).  Verified from website domain / identity.
# Duplicate-of-curated names are spelled to normalize to the same key (so they
# de-dupe and enrich rather than double up).
VERIFIED = {
    "1": ("Powerchip Investment Holding", "Foundry / DRAM"),
    "5": ("ITRI (Industrial Technology Research Institute)", "R&D Institute"),
    "9": ("Vanguard Intl Semiconductor (VIS)", "Foundry"),
    "10": ("Taiwan Mask Corp", "Photomask"),
    "13": ("TSMC", "Foundry"),
    "14": ("Applied Materials (Taiwan)", "Equipment"),
    "24": ("ISSI (Integrated Silicon Solution)", "Memory / IC"),
    "27": ("Nanya Technology", "DRAM"),
    "29": ("Lam Research (Taiwan)", "Equipment"),
    "31": ("KLA (Taiwan)", "Metrology / Inspection"),
    "32": ("Sunplus Technology", "Fabless IC Design"),
    "40": ("Winbond Electronics", "Memory"),
    "41": ("OSE (Orient Semiconductor Electronics)", "OSAT / Test"),
    "44": ("Lingsen Precision Industries", "OSAT / Test"),
    "48": ("Realtek Semiconductor", "Fabless IC Design"),
    "49": ("Etron Technology", "Memory / Fabless"),
    "50": ("Hermes-Epitek", "Equipment Distribution"),
    "51": ("Episil Technologies", "Specialty Foundry"),
    "55": ("UMC", "Foundry"),
    "62": ("Siliconware Precision (SPIL)", "OSAT / Test"),
    "64": ("Walton Advanced Engineering", "OSAT / Test"),
    "81": ("Global Unichip (GUC)", "ASIC Design"),
    "83": ("ASE Group", "OSAT / Test"),
    "101": ("ChipMOS Technologies", "OSAT / Test"),
    "102": ("ProMOS Technologies", "DRAM"),
    "104": ("BASF (Taiwan)", "Materials / Chemicals"),
    "108": ("KYEC (King Yuan Electronics)", "OSAT / Test"),
    "119": ("ESMT (Elite Semiconductor)", "Memory / IC"),
    "126": ("Megawin Technology", "Fabless IC Design"),
    "127": ("Davicom Semiconductor", "Fabless IC Design"),
    "146": ("Marketech International (MIC)", "Facility / Equipment"),
    "151": ("Spirox", "Test / Equipment"),
    "159": ("MediaTek", "Fabless IC Design"),
    "163": ("Himax Technologies", "Fabless IC Design"),
    "165": ("Richtek Technology", "Fabless IC Design"),
    "167": ("eMemory Technology", "IP / Fabless"),
    "174": ("iST (Integrated Service Technology)", "Test / Reliability"),
    "175": ("Powertech Technology (PTI)", "OSAT / Test"),
    "183": ("Alchip Technologies", "ASIC Design"),
    "184": ("Powerchip Semiconductor Mfg (PSMC)", "Foundry"),
    "185": ("Phison Electronics", "Fabless IC Design"),
    "193": ("WIN Semiconductors", "GaAs Foundry"),
    "197": ("GlobalWafers", "Silicon Wafers"),
    "198": ("HIWIN Technologies", "Precision / Automation"),
    "205": ("Ardentec", "OSAT / Test"),
    "206": ("Sigurd Microelectronics", "OSAT / Test"),
    "207": ("WPG Holdings", "Distribution"),
    "212": ("Episil-Precision (Epitech)", "Epitaxial Wafers"),
    "214": ("GPM (Gallant Precision Machining)", "Equipment"),
    "221": ("M31 Technology", "IP"),
    "222": ("AP Memory Technology", "Fabless IC Design"),
    "226": ("C SUN Mfg", "Equipment"),
    "227": ("Youngtek Electronics", "OSAT / Test"),
    "232": ("Andes Technology", "CPU IP"),
    "233": ("Egis Technology", "Fabless IC Design"),
    "234": ("Gudeng Precision", "EUV Infrastructure"),
    "236": ("RichWave Technology", "Fabless IC Design"),
    "237": ("Weltrend Semiconductor", "Fabless IC Design"),
    "249": ("Fitipower Integrated Technology", "Fabless IC Design"),
    "252": ("Sunplus Innovation Technology", "Fabless IC Design"),
    "256": ("CHPT (Chunghwa Precision Test Tech)", "Test / Probe Cards"),
    "257": ("Novatek Microelectronics", "Fabless IC Design"),
    "270": ("Eris Technology", "Discrete Semiconductors"),
    "272": ("Phoenix Silicon International (PSI)", "Wafer Reclaim"),
    "277": ("Silicon Motion Technology", "Fabless IC Design"),
    "280": ("Topco Scientific", "Materials Distribution"),
    "284": ("Kinsus Interconnect", "IC Substrates"),
    "291": ("Mirle Automation", "Equipment / Automation"),
    "293": ("Wah Lee Industrial", "Materials Distribution"),
    "299": ("Grand Process Technology (GPTC)", "Equipment"),
    "301": ("Scientech", "Equipment / Wet Process"),
    "302": ("Raydium Semiconductor", "Fabless IC Design"),
    "305": ("Kinik Company", "CMP Pad Conditioners"),
    "311": ("Utechzone", "Machine Vision / Inspection"),
    "312": ("Zhen Ding Technology (ZDT)", "PCB / Substrates"),
    "315": ("Foxsemicon (FITI)", "Fab Equipment Modules"),
    "319": ("Chroma ATE", "Test / Measurement"),
    "323": ("Fusheng", "Compressors"),
    "327": ("Manz (Taiwan)", "Equipment"),
    "331": ("Air Liquide Far Eastern", "Industrial Gases"),
    "1008": ("Synopsys (Taiwan)", "IP / EDA"),
    "1027": ("Cadence Design Systems (Taiwan)", "IP / EDA"),
    "1040": ("SEMI (Taiwan)", "Industry Association"),
    "1041": ("GlobalFoundries", "Foundry"),
    "1047": ("Senju Metal (Taiwan)", "Materials / Solder"),
    "1051": ("INFICON", "Vacuum Instruments"),
    "1054": ("EAG Laboratories", "Materials Analysis"),
    "1084": ("Atotech (MKS)", "Plating Chemicals"),
    "1096": ("ASM (Taiwan)", "Equipment"),
    "1116": ("Entegris (Taiwan)", "Materials"),
    "1120": ("Finnegan (law firm)", "Service / Affiliate"),
    "1133": ("Tokyo Electron (Taiwan)", "Equipment"),
    "1134": ("KPMG (Taiwan)", "Service / Affiliate"),
    "1141": ("III (Institute for Information Industry)", "R&D / Affiliate"),
    "1146": ("San Fu / Air Products (Taiwan)", "Industrial Gases"),
    "1153": ("Linde LienHwa", "Industrial Gases"),
    "1156": ("Taiwan Cloud IoT Association", "Industry Association"),
    "1159": ("PwC (Taiwan)", "Service / Affiliate"),
    "1161": ("Monte Jade Science & Technology Assoc.", "Industry Association"),
    "1162": ("Deloitte (Taiwan)", "Service / Affiliate"),
    "1163": ("DHL Supply Chain (Taiwan)", "Logistics / Affiliate"),
    "1164": ("Taiwan AIoT Association", "Industry Association"),
    "1168": ("TEEIA (Equipment Industry Assoc.)", "Industry Association"),
    "1169": ("EY (Taiwan)", "Service / Affiliate"),
    "1172": ("Taiwan Fertilizer", "Materials / Chemicals"),
    "1174": ("TPCA (Taiwan PCB Association)", "Industry Association"),
    "1175": ("Mizuho Bank (Taipei)", "Finance / Affiliate"),
    "1176": ("TAITRA", "Trade / Affiliate"),
    "1178": ("Chunghwa Telecom", "Telecom / Affiliate"),
    "1180": ("NielsenIQ / GfK", "Service / Affiliate"),
    "1181": ("TEJ (Taiwan Economic Journal)", "Data / Affiliate"),
    "1183": ("Taiwan Passive Component Association", "Industry Association"),
    "1187": ("Pitotech", "Equipment / Distribution"),
    "1191": ("TSOMDA (Materials & Devices Assoc.)", "Industry Association"),
    "2003": ("ASML (Taiwan)", "Lithography"),
    "2005": ("Sumitomo Bakelite (Taiwan)", "Materials"),
    "2009": ("Arm (Taiwan)", "IP"),
    "2012": ("Omron (Taiwan)", "Automation"),
    "2014": ("SK Materials (Taiwan)", "Materials / Specialty Gases"),
    "2017": ("Ushio (Taiwan)", "Light Sources"),
    "2019": ("Micron (Taiwan)", "Memory"),
    "2020": ("Amkor (Taiwan)", "OSAT / Test"),
    "2025": ("Otsuka Techno (Taiwan)", "Materials / Chemicals"),
    "2026": ("Merck Advanced Materials", "Materials"),
    "2030": ("Onto Innovation (Taiwan)", "Metrology"),
    "2031": ("SCREEN Semiconductor (Taiwan)", "Equipment"),
    "2035": ("Teradyne (Taiwan)", "Test"),
    "2039": ("Hamamatsu Photonics (Taiwan)", "Photonics"),
    "2041": ("Hanbell Vacuum", "Vacuum Pumps"),
    "2042": ("Shinwa Controls (Taiwan)", "Temp Control / Chillers"),
    "2043": ("IMS Nanofabrication", "Mask Writers"),
    "2044": ("MaxLinear (Taiwan)", "Fabless IC Design"),
    "2045": ("Ebara Precision (Taiwan)", "Equipment"),
    "2047": ("Kanken Techno (Taiwan)", "Abatement"),
    "2050": ("Siemens EDA (Mentor)", "IP / EDA"),
    "2051": ("Siltronic (Taiwan)", "Silicon Wafers"),
    "2052": ("Primarius Technologies", "IP / EDA"),
    "2056": ("DNP (Dai Nippon Printing, Taiwan)", "Photomask"),
    "2058": ("Carl Zeiss (Taiwan)", "Optics"),
    "2059": ("Ecolab (Taiwan)", "Materials / Chemicals"),
    "2061": ("ULVAC (Taiwan)", "Equipment"),
    "2063": ("PDF Solutions (Taiwan)", "Yield / EDA"),
    "2064": ("JSR (Taiwan)", "Photoresist Materials"),
    "2065": ("Cyient Semiconductor", "Design Services"),
}

# Segment guesses for unverified rows, keyed by hints in the domain (best effort).
def fallback_segment(domain: str) -> str:
    d = domain.lower()
    if any(k in d for k in ("semi", "ic", "chip", "micro", "tek", "tech")):
        return "Semiconductor (unclassified)"
    if any(k in d for k in ("chem", "material", "gas")):
        return "Materials / Chemicals"
    return "Unclassified"


def brand_from_domain(url: str) -> str:
    d = str(url).strip().replace("%20", "").lstrip()
    d = re.sub(r"^https?://", "", d).replace("www.", "")
    d = d.split("/")[0].split("?")[0]
    parts = [p for p in d.split(".") if p]
    if not parts:
        return ""
    generic = {"w3", "taiwan", "tw", "epi", "www2", "eda", "sw"}
    label = parts[0]
    if label in generic and len(parts) > 1:
        label = parts[1]
    return re.sub(r"[^a-zA-Z0-9]", " ", label).title().strip()


def main():
    rows_out = []
    with SCRAPED.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            mid = r["member_id"].strip()
            key = mid.lstrip("0") or "0"      # scraped ids are zero-padded ("0013")
            local = r["local_name"].strip()
            site = r.get("website", "")
            if key in VERIFIED:
                name, segment = VERIFIED[key]
                verified = "True"
            else:
                brand = brand_from_domain(site) or local
                name = f"{brand}*"
                segment = fallback_segment(brand_from_domain(site))
                verified = "False"
            rows_out.append([local, name, verified, "TWN", segment, site, mid])

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["local_name", "name", "name_verified", "country", "segment", "website", "member_id"])
        w.writerows(rows_out)
    v = sum(1 for r in rows_out if r[2] == "True")
    print(f"Wrote {len(rows_out)} members → {OUT}  ({v} verified, {len(rows_out) - v} asterisked)")


if __name__ == "__main__":
    main()
