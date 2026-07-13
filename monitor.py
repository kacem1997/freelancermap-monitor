"""
freelancermap.de Projekt-Monitor
Fetcht neue Projekte und sendet E-Mail-Benachrichtigung.
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

SEARCH_URL = (
    "https://www.freelancermap.de/projekte"
    "?categories%5B0%5D=8&categories%5B1%5D=9&categories%5B2%5D=11"
    "&projectContractTypes%5B0%5D=contracting"
    "&remoteInPercent%5B0%5D=1&remoteInPercent%5B1%5D=100"
    "&query=%28%22data+analyst%22+OR+%22datenanalyst%22+OR+%22data+analytics%22"
    "+OR+%22datenanalyse%22+OR+%22power+bi%22+OR+%22data+science%22"
    "+OR+%22data+migration%22+OR+%22databricks%22%29"
    "&countries%5B%5D=%5B%5D&continents%5B0%5D=-1&sort=1&pagenr=1"
)

SEEN_FILE = "seen_postings.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Fetch & Parse
# ---------------------------------------------------------------------------

def fetch_html() -> str:
    resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_id(href: str) -> str:
    """Extrahiert die numerische ID aus /projekt/titel-12345."""
    match = re.search(r"-(\d+)$", href)
    return match.group(1) if match else href.split("/")[-1]


def parse_postings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    postings = []
    seen_ids: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"^/projekt/")):
        href = a["href"]
        project_id = extract_id(href)

        if project_id in seen_ids:
            continue
        seen_ids.add(project_id)

        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        postings.append({
            "id": project_id,
            "title": title,
            "url": f"https://www.freelancermap.de{href}",
        })

    return postings


# ---------------------------------------------------------------------------
# Seen-Liste
# ---------------------------------------------------------------------------

def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set[str]) -> None:
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


# ---------------------------------------------------------------------------
# E-Mail
# ---------------------------------------------------------------------------

def build_html(postings: list[dict]) -> str:
    rows = "".join(
        f'<tr>'
        f'<td style="padding:10px 4px;border-bottom:1px solid #f0f0f0;font-size:14px;">'
        f'<a href="{p["url"]}" style="color:#1a73e8;text-decoration:none;font-weight:500;">'
        f'{p["title"]}'
        f'</a>'
        f'</td>'
        f'</tr>'
        for p in postings
    )
    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:0 auto;padding:20px;">
      <h2 style="color:#1a73e8;margin-bottom:4px;">
        🔔 {len(postings)} neue Projekt{'e' if len(postings) != 1 else ''} auf freelancermap.de
      </h2>
      <p style="color:#666;font-size:13px;margin-top:0;">
        {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC
      </p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        {rows}
      </table>
      <div style="margin-top:20px;padding-top:16px;border-top:1px solid #eee;">
        <a href="https://www.freelancermap.de/projekte"
           style="background:#1a73e8;color:#fff;padding:10px 20px;
                  border-radius:4px;text-decoration:none;font-size:13px;">
          Alle Projekte ansehen →
        </a>
      </div>
      <p style="color:#bbb;font-size:11px;margin-top:20px;">
        Automatisch generiert via GitHub Actions
      </p>
    </body>
    </html>
    """


def send_email(postings: list[dict]) -> None:
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", smtp_user)
    smtp_host = os.environ.get("SMTP_HOST", "smtp-mail.outlook.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    count = len(postings)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔔 {count} neue Freelancermap-Projekt{'e' if count != 1 else ''}"
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.attach(MIMEText(build_html(postings), "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, recipient, msg.as_string())

    print(f"✅ E-Mail gesendet an {recipient} — {count} neue Projekte")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main() -> None:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] Starte freelancermap-Monitor...")

    # Seite abrufen
    try:
        html = fetch_html()
    except Exception as e:
        print(f"❌ Fehler beim Abrufen: {e}", file=sys.stderr)
        sys.exit(1)

    postings = parse_postings(html)
    print(f"  {len(postings)} Projekte auf Seite 1 gefunden")

    seen = load_seen()
    is_first_run = len(seen) == 0

    new_postings = [p for p in postings if p["id"] not in seen]

    if is_first_run:
        # Erster Lauf: Seen-Liste befüllen ohne E-Mail zu senden
        print(f"  Erster Lauf — {len(postings)} Projekte als gesehen markiert, keine E-Mail.")
    elif new_postings:
        print(f"  {len(new_postings)} neue Projekte gefunden!")
        send_email(new_postings)
    else:
        print("  Keine neuen Projekte.")

    # Seen-Liste aktualisieren
    for p in postings:
        seen.add(p["id"])
    save_seen(seen)


if __name__ == "__main__":
    main()
