from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.youtube import _extract_video_id, _join_transcript, ingest_youtube


# --- Video ID extraction ---

def test_extract_video_id_watch_url():
    assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_short_url():
    assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_shorts_url():
    assert _extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_raises_on_invalid_url():
    with pytest.raises(ValueError, match="Could not extract"):
        _extract_video_id("https://example.com/not-youtube")


# --- Transcript joining ---

def test_join_transcript_spaces_within_sentence():
    segments = [
        {"text": "Hello"},
        {"text": "world."},
    ]
    result = _join_transcript(segments)
    assert result == "Hello world."


def test_join_transcript_newline_between_sentences():
    segments = [
        {"text": "First sentence."},
        {"text": "Second sentence."},
    ]
    result = _join_transcript(segments)
    assert result == "First sentence.\nSecond sentence."


def test_join_transcript_groups_mid_sentence_segments():
    segments = [
        {"text": "This is"},
        {"text": "a long"},
        {"text": "sentence."},
        {"text": "New sentence?"},
    ]
    result = _join_transcript(segments)
    assert result == "This is a long sentence.\nNew sentence?"


def test_join_transcript_handles_question_and_exclamation():
    segments = [
        {"text": "Is this right?"},
        {"text": "Yes!"},
        {"text": "Great."},
    ]
    result = _join_transcript(segments)
    assert result == "Is this right?\nYes!\nGreat."


def test_join_transcript_skips_empty_segments():
    segments = [
        {"text": "Hello."},
        {"text": ""},
        {"text": "World."},
    ]
    result = _join_transcript(segments)
    assert result == "Hello.\nWorld."


# --- ingest_youtube ---

async def test_ingest_youtube_returns_chunk_count():
    segments = [{"text": "word."} for _ in range(600)]
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info = MagicMock(return_value={"title": "My Video"})

    with patch("backend.ingestion.youtube.YouTubeTranscriptApi") as mock_api, \
         patch("backend.ingestion.youtube.YoutubeDL", return_value=mock_ydl), \
         patch("backend.ingestion.youtube.store_chunk", return_value="uuid") as mock_store:
        mock_api.get_transcript = MagicMock(return_value=segments)
        result = await ingest_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result == mock_store.call_count
    assert result >= 1


async def test_ingest_youtube_sets_correct_metadata():
    segments = [{"text": "word."} for _ in range(600)]
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info = MagicMock(return_value={"title": "Test Video Title"})

    with patch("backend.ingestion.youtube.YouTubeTranscriptApi") as mock_api, \
         patch("backend.ingestion.youtube.YoutubeDL", return_value=mock_ydl), \
         patch("backend.ingestion.youtube.store_chunk", return_value="uuid") as mock_store:
        mock_api.get_transcript = MagicMock(return_value=segments)
        await ingest_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    meta = mock_store.call_args_list[0].args[1]
    assert meta["source_type"] == "youtube"
    assert meta["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert meta["title"] == "Test Video Title"
    assert meta["chunk_index"] == 0


async def test_ingest_youtube_raises_on_no_captions():
    from youtube_transcript_api import NoTranscriptFound

    with patch("backend.ingestion.youtube.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript = MagicMock(
            side_effect=NoTranscriptFound("dQw4w9WgXcQ", [], None)
        )
        with pytest.raises(ValueError, match="no captions available"):
            await ingest_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
