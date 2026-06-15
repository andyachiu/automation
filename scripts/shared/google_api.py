"""
Direct Google API client — fallback when MCP servers are unavailable.
"""

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _get_json(url: str, token: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_calendar_events(
    token: str,
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        }
    )
    url = (
        f"https://www.googleapis.com/calendar/v3/calendars/"
        f"{urllib.parse.quote(calendar_id)}/events?{params}"
    )
    data = _get_json(url, token)

    out: list[dict] = []
    for ev in data.get("items", []):
        start = ev.get("start", {})
        end = ev.get("end", {})
        out.append(
            {
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "summary": ev.get("summary", "(no title)"),
                "location": ev.get("location"),
            }
        )
    return out


def _fetch_message_metadata(token: str, msg_id: str) -> dict:
    url = (
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
        "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
    )
    data = _get_json(url, token)
    headers = {
        h["name"].lower(): h["value"]
        for h in data.get("payload", {}).get("headers", [])
    }
    return {
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "snippet": data.get("snippet", ""),
        "date": headers.get("date", ""),
    }


def list_unread_messages(token: str, max_results: int = 50) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": "is:unread in:inbox", "maxResults": str(max_results)}
    )
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}"
    data = _get_json(url, token)
    ids = [m["id"] for m in data.get("messages", [])]
    if not ids:
        return []

    with ThreadPoolExecutor(max_workers=10) as pool:
        return list(pool.map(lambda i: _fetch_message_metadata(token, i), ids))
