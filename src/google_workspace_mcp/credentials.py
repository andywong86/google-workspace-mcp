from pathlib import Path

from google.oauth2.credentials import Credentials


GCLOUD_CONFIG_DIR = Path.home() / ".config" / "gcloud"
PROFILE_SUFFIX = "_mcp_credentials"
PROFILE_GLOB = f"*{PROFILE_SUFFIX}.json"


def list_credential_profiles() -> list[str]:
    """Return safe Google MCP credential profile names."""
    if not GCLOUD_CONFIG_DIR.exists():
        return []

    return sorted(
        path.stem
        for path in GCLOUD_CONFIG_DIR.glob(PROFILE_GLOB)
        if path.is_file() and path.stem.endswith(PROFILE_SUFFIX)
    )


def credential_path(profile: str) -> Path:
    allowed = set(list_credential_profiles())
    if profile not in allowed:
        raise ValueError(
            f"Unknown credential profile {profile!r}. "
            f"Allowed profiles: {', '.join(sorted(allowed)) or '(none)'}"
        )

    return GCLOUD_CONFIG_DIR / f"{profile}.json"


def credentials_for(profile: str) -> Credentials:
    return Credentials.from_authorized_user_file(str(credential_path(profile)))
