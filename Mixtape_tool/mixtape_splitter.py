#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path


# ---------------------------------------------------------------------------
# Timecode parsing
# ---------------------------------------------------------------------------

LINK_TIMECODE_RE = re.compile(
    r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]\(https?://[^\)]+\)\s*([^\[\n]+)'
)

BRACKET_TIMECODE_RE = re.compile(
    r'^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^\n]+)',
    re.MULTILINE
)

NUMBERED_TIMECODE_RE = re.compile(
    r'^\s*\d+\.\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+([^\n]+)',
    re.MULTILINE
)

PLAIN_TIMECODE_RE = re.compile(
    r'^(\d{1,2}:\d{2}(?::\d{2})?)\s+([^\n]+)',
    re.MULTILINE
)

TIMECODE_RE = re.compile(
    r'(\d{1,2,3}:\d{2,3}(?::\d{2})?)'
)

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def parse_timecode(tc: str) -> int:
    parts = [int(p) for p in tc.strip().split(':')]

    if len(parts) == 2:
        return parts[0] * 60 + parts[1]

    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    raise ValueError(f'Invalid timecode: {tc}')


def clean_title(title: str, max_len: int = 100) -> str:
    """
    Sanitise a string for use as a filename or folder name.

    Pass order:
      1. NFKC normalise            — converts fullwidth variants (｜ ： etc) to ASCII
      2. Expand ampersands         — replace & with 'and' before stripping
      3. Strip illegal characters  — characters Windows forbids in filenames
      4. MP3 compatability         — periods and apostrophes trip up many cheap players
      5. Collapse spaces           — tidy up any gaps left by removals
      6. Truncate long filenames   — keep under max_len to avoid MAX_PATH issues
    """
    title = unicodedata.normalize('NFKC', title)
    title = title.strip().replace('\n', ' ')

    # Expand ampersand before any stripping so we don't lose the word
    title = title.replace('&', 'and')

    # Windows-illegal characters
    title = re.sub(r'[<>:"/\\|?*]', '', title)

    # Characters that trip up cheap/budget MP3 players mid-filename
    # Periods: players often treat them as extension separators
    # Apostrophes/backticks: cause display/sorting issues on some firmware
    title = re.sub(r"[.'`]", '', title)

    title = re.sub(r'  +', ' ', title).strip()

    if len(title) > max_len:
        title = title[:max_len].rstrip()

    return title


def make_folder_name(title: str, channel: str, max_len: int = 60) -> str:
    """
    Build a folder name from video title and channel.
    Tries 'Title - Channel' first; falls back to just 'Title' if too long.
    """
    combined = clean_title(f'{title} - {channel}', max_len=9999) if channel else None

    if combined and len(combined) <= max_len:
        return combined

    return clean_title(title, max_len=max_len)


# ---------------------------------------------------------------------------
# Track extraction
# ---------------------------------------------------------------------------

def extract_tracks(description: str) -> list[dict]:
    """
    Heuristic timestamp parser.

    Handles formats like:
        00:00 Song
        [00:00] Song
        {00:00} Song
        01. 00:00 Song
        ▶ 00:00 Song
        - 00:00 - Song
        00:00 | Song
        00:00 — Song
        000:00
        000:00:00 (FOR SOME FUCKING REASON???)
    """

    tracks = []

    for raw_line in description.splitlines():

        line = unicodedata.normalize('NFKC', raw_line).strip()

        if not line:
            continue

        match = TIMECODE_RE.search(line)

        if not match:
            continue

        tc = match.group(1)

        try:
            start_sec = parse_timecode(tc)
        except ValueError:
            continue

        # Everything AFTER the timestamp becomes title
        title = line[match.end():]

        # Strip common separators/junk
        title = re.sub(
            r'^[\s\]\}\)\-–—|:>.•]+',
            '',
            title
        )

        title = clean_title(title)

        if not title:
            continue

        tracks.append({
            'start_sec': start_sec,
            'title': title,
        })

    # Deduplicate timestamps
    seen = set()
    deduped = []

    for track in tracks:
        if track['start_sec'] in seen:
            continue

        seen.add(track['start_sec'])
        deduped.append(track)

    deduped.sort(key=lambda t: t['start_sec'])

    return deduped

