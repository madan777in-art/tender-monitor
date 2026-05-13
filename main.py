"""
main.py — Tender Monitor v6 (FULL COVERAGE)
GitHub Actions calls this once per run. No while-loop needed.

SOURCES:
  DIRECT GOVT PORTALS (12):
    GeM BidPlus, CPPP/eProcure, eTenders NIC, ISTM, NCERT/NIOS,
    NSDC/Skill India, NIELIT, BIS, DOPT/Karmayogi, MoD/DRDO,
    AP eProcure, MahaTenders

  AGGREGATORS (7):
    TenderDetail, TendersOnTime, BidAssist, NationalTenders,
    FirstTender, TenderTiger, TenderDekho

  WEB SEARCH:
    DuckDuckGo (site-targeted at GeM, CPPP, govt portals)
"""

import requests
from bs4 import BeautifulSoup
import smtplib
import sqlite3
import hashlib
import logging
import os
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config from GitHub Secrets ────────────────────────────────────────
SMTP_USER   = os.environ.get("SMTP_USER", "")
SMTP_PASS   = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "madan78au@hotmail.com")
DB_PATH     = "tenders.db"

# ── Keywords ──────────────────────────────────────────────────────────
KEYWORDS = [
    # ── eLearning / LMS ──────────────────────────────────────────
    "e-learning", "elearning", "e learning", "elearning",
    "lms", "learning management system",
    "digital learning", "digital learning solutions", "dls",
    "cbt", "computer based training",
    "wbt", "web based training",
    "scorm", "xapi", "x-api", "tin can",
    "learning platform", "training portal",
    "online learning", "online training", "blended learning",
    "mobile learning", "mlearning",
    "training platform", "skilling platform",

    # ── Content Development ──────────────────────────────────────
    "content development", "content design", "content creation",
    "instructional design",
    "storyboarding",
    "courseware", "course development",
    "module development", "learning module",
    "video based learning", "video learning", "explainer video",
    "assessment creation", "assessment development",
    "mcq development", "mcq creation", "question bank",
    "rapid authoring", "rapid elearning",
    "animation training", "2d animation", "3d animation",
    "multimedia content", "multimedia development",
    "digital content",

    # ── AR / VR / Immersive ──────────────────────────────────────
    "ar/vr", "ar vr",
    "virtual reality", "augmented reality",
    "immersive learning", "immersive technology", "immersive",
    "simulation training", "simulation based",
    "metaverse learning", "metaverse",
    "mixed reality", "xr", "extended reality",
    "vr training simulator", "vr simulator",

    # ── iGOT / Govt Training ─────────────────────────────────────
    "igot", "iGOT", "karmayogi", "integrated government online training",
    "civil services training", "capacity building",
    "nsdc", "nielit", "nios", "ncert digital",
    "defence training",

    # ── BFSI / Insurance ─────────────────────────────────────────
    "bfsi", "banking financial services",
    "los", "loan origination system", "loan origination",
    "insurance core", "insurance platform",
    "underwriting", "underwriting system",
    "queue management", "queue management system",
    "lending platform", "lending solution",
    "nbfc", "microfinance", "credit appraisal",
    "claims management", "policy management",

    # ── AI / Tech ────────────────────────────────────────────────
    "ai avatar", "ai-avatar", "virtual avatar",
    "conversational ai", "chatbot training",
    "digital twin",
]

