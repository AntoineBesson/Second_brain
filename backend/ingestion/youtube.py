import re
from datetime import datetime, timezone

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from backend.memory.vector import _chunk, store_chunk

_YT_PATTERNS = [
    r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})",
    r"youtu\.be/([A-Za-z0-9_-]{11})",
    r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
]


def _extract_video_id(url: str) -> str:
    for pattern in _YT_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise ValueError(f"Could not extract YouTube video ID from: {url}")


def _join_transcript(segments: list[dict]) -> str:
    """Join transcript segments into sentences.

    Segments not ending with .?! are joined with spaces.
    A newline is inserted between complete sentences.
    """
    lines: list[str] = []
    current: list[str] = []

    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        current.append(text)
        if text[-1] in ".?!":
            lines.append(" ".join(current))
            current = []

    if current:
        lines.append(" ".join(current))

    return "\n".join(lines)


async def ingest_youtube(url: str) -> int:
    """Fetch a YouTube transcript and store chunks in Qdrant.

    Returns number of chunks stored.
    Raises ValueError if no captions are available.
    """
    video_id = _extract_video_id(url)

    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
    except (NoTranscriptFound, TranscriptsDisabled) as exc:
        raise ValueError("no captions available for this video") from exc

    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            raise ValueError(f"Could not fetch video metadata: {exc}") from exc
    title = info.get("title", url)

    text = _join_transcript(segments)
    chunks = _chunk(text)
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        store_chunk(chunk, {
            "source_type": "youtube",
            "source_url": url,
            "title": title,
            "date_added": now,
            "chunk_index": i,
            "tags": [],
        })

    return len(chunks)
