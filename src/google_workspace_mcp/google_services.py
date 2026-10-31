from functools import lru_cache

from googleapiclient.discovery import build

from google_workspace_mcp.credentials import credentials_for


@lru_cache(maxsize=32)
def gmail_service(profile: str):
    creds = credentials_for(profile)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


@lru_cache(maxsize=32)
def calendar_service(profile: str):
    creds = credentials_for(profile)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
