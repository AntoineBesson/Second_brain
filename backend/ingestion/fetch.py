from pathlib import Path

import httpx
from fastapi import UploadFile

_DEFAULT_HEADERS = {"User-Agent": "SecondBrain-Bot/1.0"}
_TIMEOUT = 30.0


async def fetch_bytes(
    source: UploadFile | str | Path,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    """Return raw bytes from an UploadFile, local path, or HTTP URL.

    auth and headers are only forwarded for HTTP URLs.
    auth is HTTP Basic auth — used for Twilio MediaUrl0 which
    requires (ACCOUNT_SID, AUTH_TOKEN).
    """
    if isinstance(source, UploadFile):
        return await source.read()

    if isinstance(source, Path) or (
        isinstance(source, str) and not source.startswith("http")
    ):
        return Path(source).read_bytes()

    # HTTP URL
    r = httpx.get(
        source,
        auth=auth,
        headers={**_DEFAULT_HEADERS, **(headers or {})},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.content
