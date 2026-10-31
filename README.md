# google-workspace-mcp

Local MCP server for Google Workspace APIs. It uses OAuth credential files from
`~/.config/gcloud` and exposes safe credential profile names to the agent.

## Setup

```bash
uv venv
uv sync
```

## Run

```bash
uv run google-workspace-mcp
```

## Credential Profiles

The server lists only files matching:

```text
~/.config/gcloud/*_mcp_credentials.json
```

Tool calls use the filename stem, not the full path. For example:

```text
personal_mcp_credentials
```

maps internally to:

```text
~/.config/gcloud/personal_mcp_credentials.json
```

Arbitrary paths and unknown profile names are rejected.

## Initial Tools

- `list_credentials`: lists available Google MCP credential profile names.
- `search_gmail`: searches Gmail threads/messages using a selected credential profile.
- `get_gmail_message`: fetches Gmail message metadata/snippet by message ID.
- `get_gmail_message_body`: fetches readable text body for a Gmail message by ID.
- `list_calendars`: lists calendars available to a selected credential profile.
- `list_calendar_events`: lists compact event summaries from a selected calendar.
- `create_calendar_event`: creates a structured calendar event.
- `update_calendar_event`: patches selected fields on a calendar event.
- `move_calendar_event`: moves a default event to another calendar.
- `duplicate_calendar_event`: copies an event to another calendar.
- `delete_calendar_event`: deletes an event when `confirm` is `true`.

## Codex MCP Config

Point Codex at the local venv entrypoint after `uv sync`:

```toml
[mcp_servers.google_workspace]
command = "/absolute/path/to/google-workspace-mcp/.venv/bin/google-workspace-mcp"
```
