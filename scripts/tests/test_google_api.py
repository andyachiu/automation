"""Offline regression tests for calendar pagination."""

from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from shared.google_api import list_calendar_events


def test_calendar_follows_pages_including_empty_intermediate_page():
    pages = [
        {"items": [{"summary": "Meeting", "start": {"dateTime": "2026-09-13T10:00:00Z"}}], "nextPageToken": "page+2/="},
        {"items": [], "nextPageToken": "page3"},
        {"items": [{"summary": "Allergy shot", "start": {"date": "2026-09-20"}, "end": {"date": "2026-09-21"}, "location": "Clinic"}]},
    ]
    with patch("shared.google_api._get_json", side_effect=pages) as fetch:
        events = list_calendar_events("test-token", "start", "end", "custom@example.com")

    assert events == [
        {"summary": "Meeting", "start": "2026-09-13T10:00:00Z", "end": "", "location": None},
        {"summary": "Allergy shot", "start": "2026-09-20", "end": "2026-09-21", "location": "Clinic"},
    ]
    assert fetch.call_count == 3
    for call, page_token in zip(fetch.call_args_list, [None, "page+2/=", "page3"]):
        url, token = call.args
        assert token == "test-token"
        assert urlsplit(url).path == "/calendar/v3/calendars/custom%40example.com/events"
        expected = {"timeMin": ["start"], "timeMax": ["end"], "singleEvents": ["true"], "orderBy": ["startTime"], "maxResults": ["250"]}
        if page_token:
            expected["pageToken"] = [page_token]
        assert parse_qs(urlsplit(url).query) == expected


@pytest.mark.parametrize("page", [{}, {"items": []}, {"items": [{}]}])
def test_calendar_stops_after_single_page(page):
    with patch("shared.google_api._get_json", return_value=page) as fetch:
        events = list_calendar_events("test-token", "start", "end")
    assert len(events) == len(page.get("items", []))
    fetch.assert_called_once()


def test_later_page_failure_raises_instead_of_returning_partial_calendar():
    error = HTTPError("https://example.com", 503, "Unavailable", {}, None)
    with patch("shared.google_api._get_json", side_effect=[
        {"items": [{"summary": "Meeting"}], "nextPageToken": "page2"}, error,
    ]):
        with pytest.raises(HTTPError):
            list_calendar_events("test-token", "start", "end")
