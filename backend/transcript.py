"""
YouTube transcript and metadata fetching.

Uses `youtube-transcript-api` library for robust caption fetching, with
httpx for metadata (oEmbed). Maintains the same public interface so
routes.py doesn't need changes.
"""

import asyncio
from dataclasses import dataclass
from functools import partial

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

CHUNK_INTERVAL_SECONDS = 30.0
METADATA_TIMEOUT = 5.0


@dataclass
class TranscriptResult:
    text: str


@dataclass
class VideoMetadata:
    title: str
    author: str


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


def _format_transcript_with_timestamps(snippets: list[dict]) -> str:
    if not snippets:
        return ""
    chunks: list[str] = []
    current_texts: list[str] = []
    chunk_start = snippets[0]["start"]
    for snippet in snippets:
        if snippet["start"] - chunk_start >= CHUNK_INTERVAL_SECONDS and current_texts:
            chunks.append(f"[{_format_timestamp(chunk_start)}] {' '.join(current_texts)}")
            current_texts = []
            chunk_start = snippet["start"]
        current_texts.append(snippet["text"].strip())
    if current_texts:
        chunks.append(f"[{_format_timestamp(chunk_start)}] {' '.join(current_texts)}")
    return "\n".join(chunks)


def _fetch_transcript_sync(video_id: str) -> str:
    """Blocking call — run via asyncio.to_thread / run_in_executor."""
    ytt = YouTubeTranscriptApi()
    try:
        # Try English first, then fall back to any language
        try:
            transcript = ytt.fetch(video_id, languages=["en"])
        except NoTranscriptFound:
            transcript = ytt.fetch(video_id)  # any language
    except TranscriptsDisabled:
        raise Exception(
            "Transcripts are disabled for this video. "
            "The creator has turned off captions."
        )
    except VideoUnavailable:
        raise Exception("This video is unavailable or does not exist.")
    except Exception as e:
        raise Exception(f"Failed to fetch transcript: {e}")

    snippets = [
        {"start": s.start, "text": s.text}
        for s in transcript.snippets
        if s.text.strip()
    ]
    return _format_transcript_with_timestamps(snippets)


async def fetch_transcript(client: httpx.AsyncClient, video_id: str) -> TranscriptResult:
    """Fetch transcript. `client` param kept for API compatibility but unused."""
    text = await asyncio.to_thread(_fetch_transcript_sync, video_id)
    return TranscriptResult(text=text)


async def fetch_metadata(client: httpx.AsyncClient, video_id: str) -> VideoMetadata:
    url = (
        f"https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com"
        f"%2Fwatch%3Fv%3D{video_id}&format=json"
    )
    resp = await client.get(url, timeout=METADATA_TIMEOUT)
    if not (200 <= resp.status_code < 300):
        raise Exception("Could not fetch video metadata.")
    data = resp.json()
    return VideoMetadata(
        title=data.get("title", ""),
        author=data.get("author_name", ""),
    )
