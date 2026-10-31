import base64
from datetime import UTC, datetime, timedelta
import html
import json
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

from google_workspace_mcp.credentials import list_credential_profiles
from google_workspace_mcp.google_services import calendar_service, gmail_service


mcp = FastMCP("google-workspace")


def _compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _header_value(headers: list[dict[str, str]], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def _summarize_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    return {
        "id": message.get("id"),
        "threadId": message.get("threadId"),
        "date": _header_value(headers, "Date"),
        "from": _header_value(headers, "From"),
        "to": _header_value(headers, "To"),
        "subject": _header_value(headers, "Subject"),
        "snippet": message.get("snippet"),
    }


def _decode_body_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<br\s*/?>", "\n", value)
    value = re.sub(r"(?s)</p\s*>", "\n\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]+\n", "\n", value)


def _normalize_body(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def _collect_body_parts(part: dict[str, Any]) -> tuple[list[str], list[str]]:
    plain_parts = []
    html_parts = []

    filename = part.get("filename")
    body = part.get("body", {})
    data = body.get("data")
    mime_type = part.get("mimeType")

    if data and not filename:
        decoded = _decode_body_data(data)
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)

    for child in part.get("parts", []):
        child_plain, child_html = _collect_body_parts(child)
        plain_parts.extend(child_plain)
        html_parts.extend(child_html)

    return plain_parts, html_parts


def _event_time(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None

    return _drop_empty({
        "date": value.get("date"),
        "dateTime": value.get("dateTime"),
        "timeZone": value.get("timeZone"),
    })


def _calendar_time(value: str, time_zone: str | None, all_day: bool) -> dict[str, str]:
    if all_day:
        return {"date": value}

    result = {"dateTime": value}
    if time_zone:
        result["timeZone"] = time_zone
    return result


def _reminders(
    reminder_minutes: list[int] | None,
    reminder_method: str,
    use_default_reminders: bool | None,
) -> dict[str, Any] | None:
    if use_default_reminders is True:
        return {"useDefault": True}
    if reminder_minutes is None and use_default_reminders is None:
        return None
    if reminder_minutes is None:
        reminder_minutes = []

    return {
        "useDefault": False,
        "overrides": [
            {
                "method": reminder_method,
                "minutes": max(0, min(minutes, 40320)),
            }
            for minutes in reminder_minutes
        ],
    }


def _attendees(attendees: list[str] | None) -> list[dict[str, str]] | None:
    if attendees is None:
        return None
    return [{"email": email} for email in attendees]


def _summarize_calendar_event(
    event: dict[str, Any],
    include_description: bool,
    include_attendees: bool,
) -> dict[str, Any]:
    attendee_count = len(event.get("attendees", []))
    summary = _drop_empty({
        "id": event.get("id"),
        "iCalUID": event.get("iCalUID"),
        "status": event.get("status"),
        "summary": event.get("summary"),
        "location": event.get("location"),
        "start": _event_time(event.get("start")),
        "end": _event_time(event.get("end")),
        "eventType": event.get("eventType"),
        "htmlLink": event.get("htmlLink"),
        "creator": event.get("creator", {}).get("email"),
        "organizer": event.get("organizer", {}).get("email"),
        "attendeeCount": attendee_count if attendee_count else None,
        "recurringEventId": event.get("recurringEventId"),
    })

    if include_description:
        summary["description"] = event.get("description")

    if include_attendees:
        summary["attendees"] = [
            _drop_empty({
                "email": attendee.get("email"),
                "displayName": attendee.get("displayName"),
                "responseStatus": attendee.get("responseStatus"),
                "self": attendee.get("self"),
                "organizer": attendee.get("organizer"),
            })
            for attendee in event.get("attendees", [])
        ]

    return _drop_empty(summary)


def _mutable_event_copy(event: dict[str, Any]) -> dict[str, Any]:
    ignored_fields = {
        "kind",
        "etag",
        "id",
        "htmlLink",
        "created",
        "updated",
        "creator",
        "organizer",
        "sequence",
        "hangoutLink",
    }
    return {key: value for key, value in event.items() if key not in ignored_fields}


@mcp.tool()
def list_credentials() -> list[str]:
    """List available Google MCP credential profiles."""
    return list_credential_profiles()


@mcp.tool(structured_output=False)
def search_gmail(
    query: str,
    credential: str,
    max_results: int = 10,
) -> str:
    """Search Gmail messages with a selected credential profile."""
    service = gmail_service(credential)
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max(1, min(max_results, 50)),
        )
        .execute()
    )
    return _compact_json({
        "messages": response.get("messages", []),
        "resultSizeEstimate": response.get("resultSizeEstimate", 0),
    })


