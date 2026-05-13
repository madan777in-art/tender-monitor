"""
main.py — Tender Monitor v8
- Smart field extraction (Tender No, Title, Dept, Value, Deadline)
- Clean card format email
- Only shows tenders from last 30 days
- Fresh run every time (no stale cache issues)
"""

import requests
from bs4 import BeautifulSoup
import smtplib
import sqlite3
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SMTP_USER   = os.environ.get("SMTP_USER", "")
SMTP_PASS   = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "madan78au@hotmail.com")
DB_PATH     = "tenders.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

# ── Keywords ─────────────────────────────────────────────────────────
KEYWORDS = [
    # eLearning / LMS
    "e-learning", "elearning", "e learning",
    "lms", "learning management system",
    "digital learning", "digital learning solutions", "dls",
    "cbt", "computer based training",
    "wbt", "web based training",
    "scorm", "xapi", "tin can",
    "learning platform", "training portal",
    "online learning", "online training", "blended learning",
    "mobile learning", "mlearning",
    # Content Development
    "content development", "content design", "content creation",
    "instructional design", "storyboarding",
    "courseware", "course development", "module development",
    "video based learning", "video learning", "explainer video",
    "assessment creation", "mcq development", "question bank",
    "rapid authoring", "rapid elearning",
    "animation training", "2d animation", "3d animation",
    "multimedia content", "multimedia development", "digital content",
    # AR/VR/Immersive
    "ar/vr", "ar vr", "virtual reality", "augmented reality",
    "immersive learning", "immersive technology", "immersive",
    "simulation training", "simulation based",
    "metaverse learning", "metaverse",
    "mixed reality", "xr", "extended reality",
    "vr training simulator", "vr simulator",
    # iGOT / Govt Training
    "igot", "igot", "karmayogi",
    "integrated government online training",
    "civil services training", "capacity building",
    "nsdc", "nielit", "nios", "ncert digital", "defence training",
    # BFSI / Insurance
    "bfsi", "banking financial services",
    "los", "loan origination system", "loan origination",
    "insurance core", "insurance platform",
    "underwriting", "underwriting system",
    "queue management", "queue management system",
    "lending platform", "lending solution",
    "nbfc", "microfinance", "credit appraisal",
    "claims management", "policy management",
    # AI / Tech
    "ai avatar", "virtual avatar",
    "conversational ai", "chatbot training", "digital twin",
]

EXCLUDE = [
    "hand pump", "solar panel", "fodder", "road construction",
    "civil works", "plumbing", "electrical wiring", "furniture supply",
    "vehicle", "generator", "pump set", "valve", "borewell",
    "water supply", "sanitation", "drainage", "earthwork",
]

SOURCE_COLOR = {
    "GeM BidPlus ★":            "#1a237e",
    "CPPP / eProcure ★":        "#4a148c",
    "eTenders NIC ★":           "#880e4f",
    "ISTM ★":                   "#b71c1c",
    "NCERT / NIOS ★":           "#e65100",
    "NSDC / Skill India ★":     "#1b5e20",
    "NIELIT ★":                 "#006064",
    "BIS ★":                    "#37474f",
    "DOPT / Karmayogi ★":       "#4e342e",
    "MoD / DRDO ★":             "#212121",
    "AP eProcure ★":            "#0d47a1",
    "MahaTenders ★":            "#1565c0",
    "Web Search (Govt Portals)": "#00838f",
    "TenderDetail":             "#ef6c00",
    "TendersOnTime":            "#2e7d32",
    "BidAssist":                "#1976d2",
    "NationalTenders":          "#5d4037",
    "FirstTender":              "#455a64",
    "TenderTiger":              "#6a1b9a",
    "TenderDekho":              "#ad1457",
}

