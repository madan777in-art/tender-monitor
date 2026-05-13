"""
main.py — Tender Monitor for GitHub Actions
GitHub Actions calls this once per run. No while-loop needed.
Scrapes all sources → matches keywords → emails new tenders only.
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
    "e-learning", "elearning", "e learning",
    "igot", "iGOT", "karmayogi",
    "lms", "learning management system",
    "ar/vr", "ar vr", "augmented reality", "virtual reality",
    "immersive", "immersive learning",
    "content development", "content design",
    "storyboarding", "instructional design",
    "digital learning", "digital content",
    "online training", "online learning",
    "courseware", "scorm", "multimedia content",
    "simulation training", "animation training",
    "2d animation", "explainer video",
    "rapid authoring", "mobile learning",
]

EXCLUDE = [
    "hand pump", "solar panel", "fodder", "road", "civil works",
    "plumbing", "electrical wiring", "furniture", "vehicle",
    "generator", "pump", "valve", "borewell",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ─────────────────────────────────────────────────────────────────────
# DATABASE — deduplication
# ─────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            hash TEXT PRIMARY KEY,
            title TEXT,
            source TEXT,
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def is_new(conn, tender):
    raw  = (tender.get("title","") + tender.get("link","")).lower().strip()
    h    = hashlib.md5(raw.encode()).hexdigest()
    row  = conn.execute("SELECT hash FROM seen WHERE hash=?", (h,)).fetchone()
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
# SCRAPERS
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
        log.warning(f"FETCH FAILED [{url[:60]}]: {e}")
        return None


def scrape_tenderdetail():
    results = []
    urls = [
        "https://www.tenderdetail.com/Indian-tender/e-learning-content-development-tenders",
        "https://www.tenderdetail.com/Indian-tender/e-learning-tenders",
        "https://www.tenderdetail.com/Indian-tender/immersive-tenders-tenders",
    ]
    for url in urls:
        r = get(url)
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for div in soup.find_all("div", class_=lambda c: c and "tender" in str(c).lower())[:30]:
            t = div.get_text(" ", strip=True)[:300]
            a = div.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tenderdetail.com" + link
            if len(t) > 20:
                results.append({"title": t, "link": link, "source": "TenderDetail"})
        time.sleep(1)
    log.info(f"TenderDetail: {len(results)}")
    return results


def scrape_tendersontime():
    results = []
    urls = [
        "https://www.tendersontime.com/indiaproducts/indian-e-learning-tenders-1546/",
        "https://www.tendersontime.com/indiaproducts/indian-learning-and-development-tenders-3920/",
    ]
    for url in urls:
        r = get(url)
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h3","h4","li"])[:40]:
            t = tag.get_text(strip=True)
            a = tag.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.tendersontime.com" + link
            if len(t) > 20:
                results.append({"title": t, "link": link, "source": "TendersOnTime"})
        time.sleep(1)
    log.info(f"TendersOnTime: {len(results)}")
    return results


def scrape_bidassist():
    results = []
    for kw in ["e-learning content development", "igot tender", "lms government", "ar vr training"]:
        url = f"https://bidassist.com/tenders?q={requests.utils.quote(kw)}&country=India"
        r = get(url)
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.find_all("div", class_=lambda c: c and "tender" in str(c).lower())[:15]:
            t = card.get_text(" ", strip=True)[:300]
            a = card.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://bidassist.com" + link
            if len(t) > 20:
                results.append({"title": t, "link": link, "source": "BidAssist"})
        time.sleep(2)
    log.info(f"BidAssist: {len(results)}")
    return results


def scrape_nationaltenders():
    results = []
    for kw in ["e-learning", "igot", "lms", "immersive learning"]:
        url = f"https://www.nationaltenders.com/tender/search?q={requests.utils.quote(kw)}"
        r = get(url)
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all(["h2","h3","a"], class_=lambda c: c and "tender" in str(c).lower())[:20]:
            t = tag.get_text(strip=True)
            a = tag if tag.name == "a" else tag.find("a", href=True)
            link = a["href"] if a and a.has_attr("href") else url
            if not link.startswith("http"):
                link = "https://www.nationaltenders.com" + link
            if len(t) > 15:
                results.append({"title": t, "link": link, "source": "NationalTenders"})
        time.sleep(1)
    log.info(f"NationalTenders: {len(results)}")
    return results


def scrape_firsttender():
    results = []
    for kw in ["e-learning", "igot", "lms learning management"]:
        url = f"https://www.firsttender.com/tender/search-result.aspx?SearchFor={requests.utils.quote(kw)}"
        r = get(url)
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for td in soup.find_all("td")[:40]:
            t = td.get_text(strip=True)[:250]
            a = td.find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://www.firsttender.com" + link
            if len(t) > 20:
                results.append({"title": t, "link": link, "source": "FirstTender"})
        time.sleep(1)
    log.info(f"FirstTender: {len(results)}")
    return results


def scrape_cppp():
    results = []
    url = "https://eprocure.gov.in/eprocure/app"
    params = {
        "component": "$DirectLink",
        "page": "FrontEndLatestActiveTenders",
        "service": "direct",
    }
    r = get(url, params=params)
    if not r:
        log.warning("CPPP: not reachable")
        return results
    soup = BeautifulSoup(r.text, "lxml")
    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) >= 2:
            t = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            a = cols[1].find("a", href=True)
            link = a["href"] if a else url
            if not link.startswith("http"):
                link = "https://eprocure.gov.in" + link
            dept = cols[0].get_text(strip=True)
            if len(t) > 10:
                results.append({
                    "title": f"{t} [{dept}]",
                    "link": link,
                    "source": "CPPP / eProcure ★"
                })
    log.info(f"CPPP: {len(results)}")
    return results


def scrape_duckduckgo():
    results = []
    queries = [
        "igot karmayogi e-learning content development tender 2026",
        "LMS learning management system government tender India 2026",
        "AR VR immersive learning government tender India 2026",
        'site:gem.gov.in "e-learning" OR "igot" OR "lms" tender',
        'site:eprocure.gov.in "e-learning" OR "igot" OR "lms"',
    ]
    for q in queries:
        r = get("https://html.duckduckgo.com/html/", post_data={"q": q, "kl": "in-en"})
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for res in soup.find_all("div", class_="result__body")[:6]:
            title_tag   = res.find("a", class_="result__a")
            snippet_tag = res.find("a", class_="result__snippet")
            title   = title_tag.get_text(strip=True) if title_tag else ""
            link    = title_tag["href"] if title_tag and title_tag.has_attr("href") else ""
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            full    = f"{title} — {snippet}"
            if len(title) > 10:
                results.append({"title": full[:350], "link": link, "source": "Web Search (GeM/CPPP)"})
        time.sleep(2)
    log.info(f"DuckDuckGo: {len(results)}")
    return results


# ─────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────
SOURCE_COLOR = {
    "CPPP / eProcure ★":     "#4a148c",
    "Web Search (GeM/CPPP)": "#1a237e",
    "TenderDetail":          "#e65100",
    "TendersOnTime":         "#00695c",
    "BidAssist":             "#1565c0",
    "NationalTenders":       "#4e342e",
    "FirstTender":           "#37474f",
}
GOVT_SOURCES = {"CPPP / eProcure ★", "Web Search (GeM/CPPP)"}


def send_email(tenders):
    if not SMTP_USER or not SMTP_PASS:
        log.error("SMTP credentials missing — set GitHub Secrets SMTP_USER and SMTP_PASS")
        return

    date_str = datetime.now().strftime("%d %b %Y %I:%M %p")

    # Group by source
    by_src = {}
    for t in tenders:
        by_src.setdefault(t["source"], []).append(t)

    rows = ""
    for src, items in by_src.items():
        color = SOURCE_COLOR.get(src, "#555")
        label = f"★ GOVT — {src}" if src in GOVT_SOURCES else src
        rows += f"""
        <tr>
          <td colspan="2" style="background:{color};color:#fff;padding:8px 14px;
              font-weight:bold;font-size:13px;border-radius:4px 4px 0 0;">
            {label} &nbsp;({len(items)})
          </td>
        </tr>"""
        for t in items:
            kws = " · ".join(t.get("hits", []))
            rows += f"""
        <tr style="border-bottom:1px solid #eee;vertical-align:top;">
          <td style="padding:10px 14px;width:70%;">
            <a href="{t['link']}" style="color:#1a237e;font-weight:bold;
               font-size:13px;text-decoration:none;">{t['title'][:220]}</a>
          </td>
          <td style="padding:10px 8px;font-size:11px;color:#666;">{kws}</td>
        </tr>"""

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;
    background:#f0f0f0;margin:0;padding:16px;">
    <div style="max-width:720px;margin:auto;background:#fff;border-radius:10px;
         overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.12);">
      <div style="background:linear-gradient(135deg,#1a237e,#283593);
           padding:22px 28px;color:#fff;">
        <h2 style="margin:0;font-size:22px;">🔔 Tender Alert — {len(tenders)} New Match(es)</h2>
        <p style="margin:6px 0 0;color:#c5cae9;font-size:13px;">{date_str} IST</p>
      </div>
      <div style="padding:10px 20px;background:#e8eaf6;font-size:12px;color:#3949ab;">
        Sources: CPPP/eProcure ★ · GeM Web Search ★ · BidAssist · TendersOnTime ·
        TenderDetail · NationalTenders · FirstTender
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#fafafa;">
            <th style="padding:8px 14px;text-align:left;font-size:11px;
                color:#888;border-bottom:2px solid #eee;">TENDER</th>
            <th style="padding:8px 8px;text-align:left;font-size:11px;
                color:#888;border-bottom:2px solid #eee;">KEYWORDS HIT</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="padding:14px 20px;background:#f5f5f5;font-size:11px;color:#aaa;
           border-top:1px solid #eee;">
        Novac Technology Solutions — Tender Monitor | Powered by GitHub Actions (Free)
      </div>
    </div></body></html>"""

    subject = f"[Tender Alert] {len(tenders)} new tender(s) — {date_str}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = ALERT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        log.info(f"✅ Email sent → {ALERT_EMAIL}")
    except Exception as e:
        log.error(f"❌ Email failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("Tender Monitor — GitHub Actions Run")
    log.info("=" * 55)

    conn = init_db()

    # Collect from all sources
    all_raw = []
    all_raw += scrape_tenderdetail()
    all_raw += scrape_tendersontime()
    all_raw += scrape_bidassist()
    all_raw += scrape_nationaltenders()
    all_raw += scrape_firsttender()
    all_raw += scrape_cppp()
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

    log.info("Run complete.")


if __name__ == "__main__":
    main()