@mcp.tool(structured_output=False)
def search_gmail_summaries(
    query: str,
    credential: str,
    max_results: int = 10,
) -> str:
    """Search Gmail and return readable message summaries."""
    service = gmail_service(credential)
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max(1, min(max_results, 25)),
        )
        .execute()
    )
    messages = response.get("messages", [])
    summaries = []

    for message in messages:
        detail = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=["Date", "From", "To", "Subject"],
            )
            .execute()
        )
        summaries.append(_summarize_message(detail))

    return _compact_json({
        "messages": summaries,
        "resultSizeEstimate": response.get("resultSizeEstimate", 0),
    })


@mcp.tool(structured_output=False)
def get_gmail_message(
    message_id: str,
    credential: str,
    format: str = "metadata",
) -> str:
    """Fetch a Gmail message by ID using a selected credential profile."""
    service = gmail_service(credential)
    return _compact_json(
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format=format,
        )
        .execute()
    )


@mcp.tool(structured_output=False)
def get_gmail_message_body(
    message_id: str,
    credential: str,
    max_chars: int = 12000,
) -> str:
    """Fetch readable text body for a Gmail message by ID."""
    service = gmail_service(credential)
    message = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="full",
        )
        .execute()
    )

    plain_parts, html_parts = _collect_body_parts(message.get("payload", {}))
    if plain_parts:
        body = _normalize_body("\n\n".join(plain_parts))
        source = "text/plain"
    elif html_parts:
        body = _normalize_body(_html_to_text("\n\n".join(html_parts)))
        source = "text/html"
    else:
        body = ""
        source = None

    max_chars = max(500, min(max_chars, 100000))
    truncated = len(body) > max_chars

    return _compact_json({
        **_summarize_message(message),
        "body": body[:max_chars],
        "bodySource": source,
        "truncated": truncated,
    })


@mcp.tool(structured_output=False)
def list_calendars(
    credential: str,
    min_access_role: str | None = None,
    show_hidden: bool = False,
    max_results: int = 100,
) -> str:
    """List calendars available to a selected credential profile."""
    service = calendar_service(credential)
    request_args: dict[str, Any] = {
        "showHidden": show_hidden,
        "maxResults": max(1, min(max_results, 250)),
    }
    if min_access_role:
        request_args["minAccessRole"] = min_access_role

    response = service.calendarList().list(**request_args).execute()
    calendars = [
        {
            "id": item.get("id"),
            "summary": item.get("summary"),
            "description": item.get("description"),
            "timeZone": item.get("timeZone"),
            "accessRole": item.get("accessRole"),
            "primary": item.get("primary", False),
            "selected": item.get("selected", False),
            "hidden": item.get("hidden", False),
            "backgroundColor": item.get("backgroundColor"),
            "foregroundColor": item.get("foregroundColor"),
        }
        for item in response.get("items", [])
    ]
    return _compact_json({
        "calendars": calendars,
        "nextPageToken": response.get("nextPageToken"),
        "nextSyncToken": response.get("nextSyncToken"),
    })


@mcp.tool(structured_output=False)
def list_calendar_events(
    credential: str,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    query: str | None = None,
    max_results: int = 25,
    single_events: bool = True,
    order_by: str = "startTime",
    time_zone: str | None = None,
    show_deleted: bool = False,
    page_token: str | None = None,
    event_types: list[str] | None = None,
    include_description: bool = False,
    include_attendees: bool = False,
) -> str:
    """List events from a selected Google Calendar."""
    if time_min is None:
        time_min = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if time_max is None:
        time_max = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    request_args: dict[str, Any] = {
        "calendarId": calendar_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "maxResults": max(1, min(max_results, 250)),
        "singleEvents": single_events,
        "showDeleted": show_deleted,
    }

    if order_by:
        request_args["orderBy"] = order_by
    if query:
        request_args["q"] = query
    if time_zone:
        request_args["timeZone"] = time_zone
    if page_token:
        request_args["pageToken"] = page_token
    if event_types:
        request_args["eventTypes"] = event_types

    response = calendar_service(credential).events().list(**request_args).execute()
    events = [
        _summarize_calendar_event(
            event,
            include_description=include_description,
            include_attendees=include_attendees,
        )
        for event in response.get("items", [])
    ]

    return _compact_json({
        "calendarId": calendar_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "events": events,
        "nextPageToken": response.get("nextPageToken"),
        "nextSyncToken": response.get("nextSyncToken"),
    })