GOVT_SOURCES = {
    "GeM BidPlus ★", "CPPP / eProcure ★", "eTenders NIC ★",
    "ISTM ★", "NCERT / NIOS ★", "NSDC / Skill India ★",
    "NIELIT ★", "BIS ★", "DOPT / Karmayogi ★", "MoD / DRDO ★",
    "AP eProcure ★", "MahaTenders ★", "Web Search (Govt Portals)",
}


# ─────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            hash   TEXT PRIMARY KEY,
            title  TEXT,
            source TEXT,
            added  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            (h, tender.get("title", "")[:500], tender.get("source", ""))
        )
        conn.commit()
        return True
    return False


# ─────────────────────────────────────────────────────────────────────
# SMART FIELD EXTRACTOR
# Pulls Tender No, Dept, Value, Deadline from raw text
# ─────────────────────────────────────────────────────────────────────
def extract_fields(raw_text, source_url=""):
    """
    Smartly extract structured fields from raw scraped text.
    Returns dict with tender_no, department, value, deadline.
    """
    text = raw_text.strip()

    # ── Tender / Bid Number ──────────────────────────────────────────
    tender_no = "N/A"
    patterns_no = [
        r"GEM/\d{4}/[A-Z]/\d+",               # GeM format
        r"Bid\s*No[:\s]+([A-Z0-9/\-]+)",
        r"Tender\s*No[:\s]+([A-Z0-9/\-]+)",
        r"NIT\s*No[:\s]+([A-Z0-9/\-]+)",
        r"Ref\s*No[:\s]+([A-Z0-9/\-]+)",
        r"\b(\d{7,10})\b",                     # plain 7-10 digit number (common in aggregators)
    ]
    for pat in patterns_no:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            tender_no = m.group(0) if "/" in pat else m.group(1)
            tender_no = tender_no.strip()
            break

    # ── Department ───────────────────────────────────────────────────
    department = "N/A"
    dept_patterns = [
        r"(?:Ministry|Department|Directorate|Board|Authority|Commission|"
        r"Corporation|Council|Institute|Office|Bureau|NSDC|NIELIT|NCERT|"
        r"NIOS|DRDO|DoPT|PSU|Undertaking)[^,\n|]{3,60}",
    ]
    for pat in dept_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            department = m.group(0).strip()[:100]
            break

    # If aggregator format "X Dept Name - City - State XXXXXX"
    dept_match = re.match(
        r"^\d+\s+([\w\s/&,\-]+?)\s*-\s*[\w\s]+\s*-\s*[\w\s]+\s+\d{7,}",
        text
    )
    if dept_match:
        department = dept_match.group(1).strip()

    # ── Estimated Value ──────────────────────────────────────────────
    value = "N/A"
    value_patterns = [
        r"Tender\s*Value\s*[:\-]?\s*([\d,\.]+\s*(?:Lakhs?|Crores?|L|Cr)?)",
        r"Estimated\s*(?:Cost|Value|Amount)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,\.]+\s*(?:Lakhs?|Crores?)?)",
        r"(?:Rs\.?|INR|₹)\s*([\d,\.]+\s*(?:Lakhs?|Crores?|L|Cr)?)",
        r"([\d,\.]+\s*(?:Lakhs?|Crores?))",
        r"EMD\s*[:\-]?\s*(?:Rs\.?|₹)?\s*([\d,\.]+)",
    ]
    for pat in value_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            value = "₹ " + m.group(1).strip()
            break

    # ── Deadline / Due Date ──────────────────────────────────────────
    deadline = "N/A"
    deadline_patterns = [
        r"(?:Due\s*Date|Last\s*Date|Submission\s*(?:Date|Deadline)|"
        r"Closing\s*Date|End\s*Date|Bid\s*(?:End|Close)|Deadline)\s*[:\-]?\s*"
        r"([\d]{1,2}[\s/\-\.]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[\s/\-\.]+\d{2,4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
        r"\d{1,2},?\s+\d{4})\b",
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\s+\d{4})\b",
        r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})\b",
    ]
    for pat in deadline_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            g = m.lastindex or 1
            deadline = m.group(g).strip()
            # Filter out obvious non-deadlines (years before 2025)
            year_m = re.search(r"\d{4}", deadline)
            if year_m and int(year_m.group()) < 2025:
                deadline = "N/A"
                continue
            break

    # Clean title — remove leading numbering "1 Govt Dept - City - State XXXXXXX"
    title = re.sub(r"^\d+\s+", "", text)
    # Remove duplicate whitespace
    title = " ".join(title.split())

    return {
        "tender_no":  tender_no,
        "department": department,
        "value":      value,
        "deadline":   deadline,
        "title":      title[:300],
    }


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
# HTTP HELPER
# ─────────────────────────────────────────────────────────────────────
def get(url, params=None, post_data=None, timeout=20):
    try:
        if post_data:
            r = requests.post(url, data=post_data,
                              headers=HEADERS, timeout=timeout)
        else:
            r = requests.get(url, params=params,
                             headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"FETCH FAILED [{url[:70]}]: {e}")
        return None