EXCLUDE = [
    "hand pump", "solar panel", "fodder", "road construction",
    "civil works", "plumbing", "electrical wiring", "furniture supply",
    "vehicle", "generator", "pump set", "valve", "borewell",
    "water supply", "sanitation", "drainage", "earthwork",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

# Source categories for email display
GOVT_SOURCES = {
    "GeM BidPlus ★",
    "CPPP / eProcure ★",
    "eTenders NIC ★",
    "ISTM ★",
    "NCERT / NIOS ★",
    "NSDC / Skill India ★",
    "NIELIT ★",
    "BIS ★",
    "DOPT / Karmayogi ★",
    "MoD / DRDO ★",
    "AP eProcure ★",
    "MahaTenders ★",
    "Web Search (Govt Portals)",
}

SOURCE_COLOR = {
    "GeM BidPlus ★":           "#1a237e",
    "CPPP / eProcure ★":       "#4a148c",
    "eTenders NIC ★":          "#880e4f",
    "ISTM ★":                  "#b71c1c",
    "NCERT / NIOS ★":          "#e65100",
    "NSDC / Skill India ★":    "#1b5e20",
    "NIELIT ★":                "#006064",
    "BIS ★":                   "#37474f",
    "DOPT / Karmayogi ★":      "#4e342e",
    "MoD / DRDO ★":            "#212121",
    "AP eProcure ★":           "#0d47a1",
    "MahaTenders ★":           "#1565c0",
    "Web Search (Govt Portals)":"#00838f",
    "TenderDetail":            "#ef6c00",
    "TendersOnTime":           "#2e7d32",
    "BidAssist":               "#1976d2",
    "NationalTenders":         "#5d4037",
    "FirstTender":             "#455a64",
    "TenderTiger":             "#6a1b9a",
    "TenderDekho":             "#ad1457",
}


# ─────────────────────────────────────────────────────────────────────
# DATABASE — deduplication
# ─────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            hash  TEXT PRIMARY KEY,
            title TEXT,
            source TEXT,
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def is_new(conn, tender):
    raw = (tender.get("title", "") + tender.get("link", "")).lower().strip()
    h   = hashlib.md5(raw.encode()).hexdigest()
    row = conn.execute("SELECT hash FROM seen WHERE hash=?", (h,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT OR IGNORE INTO seen(hash,title,source) VALUES(?,?,?)",
            (h, tender.get("title","")[:500], tender.get("source",""))
        )
        conn.commit()
        return True
    return False


# ─────────────────────────────────────────────────────────────────────
# KEYWORD MATCHER
# ─────────────────────────────────────────────────────────────────────
def matches(tender):
    title = tender.get("title", "").lower()
    for ex in EXCLUDE:
        if ex in title:
            return False, []
    hits = [kw for kw in KEYWORDS if kw.lower() in title]
    return len(hits) > 0, hits


# ─────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────
def get(url, params=None, post_data=None, timeout=20):
    try:
        if post_data:
            r = requests.post(url, data=post_data, headers=HEADERS, timeout=timeout)
        else:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"FETCH FAILED [{url[:70]}]: {e}")
        return None


def clean(text):
    """Strip extra whitespace from scraped text."""
    return " ".join(str(text).split()).strip() if text else "N/A"


def make_tender(title, link, source, base_url="",
                bid_id="N/A", department="N/A",
                estimated_value="N/A", deadline="N/A"):
    if link and not link.startswith("http") and base_url:
        link = base_url + link
    return {
        "title":           clean(title)[:350],
        "link":            link or "",
        "source":          source,
        "bid_id":          bid_id or "N/A",
        "department":      department or "N/A",
        "estimated_value": estimated_value or "N/A",
        "deadline":        deadline or "N/A",
    }


def parse_table_rows(soup, source, base_url, col_title=1, col_link=1):
    results = []
    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) > col_title:
            t    = cols[col_title].get_text(strip=True)
            a    = cols[col_link].find("a", href=True)
            link = a["href"] if a else base_url
            dept = cols[0].get_text(strip=True) if cols else "N/A"
            deadline = "N/A"
            value    = "N/A"
            for col in cols[2:]:
                txt = col.get_text(strip=True)
                if any(x in txt.lower() for x in ["rs.","inr","lakh","crore","amount","₹"]):
                    value = clean(txt)
                if any(x in txt.lower() for x in ["2025","2026","2027","deadline","last date","due date"]):
                    deadline = clean(txt)
            if len(t) > 10:
                results.append(make_tender(
                    title=t, link=link, source=source, base_url=base_url,
                    department=clean(dept), deadline=deadline,
                    estimated_value=value,
                ))
    return results


