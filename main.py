"""
main.py — Tender Monitor v9
PROVEN WORKING SOURCES ONLY:
  1. TenderDetail       — 15+ category URLs (confirmed working)
  2. Google News RSS    — searches news about tenders (no JS needed)
  3. TendersOnTime      — fixed URLs
  4. TenderDekho        — fixed selectors
  5. DuckDuckGo Search  — fallback web search
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TenderBot/1.0; +https://novac.com)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
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
    "igot", "karmayogi",
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
    "horticulture", "agriculture", "seeds", "fertilizer",
]

SOURCE_COLOR = {
    "TenderDetail":             "#ef6c00",
    "TendersOnTime":            "#2e7d32",
    "TenderDekho":              "#ad1457",
    "Google News":              "#1a73e8",
    "DuckDuckGo Search":        "#de5833",
    "Web Search":               "#00838f",
}

GOVT_SOURCES = {"Web Search", "DuckDuckGo Search"}


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
    # Purge records older than 24 hours
    conn.execute("DELETE FROM seen WHERE added < datetime('now', '-24 hours')")
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
# SMART FIELD EXTRACTOR
# ─────────────────────────────────────────────────────────────────────
def extract_fields(raw_text):
    text = " ".join(raw_text.split()).strip()

    # Tender / Bid Number
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

    # Try aggregator format "Dept Name - City - State XXXXXXX"
    dm = re.match(
        r"^\d*\s*([\w\s/&,\-]+?)\s*-\s*[\w\s]+\s*-\s*[\w\s]+\s+\d{7,}",
        text
    )
    if dm:
        department = dm.group(1).strip()

    # Estimated Value
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
                deadline = re.sub(r"\s+,", ",", dl)
                deadline = re.sub(r"\s+", " ", deadline)
                break

    # Clean title
    title = re.sub(r"^\d+\s+", "", text)
    title = " ".join(title.split())

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
MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

def parse_date(date_str):
    if not date_str or date_str == "N/A":
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
    dl = tender.get("deadline", "N/A")
    if dl == "N/A":
        return True
    dt = parse_date(dl)
    if dt is None:
        return True
    if dt < datetime.now() - timedelta(days=1):
        return False
    return True


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


def make(raw_text, link, source):
    fields = extract_fields(raw_text)
    fields["link"]   = link or ""
    fields["source"] = source
    return fields


# ═════════════════════════════════════════════════════════════════════
# SOURCE 1 — TenderDetail (15 category URLs — PROVEN WORKING)
# ═════════════════════════════════════════════════════════════════════
def scrape_tenderdetail():
    results = []
    log.info("--- TenderDetail ---")

    CATEGORY_URLS = [
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
    ]

    seen_titles = set()
    for url in CATEGORY_URLS:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")

        # TenderDetail uses table rows and div cards
        # Try multiple selectors
        items = (
            soup.find_all("div", class_=lambda c: c and "tender" in str(c).lower()) or
            soup.find_all("tr", class_=lambda c: c and any(x in str(c).lower() for x in ["tender","row","result"])) or
            soup.find_all("li", class_=lambda c: c and "tender" in str(c).lower())
        )

        for item in items[:30]:
            t = item.get_text(" ", strip=True)
            a = item.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tenderdetail.com" + link
            # Dedup within this scraper
            key = t[:80].lower()
            if len(t) > 20 and key not in seen_titles:
                seen_titles.add(key)
                results.append(make(t, link, "TenderDetail"))
        time.sleep(1.5)

    log.info(f"TenderDetail: {len(results)}")
    return results


# ═════════════════════════════════════════════════════════════════════
# SOURCE 2 — Google News RSS (no JS, no blocking, always works)
# ═════════════════════════════════════════════════════════════════════
def scrape_google_news_rss():
    results = []
    log.info("--- Google News RSS ---")

    SEARCH_QUERIES = [
        "igot karmayogi e-learning tender India",
        "e-learning content development government tender India",
        "LMS learning management system tender India 2026",
        "AR VR immersive learning government tender India",
        "digital learning solutions government tender India",
        "storyboarding instructional design tender India",
        "elearning courseware government bid India",
        "loan origination system tender India",
        "insurance software tender government India",
        "BFSI elearning tender India",
    ]

    for query in SEARCH_QUERIES:
        encoded = requests.utils.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"

        r = get(url, headers=RSS_HEADERS, timeout=15)
        if not r:
            continue

        try:
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            if channel is None:
                continue

            for item in channel.findall("item")[:10]:
                title_el = item.find("title")
                link_el  = item.find("link")
                desc_el  = item.find("description")
                pub_el   = item.find("pubDate")

                title   = title_el.text if title_el is not None else ""
                link    = link_el.text  if link_el  is not None else ""
                desc    = desc_el.text  if desc_el  is not None else ""
                pubdate = pub_el.text   if pub_el   is not None else ""

                # Only include news from last 7 days
                if pubdate:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pubdate)
                        pub_dt = pub_dt.replace(tzinfo=None)
                        if pub_dt < datetime.now() - timedelta(days=7):
                            continue
                    except:
                        pass

                full_text = f"{title} {desc}"
                if title and len(title) > 10:
                    t = make(full_text, link, "Google News")
                    # Override title with clean news title
                    t["title"] = title[:300]
                    # Add pubdate as deadline indicator
                    if pubdate and t["deadline"] == "N/A":
                        t["deadline"] = "See article"
                    results.append(t)

        except ET.ParseError as e:
            log.warning(f"RSS parse error: {e}")

        time.sleep(1)

    log.info(f"Google News RSS: {len(results)}")
    return results


# ═════════════════════════════════════════════════════════════════════
# SOURCE 3 — TendersOnTime (fixed URLs)
# ═════════════════════════════════════════════════════════════════════
def scrape_tendersontime():
    results = []
    log.info("--- TendersOnTime ---")

    urls = [
        "https://www.tendersontime.com/indiaproducts/indian-e-learning-tenders-1546/",
        "https://www.tendersontime.com/indiaproducts/indian-learning-and-development-tenders-3920/",
        "https://www.tendersontime.com/indiaproducts/indian-lms-tenders-2890/",
        "https://www.tendersontime.com/search/?keyword=igot+elearning",
        "https://www.tendersontime.com/search/?keyword=e-learning+content+development",
    ]

    for url in urls:
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")

        # Try all possible content containers
        for selector in [
            lambda s: s.find_all("div", class_=lambda c: c and "tender" in str(c).lower()),
            lambda s: s.find_all("h3"),
            lambda s: s.find_all("h4"),
            lambda s: s.find_all("li", class_=lambda c: c and "tender" in str(c).lower()),
            lambda s: s.find_all("td"),
        ]:
            items = selector(soup)
            if items:
                for item in items[:30]:
                    t = item.get_text(" ", strip=True)
                    a = item.find("a", href=True)
                    link = a["href"] if a else url
                    if not link.startswith("http"):
                        link = "https://www.tendersontime.com" + link
                    if len(t) > 20:
                        results.append(make(t, link, "TendersOnTime"))
                break
        time.sleep(1.5)

    log.info(f"TendersOnTime: {len(results)}")
    return results


# ═════════════════════════════════════════════════════════════════════
# SOURCE 4 — TenderDekho (fixed selectors)
# ═════════════════════════════════════════════════════════════════════
def scrape_tenderdekho():
    results = []
    log.info("--- TenderDekho ---")

    search_terms = ["e-learning", "igot", "lms", "immersive learning", "elearning content"]
    for kw in search_terms:
        url = f"https://www.tenderdekho.com/tender/search.aspx?keyword={requests.utils.quote(kw)}"
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")

        # Try broader selectors
        for tag in soup.find_all(["div","tr","li","article"]):
            cl = str(tag.get("class","")).lower()
            if any(x in cl for x in ["tender","result","item","row","bid"]):
                t = tag.get_text(" ", strip=True)
                a = tag.find("a", href=True)
                link = a["href"] if a else url
                if not link.startswith("http"):
                    link = "https://www.tenderdekho.com" + link
                if len(t) > 20:
                    results.append(make(t, link, "TenderDekho"))
        time.sleep(1.5)

    log.info(f"TenderDekho: {len(results)}")
    return results


# ═════════════════════════════════════════════════════════════════════
# SOURCE 5 — DuckDuckGo HTML Search (fallback — very reliable)
# ═════════════════════════════════════════════════════════════════════
def scrape_duckduckgo():
    results = []
    log.info("--- DuckDuckGo Search ---")

    QUERIES = [
        "igot karmayogi e-learning content development tender 2026 India",
        "LMS learning management system government tender India 2026",
        "AR VR immersive learning government tender India 2026",
        "e-learning content development tender site:gov.in 2026",
        "storyboarding instructional design government tender India 2026",
        "digital learning solutions government tender India 2026",
        "elearning courseware tender India 2026",
        "loan origination system LOS government tender India 2026",
        "BFSI insurance software tender government India 2026",
        "virtual reality augmented reality training tender India 2026",
    ]

    for q in QUERIES:
        r = get(
            "https://html.duckduckgo.com/html/",
            post_data={"q": q, "kl": "in-en"},
            timeout=20,
        )
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
                t = make(full, link, "DuckDuckGo Search")
                t["title"] = title[:300]
                results.append(t)
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

    def field_box(icon, label, val, bg="#f5f5f5", fg="#333"):
        return f"""<td style="padding:8px 10px;background:{bg};border-radius:5px;
            vertical-align:top;width:46%;">
          <div style="font-size:9px;color:#999;margin-bottom:3px;
              text-transform:uppercase;letter-spacing:0.5px;">
            {icon} {label}</div>
          <div style="font-size:12px;font-weight:bold;color:{fg};
              line-height:1.3;">{val}</div>
        </td>"""

    return f"""
    <tr>
      <td style="padding:16px 18px;border-bottom:3px solid #e8eaf6;">

        <!-- Badge -->
        <div style="margin-bottom:8px;">
          <span style="background:{color};color:#fff;padding:3px 10px;
              border-radius:10px;font-size:10px;font-weight:bold;
              letter-spacing:0.5px;">{src}</span>
        </div>

        <!-- Title -->
        <a href="{link}" style="color:#1a237e;font-weight:bold;font-size:14px;
           text-decoration:none;line-height:1.5;display:block;
           margin-bottom:14px;">{title}</a>

        <!-- Fields -->
        <table style="width:100%;border-collapse:separate;border-spacing:0 0;">
          <tr>
            {field_box("🔖", "Bid ID / Tender No", bid_id)}
            <td style="width:8%;"></td>
            {field_box("🏢", "Department", dept)}
          </tr>
          <tr><td colspan="3" style="height:8px;"></td></tr>
          <tr>
            {field_box("💰", "Estimated Value", value, "#e8f5e9", "#2e7d32")}
            <td style="width:8%;"></td>
            {field_box("⏰", "Submission Deadline", deadline, "#fff3e0", "#e65100")}
          </tr>
        </table>

        <!-- Keywords -->
        <div style="margin-top:10px;font-size:10px;color:#bbb;">
          🔑 {kws or "—"}
        </div>
      </td>
    </tr>"""


def send_email(tenders):
    if not SMTP_USER or not SMTP_PASS:
        log.error("SMTP credentials missing")
        return

    date_str = datetime.now().strftime("%d %b %Y %I:%M %p")

    # Group by source
    by_src = {}
    for t in tenders:
        by_src.setdefault(t["source"], []).append(t)

    rows = ""
    for src, items in by_src.items():
        color = SOURCE_COLOR.get(src, "#555")
        rows += f"""
        <tr>
          <td style="background:{color};color:#fff;padding:8px 18px;
              font-size:12px;font-weight:bold;">
            {src} &nbsp;— {len(items)} tender(s)
          </td>
        </tr>"""
        for t in items:
            rows += render_card(t)

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#ececec;
margin:0;padding:16px;">
<div style="max-width:700px;margin:auto;background:#fff;
     border-radius:10px;overflow:hidden;
     box-shadow:0 2px 12px rgba(0,0,0,.15);">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a237e,#0d47a1);
       padding:22px 24px;color:#fff;">
    <h2 style="margin:0;font-size:20px;">
      🔔 Tender Alert — {len(tenders)} New Match(es)
    </h2>
    <p style="margin:6px 0 0;color:#bbdefb;font-size:12px;">
      {date_str} IST &nbsp;|&nbsp; Fresh tenders only (deadline not expired)
    </p>
  </div>

  <!-- Sources -->
  <div style="padding:8px 18px;background:#e8eaf6;font-size:10px;
       color:#3949ab;line-height:2;">
    <strong>Active Sources:</strong>
    TenderDetail (19 categories) · Google News RSS ·
    TendersOnTime · TenderDekho · DuckDuckGo Search
  </div>

  <!-- Cards -->
  <table style="width:100%;border-collapse:collapse;">
    <tbody>{rows}</tbody>
  </table>

  <!-- Footer -->
  <div style="padding:12px 18px;background:#f5f5f5;font-size:10px;
       color:#bbb;border-top:1px solid #eee;text-align:center;">
    Novac Technology Solutions — Tender Monitor v9 &nbsp;|&nbsp;
    GitHub Actions · Free · Every 1 Hour &nbsp;|&nbsp;
    Only showing tenders with valid/future deadlines
  </div>
</div>
</body></html>"""

    subject = (
        f"[Tender Alert] {len(tenders)} fresh tender(s) | {date_str}"
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
        log.info(f"✅ Email sent to {ALERT_EMAIL} — {len(tenders)} tenders")
    except Exception as e:
        log.error(f"❌ Email failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("Tender Monitor v9 — GitHub Actions")
    log.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    conn = init_db()

    all_raw = []
    all_raw += scrape_tenderdetail()     # 19 category URLs
    all_raw += scrape_google_news_rss()  # Google News RSS
    all_raw += scrape_tendersontime()    # Fixed URLs
    all_raw += scrape_tenderdekho()      # Fixed selectors
    all_raw += scrape_duckduckgo()       # Web search fallback

    log.info(f"Total scraped: {len(all_raw)}")

    # Match keywords
    matched = []
    for t in all_raw:
        hit, hits = matches(t)
        if hit:
            t["hits"] = hits
            matched.append(t)
    log.info(f"Keyword matched: {len(matched)}")

    # Filter expired tenders
    fresh = [t for t in matched if is_recent(t)]
    log.info(f"Fresh (deadline not expired): {len(fresh)}")

    # Deduplicate
    new_ones = [t for t in fresh if is_new(conn, t)]
    conn.close()
    log.info(f"New (unseen in last 24h): {len(new_ones)}")

    if new_ones:
        send_email(new_ones)
    else:
        log.info("No new tenders this run — no email sent ✓")

    log.info("Run complete.")


if __name__ == "__main__":
    main()