@mcp.tool(structured_output=False)
def create_calendar_event(
    credential: str,
    calendar_id: str,
    summary: str,
    start: str,
    end: str,
    time_zone: str | None = None,
    all_day: bool = False,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    recurrence: list[str] | None = None,
    reminder_minutes: list[int] | None = None,
    reminder_method: str = "popup",
    use_default_reminders: bool | None = None,
    send_updates: str = "none",
) -> str:
    """Create a calendar event."""
    body = _drop_empty({
        "summary": summary,
        "description": description,
        "location": location,
        "start": _calendar_time(start, time_zone, all_day),
        "end": _calendar_time(end, time_zone, all_day),
        "attendees": _attendees(attendees),
        "recurrence": recurrence,
        "reminders": _reminders(reminder_minutes, reminder_method, use_default_reminders),
    })

    event = (
        calendar_service(credential)
        .events()
        .insert(calendarId=calendar_id, body=body, sendUpdates=send_updates)
        .execute()
    )
    return _compact_json(_summarize_calendar_event(event, include_description=True, include_attendees=True))


@mcp.tool(structured_output=False)
def update_calendar_event(
    credential: str,
    calendar_id: str,
    event_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    time_zone: str | None = None,
    all_day: bool = False,
    description: str | None = None,
    location: str | None = None,
    recurrence: list[str] | None = None,
    reminder_minutes: list[int] | None = None,
    reminder_method: str = "popup",
    use_default_reminders: bool | None = None,
    send_updates: str = "none",
) -> str:
    """Patch selected fields on a calendar event."""
    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if start is not None:
        body["start"] = _calendar_time(start, time_zone, all_day)
    if end is not None:
        body["end"] = _calendar_time(end, time_zone, all_day)
    if recurrence is not None:
        body["recurrence"] = recurrence

    reminders = _reminders(reminder_minutes, reminder_method, use_default_reminders)
    if reminders is not None:
        body["reminders"] = reminders

    if not body:
        raise ValueError("No update fields were provided.")

    event = (
        calendar_service(credential)
        .events()
        .patch(calendarId=calendar_id, eventId=event_id, body=body, sendUpdates=send_updates)
        .execute()
    )
    return _compact_json(_summarize_calendar_event(event, include_description=True, include_attendees=True))


@mcp.tool(structured_output=False)
def move_calendar_event(
    credential: str,
    source_calendar_id: str,
    event_id: str,
    destination_calendar_id: str,
    send_updates: str = "none",
) -> str:
    """Move an event to another calendar."""
    event = (
        calendar_service(credential)
        .events()
        .move(
            calendarId=source_calendar_id,
            eventId=event_id,
            destination=destination_calendar_id,
            sendUpdates=send_updates,
        )
        .execute()
    )
    return _compact_json(_summarize_calendar_event(event, include_description=True, include_attendees=True))


@mcp.tool(structured_output=False)
def duplicate_calendar_event(
    credential: str,
    source_calendar_id: str,
    event_id: str,
    destination_calendar_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    time_zone: str | None = None,
    all_day: bool = False,
    send_updates: str = "none",
) -> str:
    """Duplicate an event into a calendar, optionally overriding title and time range."""
    service = calendar_service(credential)
    source_event = service.events().get(calendarId=source_calendar_id, eventId=event_id).execute()
    body = _mutable_event_copy(source_event)

    if summary is not None:
        body["summary"] = summary
    if start is not None:
        body["start"] = _calendar_time(start, time_zone, all_day)
    if end is not None:
        body["end"] = _calendar_time(end, time_zone, all_day)

    event = (
        service.events()
        .insert(calendarId=destination_calendar_id, body=body, sendUpdates=send_updates)
        .execute()
    )
    return _compact_json(_summarize_calendar_event(event, include_description=True, include_attendees=True))


@mcp.tool(structured_output=False)
def delete_calendar_event(
    credential: str,
    calendar_id: str,
    event_id: str,
    confirm: bool = False,
    send_updates: str = "none",
) -> str:
    """Delete a calendar event. Requires confirm=true."""
    if not confirm:
        raise ValueError("Deletion requires confirm=true.")

    (
        calendar_service(credential)
        .events()
        .delete(calendarId=calendar_id, eventId=event_id, sendUpdates=send_updates)
        .execute()
    )
    return _compact_json({
        "deleted": True,
        "calendarId": calendar_id,
        "eventId": event_id,
    })


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