def extract_chapters(info: dict) -> list[dict]:
    chapters = info.get('chapters') or []

    tracks = []

    for chapter in chapters:
        title = clean_title(chapter.get('title', ''))

        start = chapter.get('start_time')
        end   = chapter.get('end_time')

        if not title or start is None:
            continue

        tracks.append({
            'start_sec': int(start),
            'end_sec':   int(end) if end is not None else None,
            'title':     title,
        })

    return tracks


# ---------------------------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------------------------


def get_video_info(url: str) -> dict:
    cmd = [
        'yt-dlp',
        '--dump-json',
        '--no-playlist',
        url,
    ]

    result = subprocess.run(cmd, capture_output=True)

    if result.returncode != 0:
        return {}

    try:
        info = json.loads(result.stdout.decode('utf-8', errors='replace'))

        return {
            'title':       info.get('title', ''),
            'channel':     info.get('uploader') or info.get('channel', ''),
            'description': info.get('description', ''),
            'chapters':    info.get('chapters') or [],
            'is_live':     info.get('is_live'),
            'live_status': info.get('live_status'),
        }

    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_audio(url: str, output_dir: Path) -> Path:
    template = str(output_dir / '%(title)s [%(id)s].%(ext)s')

    cmd = [
        'yt-dlp',
        '--extract-audio',
        '--audio-format', 'mp3',
        '--audio-quality', '0',
        '--write-description',
        '--no-playlist',
        '-o', template,
        url,
    ]

    result = subprocess.run(cmd)

    if result.returncode != 0:
        sys.exit('yt-dlp audio download failed.')

    mp3_files = sorted(
        output_dir.glob('*.mp3'),
        key=lambda f: f.stat().st_mtime,
    )

    if not mp3_files:
        sys.exit('Download succeeded but no MP3 found.')

    return mp3_files[-1]


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------


def get_duration_seconds(mp3_path: Path) -> float:
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        str(mp3_path),
    ]

    result = subprocess.run(cmd, capture_output=True)

    info = json.loads(result.stdout.decode('utf-8', errors='replace'))

    return float(info['format']['duration'])

# ---------------------------------------------------------------------------
# Playlist generation
# ---------------------------------------------------------------------------

def write_m3u8_playlist(folder: Path):
    """
    Generate a UTF-8 .m3u8 playlist for split tracks in a folder.
    Only includes numbered split tracks.
    """
    tracks = sorted(
        [
            f for f in folder.glob('*.mp3')
            if re.match(r'^\d+\s-\s.*\.mp3$', f.name, re.IGNORECASE)
        ]
    )

    if not tracks:
        return

    playlist_name = clean_title(folder.name, max_len=120)
    playlist_path = folder / f'{playlist_name}.m3u8'

    with open(playlist_path, 'w', encoding='utf-8', newline='\n') as f:
        for track in tracks:
            f.write(f'{track.name}\n')

    print(f'📝  Wrote playlist: {playlist_path.name}')
    
# ---------------------------------------------------------------------------
# Audio splitting
# ---------------------------------------------------------------------------


def split_audio(mp3_path: Path, tracks: list[dict], output_dir: Path):
    total_duration = get_duration_seconds(mp3_path)

    print(f"\n✂  Splitting into {len(tracks)} tracks...\n")

    for i, track in enumerate(tracks):
        start = track['start_sec']

        if track.get('end_sec') is not None:
            end = track['end_sec']
        else:
            end = (
                tracks[i + 1]['start_sec']
                if i + 1 < len(tracks)
                else total_duration
            )

        duration = end - start

        num      = str(i + 1).zfill(len(str(len(tracks))))
        filename = f"{num} - {clean_title(track['title'], max_len=120)}.mp3"
        out_path = output_dir / filename

        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start),
            '-t',  str(duration),
            '-i',  str(mp3_path),
            '-acodec', 'copy',
            str(out_path),
        ]

        result = subprocess.run(cmd, capture_output=True)

        status   = '✓' if result.returncode == 0 else '✗'
        mins, secs = divmod(int(start), 60)

        print(f"  {status} [{mins:02d}:{secs:02d}] {filename}")

    print(f"\n✅ Done. Tracks saved to: {output_dir}")
    
    write_m3u8_playlist(output_dir)