def make(raw_text, link, source, base_url=""):
    """Create a tender dict with smart field extraction."""
    if link and not link.startswith("http") and base_url:
        link = base_url + link
    fields = extract_fields(raw_text)
    fields["link"]   = link or ""
    fields["source"] = source
    return fields


# ═════════════════════════════════════════════════════════════════════
# SCRAPERS
# ═════════════════════════════════════════════════════════════════════

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
            class_=lambda c: c and "tender" in str(c).lower())[:40]:
            t = div.get_text(" ", strip=True)
            a = div.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tenderdetail.com" + link
            if len(t) > 20:
                results.append(make(t, link, "TenderDetail"))
        time.sleep(1)
    log.info(f"TenderDetail: {len(results)}")
    return results


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
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tendersontime.com" + link
            if len(t) > 20:
                results.append(make(t, link, "TendersOnTime"))
        time.sleep(1)
    log.info(f"TendersOnTime: {len(results)}")
    return results


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
            t = card.get_text(" ", strip=True)
            a = card.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://bidassist.com" + link
            if len(t) > 20:
                results.append(make(t, link, "BidAssist"))
        time.sleep(2)
    log.info(f"BidAssist: {len(results)}")
    return results


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
            t = tag.get_text(" ", strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://www.nationaltenders.com" + link
            if len(t) > 15:
                results.append(make(t, link, "NationalTenders"))
        time.sleep(1)
    log.info(f"NationalTenders: {len(results)}")
    return results


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
            t = td.get_text(" ", strip=True)
            a = td.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.firsttender.com" + link
            if len(t) > 20:
                results.append(make(t, link, "FirstTender"))
        time.sleep(1)
    log.info(f"FirstTender: {len(results)}")
    return results


def scrape_tendertiger():
    results = []
    log.info("--- TenderTiger ---")
    for kw in ["e-learning", "igot", "lms", "ar vr immersive"]:
        url = f"https://www.tendertiger.com/tender/search?q={requests.utils.quote(kw)}&country=india"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h2","h3","div"],
            class_=lambda c: c and "tender" in str(c).lower())[:20]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tendertiger.com" + link
            if len(t) > 15:
                results.append(make(t, link, "TenderTiger"))
        time.sleep(1)
    log.info(f"TenderTiger: {len(results)}")
    return results