# ═════════════════════════════════════════════════════════════════════
# GOVT PORTAL SCRAPERS
# ═════════════════════════════════════════════════════════════════════

# 1. GeM BidPlus — extracts structured fields
def scrape_gem():
    results = []
    log.info("--- GeM BidPlus ---")
    url = "https://bidplus.gem.gov.in/all-bids"
    r = get(url, timeout=25)
    if not r:
        log.warning("GeM BidPlus: blocked/unreachable (cloud IP). Using web search fallback.")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    # GeM bid cards contain bid_no, item name, dept, quantity, end date
    for card in soup.find_all("div", class_=lambda c: c and "bid" in str(c).lower())[:50]:
        full_text = card.get_text(" ", strip=True)
        a = card.find("a", href=True)
        link = ("https://bidplus.gem.gov.in" + a["href"]) if a else url

        # Extract Bid ID (format: GEM/2026/B/XXXXXXX)
        import re
        bid_id_match = re.search(r"GEM/\d{4}/[A-Z]/\d+", full_text, re.IGNORECASE)
        bid_id = bid_id_match.group(0) if bid_id_match else "N/A"

        # Extract department
        dept_tag = card.find(class_=lambda c: c and "dept" in str(c).lower())
        dept = clean(dept_tag.get_text()) if dept_tag else "N/A"

        # Extract deadline (look for "End Date" or date pattern)
        deadline_match = re.search(r"End\s*Date[:\s]*([\d/\-\.]+\s*\d*:\d*)", full_text, re.IGNORECASE)
        deadline = deadline_match.group(1).strip() if deadline_match else "N/A"

        # Extract estimated value
        value_match = re.search(r"(?:Total\s*Quantity|Estimated Value|EMD)[:\s₹]*([\d,\.]+\s*(?:Lakh|Crore|L|Cr)?)", full_text, re.IGNORECASE)
        value = value_match.group(1).strip() if value_match else "N/A"

        # Title = item description
        title = full_text[:250] if full_text else "GeM Bid"

        if len(title) > 15:
            results.append(make_tender(
                title=title, link=link, source="GeM BidPlus ★",
                bid_id=bid_id, department=dept,
                estimated_value=value, deadline=deadline,
            ))
    log.info(f"GeM BidPlus: {len(results)}")
    return results


