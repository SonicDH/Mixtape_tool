# mixtape_splitter — Library Reference

`mixtape_splitter.py` is a standalone Python library for downloading YouTube audio, parsing tracklists from text, and splitting audio files into individual tracks. It has no CLI of its own and is intended to be imported by other scripts.

---

## Requirements

- Python 3.10 or later
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — `pip install yt-dlp`
- [ffmpeg and ffprobe](https://ffmpeg.org/download.html) — must be installed and available on `PATH`

---

## Quick Start

```python
from pathlib import Path
import mixtape_splitter as splitter

url        = "https://www.youtube.com/watch?v=abc123"
output_dir = Path("./downloads")

# Fetch metadata
info = splitter.get_video_info(url)

# Try official chapters first, fall back to description parsing
tracks = splitter.extract_chapters(info) or splitter.extract_tracks(info["description"])

# Download and split
output_dir.mkdir(parents=True, exist_ok=True)
mp3_path = splitter.download_audio(url, output_dir)

if tracks:
    splitter.split_audio(mp3_path, tracks, output_dir)
else:
    print("No tracklist found — keeping as single file.")
```

---

## API Reference

---

### `parse_timecode(tc: str) -> int`

Converts a timecode string to total seconds.

**Parameters:**
- `tc` — a string in `MM:SS` or `HH:MM:SS` format

**Returns:** integer seconds

**Raises:** `ValueError` if the format is not recognised

```python
splitter.parse_timecode("3:45")     # → 225
splitter.parse_timecode("01:03:28") # → 3808
splitter.parse_timecode("0:00")     # → 0
```

---

### `clean_title(title: str, max_len: int = 100) -> str`

Sanitises a string for safe use as a filename or folder name.

**Parameters:**
- `title` — the raw string to sanitise
- `max_len` — maximum character length after sanitisation (default: `100`)

**Returns:** sanitised string

Sanitisation passes, in order:

1. NFKC Unicode normalisation — converts fullwidth characters (`｜`, `：`, `？` etc.) to ASCII equivalents
2. `&` is replaced with `and`
3. Windows-illegal characters (`< > : " / \ | ? *`) are removed
4. Periods (`.`) and apostrophes (`'`) and backticks (`` ` ``) are removed — these cause display and sorting issues on many budget MP3 players
5. Consecutive spaces are collapsed to one
6. Result is truncated to `max_len` characters

Emojis, non-Latin scripts, and most Unicode are preserved.

```python
splitter.clean_title("feat. Kate Bollinger")
# → "feat Kate Bollinger"

splitter.clean_title("Sébastien Tellier - Thrill of the Night (feat. Slayyyter & Nile Rodgers)")
# → "Sébastien Tellier - Thrill of the Night (feat Slayyyter and Nile Rodgers)"

splitter.clean_title("It's Alright")
# → "Its Alright"

splitter.clean_title("Horizon Pulse 2026 ｜ Forza Horizon 6")
# → "Horizon Pulse 2026  Forza Horizon 6"

splitter.clean_title("A Very Long Title That Goes On Forever", max_len=20)
# → "A Very Long Title Th"
```

**Note:** `clean_title` is applied automatically inside `extract_tracks`, `extract_chapters`, and `split_audio`. You only need to call it directly when constructing folder names or other filesystem paths.

---

### `make_folder_name(title: str, channel: str, max_len: int = 60) -> str`

Builds a folder name from a video title and channel name.

**Parameters:**
- `title` — video title
- `channel` — channel or uploader name
- `max_len` — maximum folder name length (default: `60`)

**Returns:** sanitised folder name string

Attempts `"Title - Channel"` first. If the combined result exceeds `max_len` after sanitisation, falls back to just the title (still capped at `max_len`). This avoids truncating mid-name while keeping folder names predictable.

```python
splitter.make_folder_name("Blue Hour Vol.3", "Yawaraka Jazz")
# → "Blue Hour Vol3 - Yawaraka Jazz"   (fits within 60 chars)

splitter.make_folder_name(
    "Horizon Pulse 2026 [Remixed] + DJ Amy Simpson",
    "Horizon Remixed - The Definitive Channel"
)
# → "Horizon Pulse 2026 [Remixed] + DJ Amy Simpson"  (combined too long; title only)
```

---

### `extract_tracks(description: str) -> list[dict]`

Parses a block of text and returns a list of tracks with their start times.

**Parameters:**
- `description` — any string, typically a YouTube video description or pinned comment

**Returns:** list of track dicts sorted by `start_sec`, deduplicated on timestamp:

```python
[
    {"start_sec": 0,   "title": "Persian Waltz"},
    {"start_sec": 123, "title": "Waltz of Raincoat"},
    ...
]
```

Returns an empty list if no timecodes are found.

The parser works line by line. For each line it searches for a timecode using a broad regex, then treats everything after the timestamp as the track title, stripping common separators (`]`, `}`, `)`, `-`, `–`, `—`, `|`, `:`, `>`, `.`, `•`).

**Recognised timestamp formats:**

| Format | Example |
|---|---|
| Plain `MM:SS` at line start | `03:45 Track Name` |
| Plain `HH:MM:SS` at line start | `01:03:28 Track Name` |
| Square brackets | `[03:45] Track Name` |
| Curly braces | `{03:45} Track Name` |
| YouTube chapter links | `[03:45](https://youtu.be/...&t=225s) Track Name` |
| Numbered list | `1. 03:45 Track Name` |
| With separators | `03:45 - Track Name`, `03:45 \| Track Name`, `03:45 — Track Name` |
| Play button prefix | `▶ 03:45 Track Name` |
| Long-form hours | `000:00` or `000:00:00` |

**Limitations:**

- The parser is heuristic. Descriptions with timestamps used in prose (e.g. "recorded at 12:30 in the afternoon") may produce false positive tracks. Review the parsed tracklist before splitting where accuracy matters.
- Only the first timecode found per line is used.
- If two lines share the same timestamp, the second is silently dropped during deduplication.
- Timecodes must appear before the title text on the line; titles appearing before their timestamp are not recognised.

```python
desc = """
[00:00] Intro
[03:45] TV Girl - Summer 2000 Baby
[01:03:28] The Itch - Space In The Cab
00:00 Thanks For The Memory - Serge Chaloff
"""

tracks = splitter.extract_tracks(desc)
# [
#   {"start_sec": 0,    "title": "Intro"},
#   {"start_sec": 225,  "title": "TV Girl - Summer 2000 Baby"},
#   {"start_sec": 3808, "title": "The Itch - Space In The Cab"},
# ]
# Note: the plain 00:00 line is dropped as a duplicate of the first entry.
```

---

### `extract_chapters(info: dict) -> list[dict]`

Extracts official YouTube chapter data from a `get_video_info` result dict.

**Parameters:**
- `info` — dict returned by `get_video_info`

**Returns:** list of track dicts. Each dict includes an `end_sec` key in addition to `start_sec` and `title`:

```python
[
    {"start_sec": 0,   "end_sec": 225,  "title": "Intro"},
    {"start_sec": 225, "end_sec": 3808, "title": "TV Girl - Summer 2000 Baby"},
    ...
]
```

Returns an empty list if the video has no chapters.

When `end_sec` is present, `split_audio` uses it directly rather than inferring the end from the next track's start. This produces more accurate cuts for chapter-defined tracks.

```python
info   = splitter.get_video_info(url)
tracks = splitter.extract_chapters(info)

if not tracks:
    tracks = splitter.extract_tracks(info["description"])
```

---

### `get_video_info(url: str) -> dict`

Fetches video metadata from YouTube without downloading the audio.

**Parameters:**
- `url` — a YouTube video URL

**Returns:** dict with the following keys, or an empty dict on failure:

| Key | Type | Description |
|---|---|---|
| `title` | `str` | Video title |
| `channel` | `str` | Uploader/channel name |
| `description` | `str` | Full video description |
| `chapters` | `list` | Raw chapter list from yt-dlp (pass to `extract_chapters`) |
| `is_live` | `bool \| None` | Whether the video is a live stream |
| `live_status` | `str \| None` | yt-dlp live status string |

```python
info = splitter.get_video_info("https://www.youtube.com/watch?v=abc123")

if not info:
    print("Could not retrieve metadata.")
else:
    print(info["title"])
    print(info["channel"])
```

**Limitations:**

- Requires `yt-dlp` on `PATH`. Returns an empty dict silently if yt-dlp fails.
- Only supports YouTube URLs. Other platforms supported by yt-dlp may work but are untested.
- Does not fetch comments. Pinned comment lookup, if needed, must be implemented separately.
- Private, age-restricted, or geo-blocked videos will return an empty dict.

---

### `download_audio(url: str, output_dir: Path) -> Path`

Downloads a YouTube video as a best-quality MP3 and writes a `.description` file alongside it.

**Parameters:**
- `url` — a YouTube video URL
- `output_dir` — directory to write the MP3 into; must already exist

**Returns:** `Path` to the downloaded MP3 file

**Raises:** calls `sys.exit()` if yt-dlp fails or no MP3 is found after download

The filename uses the yt-dlp template `%(title)s [%(id)s].mp3` and is not passed through `clean_title`. Sanitisation applies only to the split track filenames and folder names, not the downloaded source file.

```python
output_dir = Path("./downloads/My Mixtape")
output_dir.mkdir(parents=True, exist_ok=True)

mp3_path = splitter.download_audio("https://www.youtube.com/watch?v=abc123", output_dir)
print(mp3_path.name)
# "Blue Hour Vol.3 [abc123].mp3"
```

**Limitations:**

- Calls `sys.exit()` on failure rather than raising, which will terminate the calling process. If you need non-fatal error handling, wrap the call in a subprocess or check yt-dlp availability before calling.
- The most recently modified MP3 in `output_dir` is returned. If other MP3s exist in the directory from a previous run, this could return the wrong file. Use a dedicated per-video output directory.

---

### `get_duration_seconds(mp3_path: Path) -> float`

Returns the duration of an audio file in seconds using `ffprobe`.

**Parameters:**
- `mp3_path` — path to any audio file supported by ffprobe

**Returns:** duration as a float

```python
duration = splitter.get_duration_seconds(Path("./downloads/mix.mp3"))
print(f"{duration:.1f} seconds")
# 7234.5 seconds
```

**Limitations:**

- Requires `ffprobe` on `PATH`. Raises `json.JSONDecodeError` or `KeyError` if ffprobe fails or produces unexpected output.

---

### `write_m3u8_playlist(folder: Path)`

Generates a `.m3u8` playlist file for all split tracks in a folder.

**Parameters:**
- `folder` — directory containing split MP3 files

Only files matching the pattern `NN - Title.mp3` (i.e., numbered split tracks) are included. The playlist file is named after the folder and written into the same directory. Does nothing if no matching files are found.

The playlist uses relative filenames (no absolute paths), making it portable as long as the player and files remain in the same folder.

```python
# After splitting, generate a playlist
splitter.write_m3u8_playlist(Path("./downloads/Blue Hour Vol3 - Yawaraka Jazz"))
# Writes: ./downloads/Blue Hour Vol3 - Yawaraka Jazz/Blue Hour Vol3 - Yawaraka Jazz.m3u8
```

**Limitations:**

- M3U8 files use UTF-8 encoding. Most modern players support this, but some older firmware may not handle non-Latin filenames in a playlist correctly.
- No `#EXTINF` duration metadata is included in the playlist — just bare filenames. Players that require duration hints may not display track lengths.

---

### `split_audio(mp3_path: Path, tracks: list[dict], output_dir: Path)`

Splits an MP3 into individual track files using ffmpeg and generates an M3U8 playlist.

**Parameters:**
- `mp3_path` — path to the source MP3
- `tracks` — list of track dicts as returned by `extract_tracks` or `extract_chapters`
- `output_dir` — directory to write split files into

Track filenames are formatted as `NN - Title.mp3`, zero-padded to the width of the total track count. Titles are passed through `clean_title` with `max_len=120`.

The split uses `ffmpeg -acodec copy` (stream copy, no re-encode), so it is fast and lossless. After splitting, `write_m3u8_playlist` is called automatically.

```python
tracks = splitter.extract_tracks(description)

if tracks:
    splitter.split_audio(mp3_path, tracks, output_dir)
    mp3_path.unlink()  # optionally delete the source
```

**Track dict format accepted:**

```python
# Minimum required keys:
{"start_sec": 225, "title": "TV Girl - Summer 2000 Baby"}

# Optional end_sec (from extract_chapters):
{"start_sec": 225, "end_sec": 609, "title": "TV Girl - Summer 2000 Baby"}
```

If `end_sec` is absent, the end of each track is inferred from the start of the next. The last track always runs to the end of the file.

**Limitations:**

- Stream copy cuts are not frame-perfect. With VBR MP3 files, a cut may land slightly before or after the exact timecode — typically within one audio frame (a few milliseconds). For the vast majority of use cases this is imperceptible.
- Does not overwrite existing files cleanly — ffmpeg is called with `-y` so existing output files at the same path are overwritten without warning.
- If a track title sanitises to an empty string, the filename will be just the track number (`01 - .mp3`). This is an edge case with titles consisting entirely of stripped characters.

---

## Timecode Regex Reference

The following compiled regex patterns are exported and available for direct use:

| Name | Matches |
|---|---|
| `LINK_TIMECODE_RE` | `[MM:SS](url) Title` — YouTube chapter links |
| `BRACKET_TIMECODE_RE` | `[MM:SS] Title` — plain square brackets |
| `NUMBERED_TIMECODE_RE` | `1. MM:SS Title` — numbered list with timestamp |
| `PLAIN_TIMECODE_RE` | `MM:SS Title` — bare timestamp at line start |
| `TIMECODE_RE` | General timestamp finder used by `extract_tracks` |

`extract_tracks` uses `TIMECODE_RE` internally and does not call the named format regexes. The named regexes are available if you need to match a specific format exactly.

```python
import re
import mixtape_splitter as splitter

# Check if a string contains any timestamp
if splitter.TIMECODE_RE.search(some_text):
    print("Timecodes found")

# Extract only YouTube chapter-link style timestamps
matches = splitter.LINK_TIMECODE_RE.findall(some_text)
```

---

## Error Handling Notes

`download_audio` calls `sys.exit()` on failure rather than raising an exception. All other functions either return empty/falsy values on failure or raise standard Python exceptions (`ValueError`, `json.JSONDecodeError`). If you need to handle download failures gracefully in a larger application, call yt-dlp directly in a subprocess rather than through this library.

---

## Full Pipeline Example

```python
from pathlib import Path
import mixtape_splitter as splitter

def process(url: str, output_base: Path, keep_original: bool = False):
    # 1. Fetch metadata
    info = splitter.get_video_info(url)
    if not info:
        print("Failed to fetch metadata.")
        return

    # 2. Reject livestreams
    if info.get("is_live") or info.get("live_status") == "is_live":
        print("Livestreams not supported.")
        return

    # 3. Build output directory
    folder    = splitter.make_folder_name(info["title"], info["channel"])
    output_dir = output_base / folder
    output_dir.mkdir(parents=True, exist_ok=True)

    # 4. Find tracklist: chapters → description
    tracks = splitter.extract_chapters(info)
    if not tracks:
        tracks = splitter.extract_tracks(info["description"])

    # 5. Download
    mp3_path = splitter.download_audio(url, output_dir)

    # 6. Split or keep whole
    if tracks:
        splitter.split_audio(mp3_path, tracks, output_dir)
        if not keep_original:
            mp3_path.unlink(missing_ok=True)
    else:
        print(f"No tracklist found — saved as: {mp3_path.name}")


process(
    "https://www.youtube.com/watch?v=abc123",
    Path("./downloads"),
    keep_original=False,
)
```