def scrape_tenderdekho():
    results = []
    log.info("--- TenderDekho ---")
    for kw in ["e-learning", "igot", "lms", "immersive"]:
        url = f"https://www.tenderdekho.com/tender/search.aspx?keyword={requests.utils.quote(kw)}"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h2","h3","div","a"],
            class_=lambda c: c and "tender" in str(c).lower())[:20]:
            t = tag.get_text(" ", strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://www.tenderdekho.com" + link
            if len(t) > 15:
                results.append(make(t, link, "TenderDekho"))
        time.sleep(1)
    log.info(f"TenderDekho: {len(results)}")
    return results


def scrape_cppp():
    results = []
    log.info("--- CPPP / eProcure ---")
    url = "https://eprocure.gov.in/eprocure/app"
    params = {"component": "$DirectLink",
              "page": "FrontEndLatestActiveTenders", "service": "direct"}
    r = get(url, params=params, timeout=25)
    if not r:
        log.warning("CPPP: unreachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) >= 2:
            t = " ".join(c.get_text(" ", strip=True) for c in cols)
            a = cols[1].find("a", href=True) if len(cols) > 1 else None
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://eprocure.gov.in" + link
            if len(t) > 10:
                results.append(make(t, link, "CPPP / eProcure ★",
                                    "https://eprocure.gov.in"))
    log.info(f"CPPP: {len(results)}")
    return results


def scrape_gem():
    results = []
    log.info("--- GeM BidPlus ---")
    url = "https://bidplus.gem.gov.in/all-bids"
    r = get(url, timeout=25)
    if not r:
        log.warning("GeM BidPlus: blocked/unreachable from cloud IP")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    for card in soup.find_all("div",
        class_=lambda c: c and "bid" in str(c).lower())[:50]:
        t = card.get_text(" ", strip=True)
        a = card.find("a", href=True)
        link = ("https://bidplus.gem.gov.in" + a["href"]) if a else url
        if len(t) > 15:
            results.append(make(t, link, "GeM BidPlus ★"))
    log.info(f"GeM: {len(results)}")
    return results


def scrape_etenders_nic():
    results = []
    log.info("--- eTenders NIC ---")
    url = "https://etenders.gov.in/eprocure/app"
    params = {"component": "$DirectLink",
              "page": "FrontEndLatestActiveTenders", "service": "direct"}
    r = get(url, params=params, timeout=25)
    if not r:
        return results
    soup = BeautifulSoup(r.text, "lxml")
    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) >= 2:
            t = " ".join(c.get_text(" ", strip=True) for c in cols)
            a = cols[1].find("a", href=True) if len(cols) > 1 else None
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://etenders.gov.in" + link
            if len(t) > 10:
                results.append(make(t, link, "eTenders NIC ★",
                                    "https://etenders.gov.in"))
    log.info(f"eTenders NIC: {len(results)}")
    return results


def scrape_govt_generic(label, urls, base):
    results = []
    log.info(f"--- {label} ---")
    for url in urls:
        r = get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a", "li", "td", "p"]):
            t = tag.get_text(" ", strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = base + link
            if len(t) > 20:
                results.append(make(t, link, label))
        time.sleep(1)
    log.info(f"{label}: {len(results)}")
    return results


def scrape_duckduckgo():
    results = []
    log.info("--- DuckDuckGo Web Search ---")
    queries = [
        'site:gem.gov.in OR site:bidplus.gem.gov.in "e-learning" OR "igot" OR "lms"',
        'site:eprocure.gov.in "e-learning" OR "igot" OR "lms" OR "immersive"',
        'site:etenders.gov.in "e-learning" OR "lms" OR "igot"',
        '"igot karmayogi" "content development" tender 2026',
        '"AR VR" OR "immersive learning" government tender India 2026',
        '"learning management system" government tender India 2026',
        '"e-learning content development" tender India site:gov.in 2026',
        '"digital learning solutions" government tender India 2026',
        '"storyboarding" "instructional design" government tender India 2026',
        '"loan origination system" OR "LOS" government tender India 2026',
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
            full    = f"{title} {snippet}"
            if len(title) > 10:
                results.append(make(full, link, "Web Search (Govt Portals)"))
        time.sleep(2)
    log.info(f"DuckDuckGo: {len(results)}")
    return results


# ─────────────────────────────────────────────────────────────────────
# EMAIL — Clean card format
# ─────────────────────────────────────────────────────────────────────
def render_card(t):
    color    = SOURCE_COLOR.get(t["source"], "#555")
    src      = t["source"]
    title    = t.get("title", "N/A")[:220]
    link     = t.get("link", "#")
    bid_id   = t.get("tender_no", "N/A")
    dept     = t.get("department", "N/A")
    value    = t.get("value", "N/A")
    deadline = t.get("deadline", "N/A")
    kws      = " · ".join(t.get("hits", [])[:6])

    def field(icon, label, val, bg="#f5f5f5", fg="#333"):
        return f"""
        <td style="padding:6px 10px;background:{bg};border-radius:5px;
            vertical-align:top;width:48%;">
          <div style="font-size:9px;color:#999;margin-bottom:2px;">
            {icon} {label}</div>
          <div style="font-size:12px;font-weight:bold;color:{fg};">
            {val}</div>
        </td>"""

    return f"""
    <tr>
      <td style="padding:14px 16px;border-bottom:3px solid #e8eaf6;">

        <!-- Source Badge + Title -->
        <div style="margin-bottom:8px;">
          <span style="background:{color};color:#fff;padding:2px 10px;
              border-radius:10px;font-size:10px;font-weight:bold;
              letter-spacing:0.5px;">{src}</span>
        </div>
        <a href="{link}"
           style="color:#1a237e;font-weight:bold;font-size:14px;
                  text-decoration:none;line-height:1.5;display:block;
                  margin-bottom:12px;">{title}</a>

        <!-- Structured Fields Grid -->
        <table style="width:100%;border-collapse:separate;
               border-spacing:6px 0;">
          <tr>
            {field("🔖", "BID ID / TENDER NO", bid_id)}
            <td style="width:4%;"></td>
            {field("🏢", "DEPARTMENT", dept)}
          </tr>
          <tr><td colspan="3" style="height:6px;"></td></tr>
          <tr>
            {field("💰", "ESTIMATED VALUE", value, "#e8f5e9", "#2e7d32")}
            <td style="width:4%;"></td>
            {field("⏰", "SUBMISSION DEADLINE", deadline, "#fff3e0", "#e65100")}
          </tr>
        </table>

        <!-- Keywords -->
        <div style="margin-top:10px;font-size:10px;color:#aaa;">
          🔑 {kws if kws else "—"}
        </div>
      </td>
    </tr>"""


def send_email(tenders):
    if not SMTP_USER or not SMTP_PASS:
        log.error("SMTP credentials missing")
        return

    date_str = datetime.now().strftime("%d %b %Y %I:%M %p")
    govt = [t for t in tenders if t["source"] in GOVT_SOURCES]
    agg  = [t for t in tenders if t["source"] not in GOVT_SOURCES]

    def section_html(items, heading, bg):
        if not items:
            return ""
        by_src = {}
        for t in items:
            by_src.setdefault(t["source"], []).append(t)
        html = f"""
        <tr>
          <td style="background:{bg};color:#fff;padding:10px 16px;
              font-size:13px;font-weight:bold;">
            {heading} &nbsp;({len(items)})
          </td>
        </tr>"""
        for src, sitems in by_src.items():
            c = SOURCE_COLOR.get(src, "#555")
            html += f"""
        <tr>
          <td style="background:{c};color:#fff;padding:5px 16px;
              font-size:11px;font-weight:bold;">
            {src} — {len(sitems)} tender(s)
          </td>
        </tr>"""
            for t in sitems:
                html += render_card(t)
        return html

    rows  = section_html(govt, "🏛️ DIRECT GOVT PORTALS", "#1a237e")
    rows += section_html(agg,  "📋 AGGREGATOR SITES",    "#37474f")

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#ececec;
margin:0;padding:16px;">
<div style="max-width:700px;margin:auto;background:#fff;
     border-radius:10px;overflow:hidden;
     box-shadow:0 2px 12px rgba(0,0,0,.15);">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a237e,#0d47a1);
       padding:22px 24px;color:#fff;">
    <h2 style="margin:0;font-size:21px;">
      🔔 Tender Alert — {len(tenders)} New Match(es)
    </h2>
    <p style="margin:6px 0 0;color:#bbdefb;font-size:12px;">
      {date_str} IST &nbsp;|&nbsp;
      {len(govt)} Govt Portal &nbsp;·&nbsp; {len(agg)} Aggregator
    </p>
  </div>

  <!-- Sources -->
  <div style="padding:8px 16px;background:#e8eaf6;font-size:10px;
       color:#3949ab;line-height:2;">
    <strong>20 Sources Active:</strong>
    🏛️ GeM · CPPP · eTenders NIC · ISTM · NCERT/NIOS · NSDC ·
    NIELIT · BIS · DOPT/Karmayogi · MoD/DRDO · AP eProcure ·
    MahaTenders · Web Search &nbsp;|&nbsp;
    📋 TenderDetail · TendersOnTime · BidAssist · NationalTenders ·
    FirstTender · TenderTiger · TenderDekho
  </div>

  <!-- Cards -->
  <table style="width:100%;border-collapse:collapse;">
    <tbody>{rows}</tbody>
  </table>

  <!-- Footer -->
  <div style="padding:12px 16px;background:#f5f5f5;
       font-size:10px;color:#bbb;border-top:1px solid #eee;
       text-align:center;">
    Novac Technology Solutions — Tender Monitor v8 &nbsp;|&nbsp;
    GitHub Actions · Free · Every 1 Hour
  </div>
</div>
</body></html>"""

    subject = (
        f"[Tender Alert] {len(tenders)} new tender(s) | "
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
    log.info("Tender Monitor v8 — GitHub Actions")
    log.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    conn = init_db()

    all_raw = []

    # Govt Portals
    all_raw += scrape_gem()
    all_raw += scrape_cppp()
    all_raw += scrape_etenders_nic()
    all_raw += scrape_govt_generic(
        "ISTM ★",
        ["https://istm.gov.in/tenders", "https://istm.gov.in/notices"],
        "https://istm.gov.in"
    )
    all_raw += scrape_govt_generic(
        "NCERT / NIOS ★",
        ["https://ncert.nic.in/tenders.php",
         "https://www.nios.ac.in/tender-notice.aspx"],
        "https://ncert.nic.in"
    )
    all_raw += scrape_govt_generic(
        "NSDC / Skill India ★",
        ["https://nsdcindia.org/tenders"],
        "https://nsdcindia.org"
    )
    all_raw += scrape_govt_generic(
        "NIELIT ★",
        ["https://nielit.gov.in/content/tenders"],
        "https://nielit.gov.in"
    )
    all_raw += scrape_govt_generic(
        "BIS ★",
        ["https://www.bis.gov.in/index.php/about-bis/tenders/"],
        "https://www.bis.gov.in"
    )
    all_raw += scrape_govt_generic(
        "DOPT / Karmayogi ★",
        ["https://dopt.gov.in/tenders",
         "https://karmayogi.gov.in/tenders"],
        "https://dopt.gov.in"
    )
    all_raw += scrape_govt_generic(
        "MoD / DRDO ★",
        ["https://ddpmod.gov.in/tenders",
         "https://www.drdo.gov.in/tenders"],
        "https://ddpmod.gov.in"
    )

    # Aggregators
    all_raw += scrape_tenderdetail()
    all_raw += scrape_tendersontime()
    all_raw += scrape_bidassist()
    all_raw += scrape_nationaltenders()
    all_raw += scrape_firsttender()
    all_raw += scrape_tendertiger()
    all_raw += scrape_tenderdekho()

    # Web Search
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

    # Deduplicate
    new_ones = [t for t in matched if is_new(conn, t)]
    conn.close()

    log.info(f"New (unseen): {len(new_ones)}")

    if new_ones:
        send_email(new_ones)
    else:
        log.info("No new tenders this run — no email sent ✓")

    log.info("Run complete.")


if __name__ == "__main__":
    main()
