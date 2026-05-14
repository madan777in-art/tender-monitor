"""
main.py — Tender Monitor v11 (Maximum Free Coverage)
100% FREE — No ScrapingBee needed

FREE SOURCES:
  1. TenderDetail       — 19 category URLs (confirmed working)
  2. Google News RSS    — 10 search queries (no blocking)
  3. TendersOnTime      — fixed URLs
  4. TenderDekho        — fixed selectors
  5. DuckDuckGo Search  — 10 queries

GOOGLE CUSTOM SEARCH API (FREE — 100 searches/day):
  Searches directly inside:
  - gem.gov.in / bidplus.gem.gov.in
  - eprocure.gov.in (CPPP)
  - etenders.gov.in
  - mahatenders.gov.in
  - tender.ap.gov.in
  - nielit.gov.in
  - nsdcindia.org
  - dopt.gov.in
  - istm.gov.in
  - bidassist.com
  - tendertiger.com
  - nationaltenders.com
  + General India govt tender search
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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SMTP_USER      = os.environ.get("SMTP_USER", "")
SMTP_PASS      = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL    = os.environ.get("ALERT_EMAIL", "madan78au@hotmail.com")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")   # from GitHub Secrets
GOOGLE_CX      = os.environ.get("GOOGLE_CX", "")        # Custom Search Engine ID
DB_PATH        = "tenders.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TenderBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ── Keywords ─────────────────────────────────────────────────────────
# HIGH CONFIDENCE — 1 hit is enough to match
HIGH_CONFIDENCE_KEYWORDS = [
    "e-learning", "elearning", "e learning",
    "lms", "learning management system",
    "igot", "karmayogi", "integrated government online training",
    "scorm", "xapi",
    "instructional design", "storyboarding",
    "courseware", "rapid authoring", "rapid elearning",
    "immersive learning", "simulation training",
    "digital learning solutions",
    "learning management",
    "loan origination system", "loan origination",
    "bfsi", "banking financial services",
    "underwriting system", "underwriting",
    "queue management system",
    "ai avatar", "virtual avatar",
    "conversational ai", "digital twin",
    "content development", "content creation",
    "instructional design",
    "learning platform", "training portal",
    "online learning", "online training",
    "blended learning", "mobile learning",
    "video based learning", "explainer video",
    "assessment creation", "mcq development",
    "animation training", "multimedia content",
    "ar/vr", "ar vr", "virtual reality training",
    "augmented reality training",
    "metaverse learning",
    "mixed reality",
    "vr training simulator", "vr simulator",
    "civil services training",
    "nielit", "nios", "nsdc",
    "insurance core", "insurance platform",
    "lending platform", "lending solution",
    "nbfc", "microfinance", "credit appraisal",
    "claims management", "policy management",
    "chatbot training",
]

# SECONDARY — need 2+ hits to match (prevents false positives)
SECONDARY_KEYWORDS = [
    "digital learning", "digital content",
    "content design", "module development",
    "course development", "question bank",
    "2d animation", "3d animation",
    "multimedia development",
    "virtual reality", "augmented reality",
    "immersive technology",
    "simulation based",
    "metaverse",
    "extended reality",
    "capacity building",
    "ncert digital", "defence training",
    "queue management",
    "insurance",
]

# Combined for backward compatibility
KEYWORDS = HIGH_CONFIDENCE_KEYWORDS + SECONDARY_KEYWORDS

EXCLUDE = [
    # Hardware/Infrastructure
    "hand pump", "solar panel", "fodder", "road construction",
    "civil works", "plumbing", "electrical wiring", "furniture supply",
    "vehicle", "generator", "pump set", "valve", "borewell",
    "water supply", "sanitation", "drainage", "earthwork",
    "horticulture", "agriculture", "seeds", "fertilizer",
    # Surveillance/Security
    "cctv", "surveillance", "ip camera", "security camera",
    "video surveillance", "access control",
    # Construction
    "construction of", "civil construction", "building construction",
    "renovation", "repair works", "maintenance works",
    # Irrelevant supplies
    "furniture", "chairs", "tables", "stationery", "printing",
    "canteen", "catering", "housekeeping", "cleaning services",
    "security guard", "manpower supply",
    # Medical
    "hospital", "medical equipment", "medicine", "pharmaceutical",
    # Unrelated digital
    "signage", "display board", "led display",
    "gaming", "entertainment system",
    "website development", "web portal development",
    "mobile app development",  # too generic without learning context
]

SOURCE_COLOR = {
    "GeM BidPlus ★":         "#1a237e",
    "CPPP / eProcure ★":     "#4a148c",
    "eTenders NIC ★":        "#880e4f",
    "Govt Portal ★":         "#b71c1c",
    "BidAssist":             "#1976d2",
    "TenderTiger":           "#6a1b9a",
    "NationalTenders":       "#5d4037",
    "Google Search":         "#34a853",
    "TenderDetail":          "#ef6c00",
    "TendersOnTime":         "#2e7d32",
    "TenderDekho":           "#ad1457",
    "Google News":           "#1a73e8",
    "DuckDuckGo Search":     "#de5833",
    "TendersInfo":           "#00897b",
    "Tender247":             "#f57c00",
    "BidDetail":             "#5e35b1",
    "TenderKart":            "#c62828",
    "TenderSniper":          "#2e7d32",
    "ISTM ★":                "#b71c1c",
}

GOVT_SOURCES = {
    "GeM BidPlus ★", "CPPP / eProcure ★",
    "eTenders NIC ★", "Govt Portal ★",
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
    conn.execute("DELETE FROM seen WHERE added < datetime('now', '-24 hours')")
    conn.commit()
    return conn


def is_new(conn, tender):
    raw = (tender.get("title","") + tender.get("link","")).lower().strip()
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
# FIELD EXTRACTOR
# ─────────────────────────────────────────────────────────────────────
def extract_fields(raw_text):
    text = " ".join(raw_text.split()).strip()

    # Tender No
    tender_no = "N/A"
    for pat in [
        r"GEM/\d{4}/[A-Z]/\d+",
        r"(?:Bid|Tender|NIT|Ref)\s*No[:\s]+([A-Z0-9/\-]+)",
        r"\b(\d{7,10})\b",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            tender_no = m.group(0).strip()
            break

    # Department
    department = "N/A"
    m = re.search(
        r"((?:Ministry|Department|Directorate|Board|Authority|Commission|"
        r"Corporation|Council|Institute|Office|Bureau|NSDC|NIELIT|NCERT|"
        r"NIOS|DRDO|DoPT|PSU|Undertaking|Govt|Government)[^\n,|]{3,80})",
        text, re.IGNORECASE
    )
    if m:
        department = m.group(1).strip()[:100]
    dm = re.match(
        r"^\d*\s*([\w\s/&,\-]+?)\s*-\s*[\w\s]+\s*-\s*[\w\s]+\s+\d{7,}",
        text
    )
    if dm:
        department = dm.group(1).strip()

    # Value
    value = "N/A"
    for pat in [
        r"Tender\s*Value\s*[:\-]?\s*([\d,\.]+\s*(?:Lakhs?|Crores?|L|Cr)?)",
        r"Estimated\s*(?:Cost|Value|Amount)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,\.]+\s*(?:Lakhs?|Crores?)?)",
        r"(?:Rs\.?|INR|₹)\s*([\d,\.]+\s*(?:Lakhs?|Crores?|L|Cr)?)",
        r"([\d,\.]+\s*(?:Lakhs?|Crores?))",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            value = "₹ " + m.group(1).strip()
            break

    # Deadline
    deadline = "N/A"
    for pat in [
        r"(?:Due\s*Date|Last\s*Date|Submission\s*(?:Date|Deadline)|Closing\s*Date|End\s*Date|Deadline)\s*[:\-]?\s*(\w+\s+\d{1,2}\s*,?\s*\d{4})",
        r"(?:Due\s*Date|Last\s*Date|Deadline)\s*[:\-]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\s*,?\s*\d{4})",
        r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            g = m.lastindex or 1
            dl = m.group(g).strip()
            ym = re.search(r"\d{4}", dl)
            if ym and int(ym.group()) >= 2025:
                deadline = re.sub(r"\s+", " ", re.sub(r"\s+,", ",", dl))
                break

    title = " ".join(re.sub(r"^\d+\s+", "", text).split())
    return {
        "tender_no":  tender_no,
        "department": department,
        "value":      value,
        "deadline":   deadline,
        "title":      title[:300],
    }


# ─────────────────────────────────────────────────────────────────────
# DATE FILTER
# ─────────────────────────────────────────────────────────────────────
def parse_date(date_str):
    if not date_str or date_str in ("N/A", "See article"):
        return None
    date_str = re.sub(r"\s+,", ",", date_str.strip())
    date_str = re.sub(r"\s+", " ", date_str)
    for fmt in [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d %b %Y", "%d %B %Y",
        "%b %d , %Y", "%b %d, %Y",
        "%B %d , %Y", "%B %d, %Y",
        "%b %d %Y", "%B %d %Y",
    ]:
        try:
            return datetime.strptime(date_str, fmt)
        except:
            pass
    return None


def is_recent(tender):
    dt = parse_date(tender.get("deadline", "N/A"))
    if dt is None:
        return True
    return dt >= datetime.now() - timedelta(days=1)


# ─────────────────────────────────────────────────────────────────────
# KEYWORD MATCHER — Strict 3-tier matching to eliminate false positives
# ─────────────────────────────────────────────────────────────────────
def matches(tender):
    title = tender.get("title", "").lower()

    # TIER 1: Hard exclude — reject immediately if any exclude term found
    for ex in EXCLUDE:
        if ex.lower() in title:
            return False, []

    # TIER 2: High-confidence keywords — 1 hit in first 200 chars is enough
    # This ensures keyword is in the TENDER DESCRIPTION not just page metadata
    title_start = title[:200]  # check only the core tender description
    hc_hits = [kw for kw in HIGH_CONFIDENCE_KEYWORDS if kw.lower() in title_start]
    if hc_hits:
        return True, hc_hits

    # TIER 3: Secondary keywords — need 3+ hits anywhere in full text
    # Higher threshold prevents random page-level matches
    sec_hits = [kw for kw in SECONDARY_KEYWORDS if kw.lower() in title]
    if len(sec_hits) >= 3:
        return True, sec_hits

    return False, []


def make(raw_text, link, source):
    fields = extract_fields(raw_text)
    fields["link"]   = link or ""
    fields["source"] = source
    return fields


# ─────────────────────────────────────────────────────────────────────
# HTTP HELPER
# ─────────────────────────────────────────────────────────────────────
def get(url, params=None, post_data=None, timeout=20, headers=None):
    try:
        h = headers or HEADERS
        if post_data:
            r = requests.post(url, data=post_data, headers=h, timeout=timeout)
        else:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"FETCH FAILED [{url[:70]}]: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════
# GOOGLE CUSTOM SEARCH API
# Free: 100 queries/day | No IP blocking | Searches inside any website
# ═════════════════════════════════════════════════════════════════════
def google_search(query, site_restrict=None, num=10):
    """
    Call Google Custom Search API.
    Includes proper headers to avoid 'Host not in allowlist' error.
    Returns list of {title, link, snippet} dicts.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []

    if site_restrict:
        query = f"site:{site_restrict} {query}"

    # These headers are required when API key has no referrer restrictions
    api_headers = {
        "Referer": "https://github.com",
        "X-Referer": "https://github.com",
        "Accept": "application/json",
    }

    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key":   GOOGLE_API_KEY,
                "cx":    GOOGLE_CX,
                "q":     query,
                "num":   num,
                "gl":    "in",
                "hl":    "en",
            },
            headers=api_headers,
            timeout=15,
        )
        if r.status_code == 403:
            log.warning(f"Google API 403: {r.text[:300]}")
            return []
        if r.status_code == 429:
            log.warning("Google API quota exceeded (100/day limit reached)")
            return []
        if r.status_code != 200:
            log.warning(f"Google API {r.status_code}: {r.text[:300]}")
            return []
        data = r.json()
        items = data.get("items", [])
        # Log first result for debugging
        if items:
            log.info(f"Google API OK — {len(items)} results. First: {items[0].get('title','')[:60]}")
        else:
            # No items — log the full response to understand why
            log.warning(f"Google API returned 0 items for query: {query[:80]}")
            log.warning(f"Full response keys: {list(data.keys())}")
            if "error" in data:
                log.warning(f"Error detail: {data['error']}")
            if "searchInformation" in data:
                log.warning(f"Search info: {data['searchInformation']}")
        results = []
        for item in items:
            results.append({
                "title":   item.get("title", ""),
                "link":    item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
    except Exception as e:
        log.warning(f"Google Search error: {e}")
        return []


def scrape_google_custom_search():
    """
    Google Custom Search API — improved strategy.
    NO site restriction — searches the full web with keyword queries.
    This finds tenders indexed from GeM, eProcure, BidAssist etc.
    Uses only 20 queries/run to stay well within 100/day free limit.
    """
    results = []
    log.info("--- Google Custom Search API ---")

    if not GOOGLE_API_KEY or not GOOGLE_CX:
        log.warning("GOOGLE_API_KEY or GOOGLE_CX not set — skipping")
        return results

    # All searches WITHOUT site restriction — searches the entire web
    # Google will find results from GeM, eProcure, BidAssist etc naturally
    QUERIES = [
        # iGOT / Karmayogi
        ("igot karmayogi e-learning content development tender India", "GeM BidPlus ★"),
        ("igot karmayogi lms learning management system tender", "CPPP / eProcure ★"),
        # e-Learning
        ("e-learning content development government tender India 2026", "Google Search"),
        ("elearning courseware instructional design tender India 2026", "Google Search"),
        ("digital learning solutions online training tender India", "Google Search"),
        # LMS
        ("LMS learning management system government tender India 2026", "Google Search"),
        ("learning platform training portal government bid India", "Google Search"),
        # AR/VR
        ("AR VR virtual reality augmented reality training tender India", "Google Search"),
        ("immersive learning simulation based training tender India", "Google Search"),
        ("metaverse VR simulator government tender India 2026", "Google Search"),
        # Content Dev
        ("storyboarding multimedia content development tender India", "Google Search"),
        ("rapid authoring SCORM xAPI elearning tender government India", "Google Search"),
        # GeM specific
        ("gem.gov.in e-learning igot lms tender 2026", "GeM BidPlus ★"),
        ("bidplus.gem.gov.in content development digital learning", "GeM BidPlus ★"),
        # eProcure specific
        ("eprocure.gov.in e-learning igot content development tender", "CPPP / eProcure ★"),
        ("site:eprocure.gov.in elearning lms digital learning 2026", "CPPP / eProcure ★"),
        # BFSI
        ("loan origination system LOS government tender India 2026", "Google Search"),
        ("BFSI insurance underwriting software tender India 2026", "Google Search"),
        # Aggregators
        ("bidassist.com igot elearning lms content development tender", "BidAssist"),
        ("tendertiger.com e-learning lms igot karmayogi tender India", "TenderTiger"),
    ]

    query_count = 0
    for query, source in QUERIES:
        items = google_search(query, site_restrict=None, num=10)
        query_count += 1

        for item in items:
            title   = item.get("title", "")
            link    = item.get("link", "")
            snippet = item.get("snippet", "")
            full    = f"{title} {snippet}"

            # Auto-detect source from URL
            url_lower = link.lower()
            detected_source = source
            if "gem.gov.in" in url_lower or "bidplus.gem.gov.in" in url_lower:
                detected_source = "GeM BidPlus ★"
            elif "eprocure.gov.in" in url_lower:
                detected_source = "CPPP / eProcure ★"
            elif "etenders.gov.in" in url_lower:
                detected_source = "eTenders NIC ★"
            elif "bidassist.com" in url_lower:
                detected_source = "BidAssist"
            elif "tendertiger.com" in url_lower:
                detected_source = "TenderTiger"
            elif "tenderdetail.com" in url_lower:
                detected_source = "TenderDetail"
            elif ".gov.in" in url_lower:
                detected_source = "Govt Portal ★"

            if len(title) > 10:
                t = make(full, link, detected_source)
                t["title"] = title[:300]
                results.append(t)

        time.sleep(0.5)

    log.info(f"Google Custom Search: {len(results)} results from {query_count} queries")
    log.info(f"Daily quota used: {query_count}/100 free queries")
    return results


# ═════════════════════════════════════════════════════════════════════
# FREE SOURCES
# ═════════════════════════════════════════════════════════════════════

def scrape_tenderdetail():
    results = []
    log.info("--- TenderDetail (FREE) ---")
    URLS = [
        "https://www.tenderdetail.com/Indian-tender/e-learning-content-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/e-learning-tenders",
        "https://www.tenderdetail.com/Indian-tender/elearning-tenders",
        "https://www.tenderdetail.com/Indian-tender/lms-tenders",
        "https://www.tenderdetail.com/Indian-tender/learning-management-system-tenders",
        "https://www.tenderdetail.com/Indian-tender/immersive-tenders-tenders",
        "https://www.tenderdetail.com/Indian-tender/virtual-reality-tenders",
        "https://www.tenderdetail.com/Indian-tender/augmented-reality-tenders",
        "https://www.tenderdetail.com/Indian-tender/igot-tenders",
        "https://www.tenderdetail.com/Indian-tender/karmayogi-tenders",
        "https://www.tenderdetail.com/Indian-tender/instructional-design-tenders",
        "https://www.tenderdetail.com/Indian-tender/storyboarding-tenders",
        "https://www.tenderdetail.com/Indian-tender/digital-learning-tenders",
        "https://www.tenderdetail.com/Indian-tender/online-training-tenders",
        "https://www.tenderdetail.com/Indian-tender/simulation-training-tenders",
        "https://www.tenderdetail.com/Indian-tender/courseware-tenders",
        "https://www.tenderdetail.com/Indian-tender/content-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/loan-origination-system-tenders",
        "https://www.tenderdetail.com/Indian-tender/insurance-software-tenders",
        # Additional TenderDetail categories
        "https://www.tenderdetail.com/Indian-tender/e-for-e-learning-content-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/learning-management-system-lms-tenders",
        "https://www.tenderdetail.com/Indian-tender/skill-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/capacity-building-tenders",
        "https://www.tenderdetail.com/Indian-tender/training-tenders",
        "https://www.tenderdetail.com/Indian-tender/animation-tenders",
        "https://www.tenderdetail.com/Indian-tender/software-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/ar-vr-tenders",
    ]
    seen = set()
    for url in URLS:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        items = (
            soup.find_all("div", class_=lambda c: c and "tender" in str(c).lower()) or
            soup.find_all("tr") or
            soup.find_all("li")
        )
        for item in items[:30]:
            t = item.get_text(" ", strip=True)
            a = item.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tenderdetail.com" + link
            key = t[:80].lower()
            if len(t) > 20 and key not in seen:
                seen.add(key)
                results.append(make(t, link, "TenderDetail"))
        time.sleep(1)
    log.info(f"TenderDetail: {len(results)}")
    return results


def scrape_google_news_rss():
    results = []
    log.info("--- Google News RSS (FREE) ---")
    QUERIES = [
        "igot karmayogi e-learning tender India",
        "e-learning content development government tender India",
        "LMS learning management system tender India 2026",
        "AR VR immersive learning government tender India",
        "digital learning solutions government tender India",
        "storyboarding instructional design tender India",
        "loan origination system tender India 2026",
        "BFSI insurance software tender government India",
        "elearning courseware government bid India",
        "virtual reality simulation training tender India",
    ]
    for query in QUERIES:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        r = get(url, headers=RSS_HEADERS, timeout=15)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            if not channel:
                continue
            for item in channel.findall("item")[:10]:
                title   = (item.find("title").text   or "") if item.find("title")   is not None else ""
                link    = (item.find("link").text    or "") if item.find("link")    is not None else ""
                desc    = (item.find("description").text or "") if item.find("description") is not None else ""
                pubdate = (item.find("pubDate").text  or "") if item.find("pubDate")  is not None else ""
                if pubdate:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pubdate).replace(tzinfo=None)
                        if pub_dt < datetime.now() - timedelta(days=7):
                            continue
                    except:
                        pass
                if title and len(title) > 10:
                    t = make(f"{title} {desc}", link, "Google News")
                    t["title"] = title[:300]
                    results.append(t)
        except ET.ParseError:
            pass
        time.sleep(1)
    log.info(f"Google News RSS: {len(results)}")
    return results


def scrape_tendersontime():
    results = []
    log.info("--- TendersOnTime (FREE) ---")
    for url in [
        "https://www.tendersontime.com/indiaproducts/indian-e-learning-tenders-1546/",
        "https://www.tendersontime.com/indiaproducts/indian-learning-and-development-tenders-3920/",
    ]:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h3","h4","li","div"],
            class_=lambda c: c and "tender" in str(c).lower())[:30]:
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