# 2. CPPP / eProcure
def scrape_cppp():
    results = []
    log.info("--- CPPP / eProcure.gov.in ---")
    url = "https://eprocure.gov.in/eprocure/app"
    params = {
        "component": "$DirectLink",
        "page": "FrontEndLatestActiveTenders",
        "service": "direct",
    }
    r = get(url, params=params, timeout=25)
    if not r:
        log.warning("CPPP: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    results = parse_table_rows(soup, "CPPP / eProcure ★", "https://eprocure.gov.in")
    log.info(f"CPPP: {len(results)}")
    return results


# 3. eTenders NIC
def scrape_etenders_nic():
    results = []
    log.info("--- eTenders NIC ---")
    url = "https://etenders.gov.in/eprocure/app"
    params = {
        "component": "$DirectLink",
        "page": "FrontEndLatestActiveTenders",
        "service": "direct",
    }
    r = get(url, params=params, timeout=25)
    if not r:
        log.warning("eTenders NIC: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    results = parse_table_rows(soup, "eTenders NIC ★", "https://etenders.gov.in")
    log.info(f"eTenders NIC: {len(results)}")
    return results


# 4. ISTM — Institute of Secretariat Training & Management
def scrape_istm():
    results = []
    log.info("--- ISTM ---")
    urls = [
        "https://istm.gov.in/tenders",
        "https://istm.gov.in/notices",
    ]
    for url in urls:
        r = get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a", "li", "td", "p"]):
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://istm.gov.in" + link
            if len(t) > 15:
                results.append(make_tender(t, link, "ISTM ★"))
        time.sleep(1)
    log.info(f"ISTM: {len(results)}")
    return results


# 5. NCERT / NIOS
def scrape_ncert_nios():
    results = []
    log.info("--- NCERT / NIOS ---")
    sources = [
        ("https://ncert.nic.in/tenders.php", "https://ncert.nic.in"),
        ("https://www.nios.ac.in/tender-notice.aspx", "https://www.nios.ac.in"),
    ]
    for url, base in sources:
        r = get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a", "td", "li"]):
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = base + link
            if len(t) > 15:
                results.append(make_tender(t, link, "NCERT / NIOS ★"))
        time.sleep(1)
    log.info(f"NCERT/NIOS: {len(results)}")
    return results


# 6. NSDC / Skill India
def scrape_nsdc():
    results = []
    log.info("--- NSDC / Skill India ---")
    urls = [
        "https://nsdcindia.org/tenders",
        "https://www.skillindiadigital.gov.in/tenders",
    ]
    for url in urls:
        r = get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a", "li", "td", "div"],
                                  class_=lambda c: c and
                                  any(x in str(c).lower() for x in ["tender","notice","bid"])):
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://nsdcindia.org" + link
            if len(t) > 15:
                results.append(make_tender(t, link, "NSDC / Skill India ★"))
        time.sleep(1)
    log.info(f"NSDC: {len(results)}")
    return results


# 7. NIELIT
def scrape_nielit():
    results = []
    log.info("--- NIELIT ---")
    url = "https://nielit.gov.in/content/tenders"
    r = get(url, timeout=20)
    if not r:
        log.warning("NIELIT: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup.find_all(["a", "td", "li"]):
        t = tag.get_text(strip=True)
        a = tag if tag.name == "a" else tag.find("a", href=True)
        link = a["href"] if a and a.has_attr("href") else url
        if not link.startswith("http"):
            link = "https://nielit.gov.in" + link
        if len(t) > 15:
            results.append(make_tender(t, link, "NIELIT ★"))
    log.info(f"NIELIT: {len(results)}")
    return results


# 8. BIS — Bureau of Indian Standards
def scrape_bis():
    results = []
    log.info("--- BIS ---")
    url = "https://www.bis.gov.in/index.php/about-bis/tenders/"
    r = get(url, timeout=20)
    if not r:
        log.warning("BIS: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup.find_all(["a", "td", "li"]):
        t = tag.get_text(strip=True)
        a = tag if tag.name == "a" else tag.find("a", href=True)
        link = a["href"] if a and a.has_attr("href") else url
        if not link.startswith("http"):
            link = "https://www.bis.gov.in" + link
        if len(t) > 15:
            results.append(make_tender(t, link, "BIS ★"))
    log.info(f"BIS: {len(results)}")
    return results


# 9. DOPT / Karmayogi Bharat
def scrape_dopt_karmayogi():
    results = []
    log.info("--- DOPT / Karmayogi ---")
    urls = [
        "https://dopt.gov.in/tenders",
        "https://karmayogi.gov.in/tenders",
        "https://igotkarmayogi.gov.in/tenders",
    ]
    for url in urls:
        r = get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a", "li", "td"]):
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://dopt.gov.in" + link
            if len(t) > 15:
                results.append(make_tender(t, link, "DOPT / Karmayogi ★"))
        time.sleep(1)
    log.info(f"DOPT/Karmayogi: {len(results)}")
    return results


# 10. MoD / DRDO / Defence
def scrape_mod_drdo():
    results = []
    log.info("--- MoD / DRDO ---")
    urls = [
        "https://ddpmod.gov.in/tenders",
        "https://www.drdo.gov.in/tenders",
    ]
    for url in urls:
        r = get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a", "li", "td"]):
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = url.split("/tenders")[0] + link
            if len(t) > 15:
                results.append(make_tender(t, link, "MoD / DRDO ★"))
        time.sleep(1)
    log.info(f"MoD/DRDO: {len(results)}")
    return results


# 11. AP eProcure (Andhra Pradesh)
def scrape_ap_eprocure():
    results = []
    log.info("--- AP eProcure ---")
    url = "https://tender.apeprocurement.gov.in/tenders/active"
    r = get(url, timeout=20)
    if not r:
        log.warning("AP eProcure: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    results = parse_table_rows(soup, "AP eProcure ★", "https://tender.apeprocurement.gov.in")
    log.info(f"AP eProcure: {len(results)}")
    return results


# 12. MahaTenders (Maharashtra)
def scrape_mahatenders():
    results = []
    log.info("--- MahaTenders ---")
    url = "https://mahatenders.gov.in/nicgep/app"
    params = {
        "component": "$DirectLink",
        "page": "FrontEndLatestActiveTenders",
        "service": "direct",
    }
    r = get(url, params=params, timeout=20)
    if not r:
        log.warning("MahaTenders: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    results = parse_table_rows(soup, "MahaTenders ★", "https://mahatenders.gov.in")
    log.info(f"MahaTenders: {len(results)}")
    return results


# ═════════════════════════════════════════════════════════════════════
# AGGREGATOR SCRAPERS
# ═════════════════════════════════════════════════════════════════════

# 13. TenderDetail
def scrape_tenderdetail():
    results = []
    log.info("--- TenderDetail ---")
    urls = [
        "https://www.tenderdetail.com/Indian-tender/e-learning-content-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/e-learning-tenders",
        "https://www.tenderdetail.com/Indian-tender/immersive-tenders-tenders",
        "https://www.tenderdetail.com/Indian-tender/lms-tenders",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for div in soup.find_all("div",
                                  class_=lambda c: c and "tender" in str(c).lower())[:30]:
            t = div.get_text(" ", strip=True)[:300]
            a = div.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tenderdetail.com" + link
            if len(t) > 20:
                results.append(make_tender(t, link, "TenderDetail"))
        time.sleep(1)
    log.info(f"TenderDetail: {len(results)}")
    return results


# 14. TendersOnTime
def scrape_tendersontime():
    results = []
    log.info("--- TendersOnTime ---")
    urls = [
        "https://www.tendersontime.com/indiaproducts/indian-e-learning-tenders-1546/",
        "https://www.tendersontime.com/indiaproducts/indian-learning-and-development-tenders-3920/",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h3", "h4", "li"])[:40]:
            t = tag.get_text(strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tendersontime.com" + link
            if len(t) > 20:
                results.append(make_tender(t, link, "TendersOnTime"))
        time.sleep(1)
    log.info(f"TendersOnTime: {len(results)}")
    return results


# 15. BidAssist
def scrape_bidassist():
    results = []
    log.info("--- BidAssist ---")
    for kw in ["e-learning content development", "igot tender",
               "lms government", "ar vr training", "immersive learning"]:
        url = f"https://bidassist.com/tenders?q={requests.utils.quote(kw)}&country=India"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.find_all("div",
                                   class_=lambda c: c and "tender" in str(c).lower())[:15]:
            t = card.get_text(" ", strip=True)[:300]
            a = card.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://bidassist.com" + link
            if len(t) > 20:
                results.append(make_tender(t, link, "BidAssist"))
        time.sleep(2)
    log.info(f"BidAssist: {len(results)}")
    return results


# 16. NationalTenders
def scrape_nationaltenders():
    results = []
    log.info("--- NationalTenders ---")
    for kw in ["e-learning", "igot", "lms", "immersive learning", "ar vr"]:
        url = f"https://www.nationaltenders.com/tender/search?q={requests.utils.quote(kw)}"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h2", "h3", "a"],
                                   class_=lambda c: c and "tender" in str(c).lower())[:20]:
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://www.nationaltenders.com" + link
            if len(t) > 15:
                results.append(make_tender(t, link, "NationalTenders"))
        time.sleep(1)
    log.info(f"NationalTenders: {len(results)}")
    return results


# 17. FirstTender
def scrape_firsttender():
    results = []
    log.info("--- FirstTender ---")
    for kw in ["e-learning", "igot", "lms learning management", "immersive"]:
        url = f"https://www.firsttender.com/tender/search-result.aspx?SearchFor={requests.utils.quote(kw)}"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for td in soup.find_all("td")[:40]:
            t = td.get_text(strip=True)[:250]
            a = td.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.firsttender.com" + link
            if len(t) > 20:
                results.append(make_tender(t, link, "FirstTender"))
        time.sleep(1)
    log.info(f"FirstTender: {len(results)}")
    return results


# 18. TenderTiger
def scrape_tendertiger():
    results = []
    log.info("--- TenderTiger ---")
    for kw in ["e-learning", "igot", "lms", "ar vr immersive"]:
        url = f"https://www.tendertiger.com/tender/search?q={requests.utils.quote(kw)}&country=india"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h2", "h3", "div"],
                                   class_=lambda c: c and "tender" in str(c).lower())[:20]:
            t = tag.get_text(strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tendertiger.com" + link
            if len(t) > 15:
                results.append(make_tender(t, link, "TenderTiger"))
        time.sleep(1)
    log.info(f"TenderTiger: {len(results)}")
    return results


# 19. TenderDekho
def scrape_tenderdekho():
    results = []
    log.info("--- TenderDekho ---")
    for kw in ["e-learning", "igot", "lms", "immersive"]:
        url = f"https://www.tenderdekho.com/tender/search.aspx?keyword={requests.utils.quote(kw)}"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h2", "h3", "div", "a"],
                                   class_=lambda c: c and "tender" in str(c).lower())[:20]:
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://www.tenderdekho.com" + link
            if len(t) > 15:
                results.append(make_tender(t, link, "TenderDekho"))
        time.sleep(1)
    log.info(f"TenderDekho: {len(results)}")
    return results


# ═════════════════════════════════════════════════════════════════════
# WEB SEARCH — catches anything missed above
# ═════════════════════════════════════════════════════════════════════
def scrape_duckduckgo():
    results = []
    log.info("--- DuckDuckGo Web Search ---")
    queries = [
        'site:gem.gov.in OR site:bidplus.gem.gov.in "e-learning" OR "igot" OR "lms"',
        'site:eprocure.gov.in "e-learning" OR "igot" OR "lms" OR "immersive"',
        'site:etenders.gov.in "e-learning" OR "lms" OR "igot"',
        'site:nsdc.in OR site:nsdcindia.org "e-learning" OR "lms" tender 2026',
        'site:nielit.gov.in "e-learning" OR "lms" tender 2026',
        '"igot karmayogi" "content development" tender 2026',
        '"AR VR" OR "immersive learning" government tender India 2026',
        '"learning management system" government tender India 2026',
        '"digital learning solutions" government tender India 2026',
        '"e-learning content development" tender India site:gov.in',
    ]
    for q in queries:
        r = get("https://html.duckduckgo.com/html/",
                post_data={"q": q, "kl": "in-en"})
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for res in soup.find_all("div", class_="result__body")[:6]:
            ta = res.find("a", class_="result__a")
            ts = res.find("a", class_="result__snippet")
            title   = ta.get_text(strip=True) if ta else ""
            link    = ta["href"] if ta and ta.has_attr("href") else ""
            snippet = ts.get_text(strip=True) if ts else ""
            full    = f"{title} — {snippet}"
            if len(title) > 10:
                results.append(make_tender(full, link, "Web Search (Govt Portals)"))
        time.sleep(2)
    log.info(f"DuckDuckGo: {len(results)}")
    return results


# ─────────────────────────────────────────────────────────────────────
# EMAIL — Structured card format
# ─────────────────────────────────────────────────────────────────────
def tender_card(t, color):
    """Render one tender as a structured info card."""
    kws   = " · ".join(t.get("hits", [])[:6])
    title = t.get("title", "N/A")[:220]
    link  = t.get("link", "#")
    bid_id  = t.get("bid_id", "N/A")
    dept    = t.get("department", "N/A")
    value   = t.get("estimated_value", "N/A")
    deadline= t.get("deadline", "N/A")
    src     = t.get("source", "")

    return f"""
    <tr>
      <td style="padding:14px 16px 14px 16px;border-bottom:2px solid #e8eaf6;">
        <!-- Source badge -->
        <div style="margin-bottom:6px;">
          <span style="background:{color};color:#fff;padding:2px 9px;
              border-radius:10px;font-size:10px;font-weight:bold;">{src}</span>
        </div>

        <!-- Tender Title -->
        <a href="{link}" style="color:#1a237e;font-weight:bold;font-size:14px;
           text-decoration:none;line-height:1.4;">{title}</a>

        <!-- Structured Fields -->
        <table style="margin-top:10px;width:100%;border-collapse:collapse;
               font-size:12px;">
          <tr>
            <td style="padding:4px 8px;background:#f5f5f5;border-radius:4px;
                width:50%;vertical-align:top;">
              <span style="color:#888;font-size:10px;display:block;">
                🔖 BID ID / TENDER NO</span>
              <strong style="color:#333;">{bid_id}</strong>
            </td>
            <td style="padding:4px 8px;width:8%;"></td>
            <td style="padding:4px 8px;background:#f5f5f5;border-radius:4px;
                width:42%;vertical-align:top;">
              <span style="color:#888;font-size:10px;display:block;">
                🏢 DEPARTMENT</span>
              <strong style="color:#333;">{dept}</strong>
            </td>
          </tr>
          <tr><td colspan="3" style="height:6px;"></td></tr>
          <tr>
            <td style="padding:4px 8px;background:#e8f5e9;border-radius:4px;
                width:50%;vertical-align:top;">
              <span style="color:#888;font-size:10px;display:block;">
                💰 ESTIMATED VALUE</span>
              <strong style="color:#2e7d32;">{value}</strong>
            </td>
            <td style="padding:4px 8px;width:8%;"></td>
            <td style="padding:4px 8px;background:#fff3e0;border-radius:4px;
                width:42%;vertical-align:top;">
              <span style="color:#888;font-size:10px;display:block;">
                ⏰ SUBMISSION DEADLINE</span>
              <strong style="color:#e65100;">{deadline}</strong>
            </td>
          </tr>
        </table>

        <!-- Keywords -->
        <div style="margin-top:8px;font-size:10px;color:#999;">
          🔑 Keywords matched: {kws}
        </div>
      </td>
    </tr>"""


def build_section(items, heading, bg):
    if not items:
        return ""
    by_src = {}
    for t in items:
        by_src.setdefault(t["source"], []).append(t)
    html = f"""
    <tr>
      <td style="background:{bg};color:#fff;padding:10px 16px;
          font-size:13px;font-weight:bold;letter-spacing:0.5px;">
        {heading} &nbsp;({len(items)})
      </td>
    </tr>"""
    for src, sitems in by_src.items():
        color = SOURCE_COLOR.get(src, "#555")
        html += f"""
    <tr>
      <td style="background:{color};color:#fff;padding:5px 16px;
          font-size:11px;font-weight:bold;">
        {src} — {len(sitems)} tender(s)
      </td>
    </tr>"""
        for t in sitems:
            html += tender_card(t, color)
    return html


def send_email(tenders):
    if not SMTP_USER or not SMTP_PASS:
        log.error("SMTP credentials missing — set GitHub Secrets SMTP_USER and SMTP_PASS")
        return

    date_str = datetime.now().strftime("%d %b %Y %I:%M %p")
    govt = [t for t in tenders if t["source"] in GOVT_SOURCES]
    agg  = [t for t in tenders if t["source"] not in GOVT_SOURCES]

    rows  = build_section(govt, "🏛️ DIRECT GOVT PORTALS", "#1a237e")
    rows += build_section(agg,  "📋 AGGREGATOR SITES",    "#37474f")

    html = f"""<!DOCTYPE html><html><body
    style="font-family:Arial,sans-serif;background:#ececec;margin:0;padding:16px;">
    <div style="max-width:720px;margin:auto;background:#fff;border-radius:10px;
         overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.15);">

      <!-- Header -->
      <div style="background:linear-gradient(135deg,#1a237e,#0d47a1);
           padding:22px 24px;color:#fff;">
        <h2 style="margin:0;font-size:21px;">
          🔔 Tender Alert — {len(tenders)} New Match(es)
        </h2>
        <p style="margin:6px 0 0;color:#bbdefb;font-size:12px;">
          {date_str} IST &nbsp;|&nbsp;
          {len(govt)} Govt Portal · {len(agg)} Aggregator
        </p>
      </div>

      <!-- Sources bar -->
      <div style="padding:8px 16px;background:#e8eaf6;font-size:10px;
           color:#3949ab;line-height:1.8;">
        <strong>20 Sources:</strong>
        🏛️ GeM · CPPP · eTenders NIC · ISTM · NCERT/NIOS · NSDC · NIELIT ·
        BIS · DOPT/Karmayogi · MoD/DRDO · AP eProcure · MahaTenders &nbsp;|&nbsp;
        📋 TenderDetail · TendersOnTime · BidAssist · NationalTenders ·
        FirstTender · TenderTiger · TenderDekho · Web Search
      </div>

      <!-- Tender Cards -->
      <table style="width:100%;border-collapse:collapse;">
        <tbody>{rows}</tbody>
      </table>

      <!-- Footer -->
      <div style="padding:12px 16px;background:#f5f5f5;font-size:10px;
           color:#aaa;border-top:1px solid #eee;text-align:center;">
        Novac Technology Solutions — Tender Monitor v7 | GitHub Actions · Free · 4x Daily
      </div>
    </div></body></html>"""

    subject = (
        f"[Tender Alert] {len(tenders)} new tender(s) — "
        f"{len(govt)} Govt · {len(agg)} Aggregator | {date_str}"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = ALERT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        log.info(f"✅ Email sent → {ALERT_EMAIL} ({len(tenders)} tenders)")
    except Exception as e:
        log.error(f"❌ Email failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("Tender Monitor v6 — GitHub Actions Run")
    log.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    conn = init_db()

    # ── GOVT PORTALS (12) ──
    all_raw = []
    all_raw += scrape_gem()
    all_raw += scrape_cppp()
    all_raw += scrape_etenders_nic()
    all_raw += scrape_istm()
    all_raw += scrape_ncert_nios()
    all_raw += scrape_nsdc()
    all_raw += scrape_nielit()
    all_raw += scrape_bis()
    all_raw += scrape_dopt_karmayogi()
    all_raw += scrape_mod_drdo()
    all_raw += scrape_ap_eprocure()
    all_raw += scrape_mahatenders()

    # ── AGGREGATORS (7) ──
    all_raw += scrape_tenderdetail()
    all_raw += scrape_tendersontime()
    all_raw += scrape_bidassist()
    all_raw += scrape_nationaltenders()
    all_raw += scrape_firsttender()
    all_raw += scrape_tendertiger()
    all_raw += scrape_tenderdekho()

    # ── WEB SEARCH ──
    all_raw += scrape_duckduckgo()

    log.info(f"Total scraped: {len(all_raw)}")

    # Match keywords
    matched = []
    for t in all_raw:
        hit, hits = matches(t)
        if hit:
            t["hits"] = hits
            matched.append(t)

    log.info(f"Keyword matched: {len(matched)}")

    # Filter duplicates
    new_ones = [t for t in matched if is_new(conn, t)]
    conn.close()

    log.info(f"New (unseen): {len(new_ones)}")

    if new_ones:
        send_email(new_ones)
    else:
        log.info("No new tenders this run — no email sent ✓")

    log.info("=" * 60)
    log.info("Run complete.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
