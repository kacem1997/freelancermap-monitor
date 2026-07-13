"""
freelancermap.de Projekt-Monitor
Fetcht neue Projekte und sendet Push-Notifications via ntfy.sh.
"""

import json
import os
import re
import sys
from datetime import datetime

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

# Bis zu dieser Anzahl: eine Notification pro Posting (direkt antippbar)
# Darüber: eine Sammel-Notification
INDIVIDUAL_THRESHOLD = 5

FETCH_HEADERS = {
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
    resp = requests.get(SEARCH_URL, headers=FETCH_HEADERS, timeout=30)
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
# ntfy.sh Notifications
# ---------------------------------------------------------------------------

def ntfy_post(topic: str, title: str, body: str, click_url: str) -> None:
    """Sendet eine Push-Notification via ntfy.sh."""
    requests.post(
        f"https://ntfy.sh/{topic}",
        json={
            "topic": topic,
            "title": title,
            "message": body,
            "click": click_url,
            "tags": ["briefcase"],
            "priority": 3,
        },
        timeout=15,
    ).raise_for_status()


def send_notifications(postings: list[dict], topic: str) -> None:
    if len(postings) <= INDIVIDUAL_THRESHOLD:
        # Eine Notification pro Posting — direkt antippbar
        for p in postings:
            ntfy_post(
                topic=topic,
                title=p["title"],
                body="Neues Projekt auf freelancermap.de — antippen zum Öffnen",
                click_url=p["url"],
            )
            print(f"  🔔 Notification: {p['title']}")
    else:
        # Sammel-Notification bei vielen neuen Postings
        body = "\n".join(f"• {p['title']}" for p in postings[:10])
        if len(postings) > 10:
            body += f"\n… und {len(postings) - 10} weitere"
        ntfy_post(
            topic=topic,
            title=f"🔔 {len(postings)} neue Projekte auf freelancermap.de",
            body=body,
            click_url=SEARCH_URL,
        )
        print(f"  🔔 Sammel-Notification: {len(postings)} neue Projekte")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main() -> None:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] Starte freelancermap-Monitor...")

    ntfy_topic = os.environ.get("NTFY_TOPIC")
    if not ntfy_topic:
        print("❌ NTFY_TOPIC nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

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
        print(f"  Erster Lauf — {len(postings)} Projekte als gesehen markiert, keine Notification.")
    elif new_postings:
        print(f"  {len(new_postings)} neue Projekte!")
        send_notifications(new_postings, ntfy_topic)
    else:
        print("  Keine neuen Projekte.")

    for p in postings:
        seen.add(p["id"])
    save_seen(seen)


if __name__ == "__main__":
    main()