def scrape_tenderdekho():
    results = []
    log.info("--- TenderDekho (FREE) ---")
    for kw in ["e-learning", "igot", "lms", "immersive"]:
        url = f"https://www.tenderdekho.com/tender/search.aspx?keyword={requests.utils.quote(kw)}"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["div","tr","li"],
            class_=lambda c: c and any(
                x in str(c).lower() for x in ["tender","result","bid"]
            ))[:20]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tenderdekho.com" + link
            if len(t) > 20:
                results.append(make(t, link, "TenderDekho"))
        time.sleep(1)
    log.info(f"TenderDekho: {len(results)}")
    return results


def scrape_duckduckgo():
    results = []
    log.info("--- DuckDuckGo (FREE) ---")
    QUERIES = [
        "igot karmayogi e-learning content development tender 2026 India",
        "LMS learning management system government tender India 2026",
        "AR VR immersive learning government tender India 2026",
        "storyboarding instructional design government tender India 2026",
        "digital learning solutions government tender India 2026",
        "loan origination system LOS government tender India 2026",
        "BFSI insurance software tender government India 2026",
        "simulation based training vr tender India 2026",
    ]
    for q in QUERIES:
        r = get("https://html.duckduckgo.com/html/",
                post_data={"q": q, "kl": "in-en"}, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for res in soup.find_all("div", class_="result__body")[:5]:
            ta = res.find("a", class_="result__a")
            ts = res.find("a", class_="result__snippet")
            title   = ta.get_text(strip=True) if ta else ""
            link    = ta["href"] if ta and ta.has_attr("href") else ""
            snippet = ts.get_text(strip=True) if ts else ""
            if len(title) > 10:
                t = make(f"{title} {snippet}", link, "DuckDuckGo Search")
                t["title"] = title[:300]
                results.append(t)
        time.sleep(2)
    log.info(f"DuckDuckGo: {len(results)}")
    return results




# ═════════════════════════════════════════════════════════════════════
# NEW SOURCES — v11
# ═════════════════════════════════════════════════════════════════════

def scrape_tendersinfo():
    results = []
    log.info("--- TendersInfo ---")
    urls = [
        "https://www.tendersinfo.com/global-e-learning-tenders.php",
        "https://www.tendersinfo.com/global-lms-tenders.php",
        "https://www.tendersinfo.com/global-igot-tenders.php",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["tr","div","li"],
            class_=lambda c: c and any(
                x in str(c).lower() for x in ["tender","result","bid","row"]
            ))[:30]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tendersinfo.com" + link
            if len(t) > 20:
                results.append(make(t, link, "TendersInfo"))
        # Also try table rows
        for row in soup.find_all("tr")[:40]:
            cols = row.find_all("td")
            if len(cols) >= 2:
                t = " ".join(c.get_text(" ", strip=True) for c in cols)
                a = row.find("a", href=True)
                link = a["href"] if a else url
                if not link.startswith("http"):
                    link = "https://www.tendersinfo.com" + link
                if len(t) > 20:
                    results.append(make(t, link, "TendersInfo"))
        time.sleep(1.5)
    log.info(f"TendersInfo: {len(results)}")
    return results


def scrape_tender247():
    results = []
    log.info("--- Tender247 ---")
    urls = [
        "https://www.tender247.com/keyword/e-learning+Tenders",
        "https://www.tender247.com/keyword/igot+Tenders",
        "https://www.tender247.com/keyword/lms+Tenders",
        "https://www.tender247.com/keyword/learning+management+system+Tenders",
        "https://www.tender247.com/keyword/ar+vr+Tenders",
        "https://www.tender247.com/keyword/immersive+learning+Tenders",
        "https://www.tender247.com/keyword/content+development+Tenders",
        "https://www.tender247.com/keyword/storyboarding+Tenders",
        "https://www.tender247.com/keyword/instructional+design+Tenders",
        "https://www.tender247.com/keyword/elearning+Tenders",
    ]
    seen = set()
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        # Tender247 uses table rows
        for row in soup.find_all("tr")[:30]:
            cols = row.find_all("td")
            if len(cols) >= 2:
                t = " ".join(c.get_text(" ", strip=True) for c in cols)
                a = row.find("a", href=True)
                link = a["href"] if a else url
                if not link.startswith("http"):
                    link = "https://www.tender247.com" + link
                key = t[:60].lower()
                if len(t) > 20 and key not in seen:
                    seen.add(key)
                    results.append(make(t, link, "Tender247"))
        # Also try div/li
        for tag in soup.find_all(["div","li"],
            class_=lambda c: c and any(
                x in str(c).lower() for x in ["tender","result","list","item"]
            ))[:20]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tender247.com" + link
            key = t[:60].lower()
            if len(t) > 20 and key not in seen:
                seen.add(key)
                results.append(make(t, link, "Tender247"))
        time.sleep(1.5)
    log.info(f"Tender247: {len(results)}")
    return results


def scrape_biddetail():
    results = []
    log.info("--- BidDetail ---")
    urls = [
        "https://www.biddetail.com/global-tenders/e-learning-tenders",
        "https://www.biddetail.com/global-tenders/lms-tenders",
        "https://www.biddetail.com/global-tenders/igot-tenders",
        "https://www.biddetail.com/global-tenders/immersive-learning-tenders",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["div","tr","li","article"],
            class_=lambda c: c and any(
                x in str(c).lower() for x in ["tender","result","bid","item","row"]
            ))[:30]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.biddetail.com" + link
            if len(t) > 20:
                results.append(make(t, link, "BidDetail"))
        time.sleep(1.5)
    log.info(f"BidDetail: {len(results)}")
    return results


def scrape_tenderkart():
    results = []
    log.info("--- TenderKart ---")
    urls = [
        "https://tenderkart.in/tenders?q=e-learning",
        "https://tenderkart.in/tenders?q=igot",
        "https://tenderkart.in/tenders?q=lms",
        "https://tenderkart.in/tenders?q=immersive+learning",
        "https://tenderkart.in/tenders?q=content+development",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["div","li","tr","article"],
            class_=lambda c: c and any(
                x in str(c).lower() for x in ["tender","result","bid","card","item"]
            ))[:20]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://tenderkart.in" + link
            if len(t) > 20:
                results.append(make(t, link, "TenderKart"))
        time.sleep(1.5)
    log.info(f"TenderKart: {len(results)}")
    return results


def scrape_tendersniper():
    results = []
    log.info("--- TenderSniper ---")
    urls = [
        "https://tendersniper.com/search/index.xhtml?keyword=e-learning",
        "https://tendersniper.com/search/index.xhtml?keyword=igot",
        "https://tendersniper.com/search/index.xhtml?keyword=lms",
        "https://tendersniper.com/search/index.xhtml?keyword=immersive+learning",
        "https://tendersniper.com/search/index.xhtml?keyword=content+development",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["div","tr","li"],
            class_=lambda c: c and any(
                x in str(c).lower() for x in ["tender","result","bid","row","item"]
            ))[:20]:
            t = tag.get_text(" ", strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://tendersniper.com" + link
            if len(t) > 20:
                results.append(make(t, link, "TenderSniper"))
        time.sleep(1.5)
    log.info(f"TenderSniper: {len(results)}")
    return results


def scrape_istm_direct():
    results = []
    log.info("--- ISTM Direct ---")
    urls = [
        "https://www.istm.gov.in/home/course_tender",
        "https://www.istm.gov.in/home/other_tender",
    ]
    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["a","li","td","div","tr"]):
            t = tag.get_text(" ", strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://www.istm.gov.in" + link
            if len(t) > 20:
                results.append(make(t, link, "ISTM ★"))
        time.sleep(1.5)
    log.info(f"ISTM Direct: {len(results)}")
    return results

# ─────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────
def render_card(t):
    color    = SOURCE_COLOR.get(t["source"], "#555")
    is_govt  = t["source"] in GOVT_SOURCES
    title    = t.get("title","N/A")[:220]
    link     = t.get("link","#")
    bid_id   = t.get("tender_no","N/A")
    dept     = t.get("department","N/A")
    value    = t.get("value","N/A")
    deadline = t.get("deadline","N/A")
    kws      = " · ".join(t.get("hits",[])[:6])
    src      = t["source"]

    govt_tag = ' <span style="font-size:9px;background:#ffd600;color:#000;padding:1px 6px;border-radius:4px;font-weight:bold;">GOVT</span>' if is_govt else ""

    def fbox(icon, label, val, bg="#f5f5f5", fg="#333"):
        return f"""<td style="padding:8px 10px;background:{bg};border-radius:5px;
            vertical-align:top;width:46%;">
          <div style="font-size:9px;color:#999;margin-bottom:3px;
              text-transform:uppercase;">{icon} {label}</div>
          <div style="font-size:12px;font-weight:bold;color:{fg};">{val}</div>
        </td>"""

    return f"""
    <tr><td style="padding:16px 18px;border-bottom:3px solid #e8eaf6;">
      <div style="margin-bottom:8px;">
        <span style="background:{color};color:#fff;padding:3px 10px;
            border-radius:10px;font-size:10px;font-weight:bold;">{src}</span>{govt_tag}
      </div>
      <a href="{link}" style="color:#1a237e;font-weight:bold;font-size:14px;
         text-decoration:none;line-height:1.5;display:block;margin-bottom:14px;">{title}</a>
      <table style="width:100%;border-collapse:separate;border-spacing:0;">
        <tr>
          {fbox("🔖","Bid ID / Tender No", bid_id)}
          <td style="width:8%;"></td>
          {fbox("🏢","Department", dept)}
        </tr>
        <tr><td colspan="3" style="height:8px;"></td></tr>
        <tr>
          {fbox("💰","Estimated Value", value,"#e8f5e9","#2e7d32")}
          <td style="width:8%;"></td>
          {fbox("⏰","Submission Deadline", deadline,"#fff3e0","#e65100")}
        </tr>
      </table>
      <div style="margin-top:10px;font-size:10px;color:#bbb;">🔑 {kws or "—"}</div>
    </td></tr>"""


def send_email(tenders):
    if not SMTP_USER or not SMTP_PASS:
        log.error("SMTP credentials missing")
        return

    date_str = datetime.now().strftime("%d %b %Y %I:%M %p")
    govt = [t for t in tenders if t["source"] in GOVT_SOURCES]
    agg  = [t for t in tenders if t["source"] not in GOVT_SOURCES]

    def section(items, heading, bg):
        if not items:
            return ""
        by_src = {}
        for t in items:
            by_src.setdefault(t["source"],[]).append(t)
        html = f"""<tr><td style="background:{bg};color:#fff;padding:10px 18px;
            font-size:13px;font-weight:bold;">{heading} ({len(items)})</td></tr>"""
        for src, sitems in by_src.items():
            c = SOURCE_COLOR.get(src,"#555")
            html += f"""<tr><td style="background:{c};color:#fff;
                padding:5px 18px;font-size:11px;font-weight:bold;">
                {src} — {len(sitems)} tender(s)</td></tr>"""
            for t in sitems:
                html += render_card(t)
        return html

    rows  = section(govt, "🏛️ DIRECT GOVT PORTALS", "#1a237e")
    rows += section(agg,  "📋 AGGREGATOR / SEARCH",  "#37474f")

    google_status = "✅ Google Search API Active" if GOOGLE_API_KEY else "⚠️ Google Search API not configured"

    html = f"""<!DOCTYPE html><html><body
    style="font-family:Arial,sans-serif;background:#ececec;margin:0;padding:16px;">
    <div style="max-width:700px;margin:auto;background:#fff;border-radius:10px;
         overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.15);">
      <div style="background:linear-gradient(135deg,#1a237e,#0d47a1);
           padding:22px 24px;color:#fff;">
        <h2 style="margin:0;font-size:20px;">🔔 Tender Alert — {len(tenders)} New Match(es)</h2>
        <p style="margin:6px 0 0;color:#bbdefb;font-size:12px;">
          {date_str} IST &nbsp;|&nbsp; {len(govt)} Govt · {len(agg)} Other
        </p>
      </div>
      <div style="padding:8px 18px;background:#e8eaf6;font-size:10px;
           color:#3949ab;line-height:2;">
        {google_status}<br>
        🏛️ GeM · CPPP · eTenders · ISTM Direct<br>
        📋 TenderDetail (27 URLs) · TendersInfo · Tender247 · BidDetail ·
        TenderKart · TenderSniper · TendersOnTime · Google News · DuckDuckGo
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <tbody>{rows}</tbody>
      </table>
      <div style="padding:12px 18px;background:#f5f5f5;font-size:10px;
           color:#bbb;border-top:1px solid #eee;text-align:center;">
        Novac Technology Solutions — Tender Monitor v11 &nbsp;|&nbsp;
        GitHub Actions · Free · Every 3 Hours
      </div>
    </div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Tender Alert] {len(tenders)} tender(s) | {len(govt)} Govt · {len(agg)} Other | {date_str}"
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
    log.info("Tender Monitor v11 — Maximum Free Coverage")
    log.info(f"Google API: {'✅ ACTIVE' if GOOGLE_API_KEY else '❌ NOT SET'}")
    log.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    conn    = init_db()
    all_raw = []

    # Free sources — always run
    all_raw += scrape_tenderdetail()      # 27 category URLs
    all_raw += scrape_google_news_rss()   # Google News RSS
    all_raw += scrape_tendersontime()     # TendersOnTime
    all_raw += scrape_tenderdekho()       # TenderDekho
    all_raw += scrape_duckduckgo()        # DuckDuckGo Search

    # NEW v11 sources
    all_raw += scrape_tendersinfo()       # TendersInfo
    all_raw += scrape_tender247()         # Tender247
    all_raw += scrape_biddetail()         # BidDetail
    all_raw += scrape_tenderkart()        # TenderKart
    all_raw += scrape_tendersniper()      # TenderSniper
    all_raw += scrape_istm_direct()       # ISTM Direct

    # Google Custom Search API
    all_raw += scrape_google_custom_search()

    log.info(f"Total scraped: {len(all_raw)}")

    matched = []
    for t in all_raw:
        hit, hits = matches(t)
        if hit:
            t["hits"] = hits
            matched.append(t)
    log.info(f"Keyword matched: {len(matched)}")

    fresh = [t for t in matched if is_recent(t)]
    log.info(f"Fresh (not expired): {len(fresh)}")

    new_ones = [t for t in fresh if is_new(conn, t)]
    conn.close()
    log.info(f"New (unseen 24h): {len(new_ones)}")

    if new_ones:
        send_email(new_ones)
    else:
        log.info("No new tenders — no email sent ✓")

    log.info("Run complete.")


if __name__ == "__main__":
    main()
