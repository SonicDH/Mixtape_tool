# Mixtape Tool

A command-line utility for downloading YouTube DJ sets and mixtapes as split MP3 track collections. Supports single videos, full playlist syncing, and automated archive tracking.

---

## Requirements

- Python 3.10 or later
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — `pip install yt-dlp`
- [ffmpeg](https://ffmpeg.org/download.html) — must be installed and available on `PATH`
- `mixtape_splitter.py` — must be in the same directory as `mixtape_tool.py`

---

## Installation

No installation step is required. Place both files in the same folder and run directly:

```
mixtape_tool.py
mixtape_splitter.py
```

On first run, `mixtape_config.json` is created automatically in the same directory to store your settings.

---

## Usage

### Interactive menu

Launch with no arguments to open the interactive menu:

```
python mixtape_tool.py
```

### Command-line mode

```
python mixtape_tool.py --video <url>
python mixtape_tool.py --playlist <url>
```

The interactive menu is suppressed when arguments are passed, making it suitable for scripted or scheduled invocations.

---

## CLI Reference

| Flag | Short | Description |
|---|---|---|
| `--video <url>` | `-v` | Download and split a single video |
| `--playlist <url>` | `-p` | Sync an entire playlist |
| `--output-dir <path>` | `-o` | Override the output directory for this run |
| `--keep-original` | | Retain the full unsplit MP3 after splitting |
| `--dry-run` | | Preview what a playlist sync would process without downloading |

`--output-dir` on the command line takes priority over the saved setting in `mixtape_config.json` but does not overwrite it.

`--video` and `--playlist` are mutually exclusive.

### Examples

```bash
# Process a single video
python mixtape_tool.py -v "https://www.youtube.com/watch?v=abc123"

# Sync a playlist, keep full files
python mixtape_tool.py -p "https://www.youtube.com/playlist?list=PLxxx" --keep-original

# Preview a playlist sync without downloading anything
python mixtape_tool.py -p "https://www.youtube.com/playlist?list=PLxxx" --dry-run

# Write to a specific folder for this run only
python mixtape_tool.py -v "https://www.youtube.com/watch?v=abc123" -o "D:/Music/Jazz"
```

---

## Interactive Menu

```
╔══════════════════════════════════════╗
║          MIXTAPE TOOL v1.1           ║
╚══════════════════════════════════════╝

1. Process single video
2. Sync playlist
3. Sync all saved playlists  (2 saved)
4. Open download folder
5. Download dir: ./downloads
6. Tools
7. Exit
```

### Option 1 — Process single video

Prompts for a YouTube URL and runs the full download and split pipeline. Tracks are saved to a subfolder of the download directory named after the video.

### Option 2 — Sync playlist

Prompts for a YouTube playlist URL. Downloads any videos not already recorded in the playlist's archive. Skips videos that have been successfully processed in a previous run.

### Option 3 — Sync all saved playlists

Runs option 2 against every playlist saved in Playlist Management, in order. Useful when triggered on a schedule.

### Option 4 — Open download folder

Opens the current download directory in Windows Explorer.

### Option 5 — Download dir

Displays and changes the active download directory. The new value is written to `mixtape_config.json` and persists across sessions.

### Option 6 — Tools

Opens the Tools submenu (see below).

### Option 7 — Exit

---

## Tools Submenu

```
Tools
────────────────────────────────────────
1. Retry failed downloads
2. Playlist management
3. Force reprocess a video
4. Archive stats
5. Back
```

### Retry failed downloads

Scans all playlist archives under the download directory and lists every entry with a `failed` status, along with the stored error message. You can retry a single entry by number, or enter `A` to retry all failures at once. The archive is updated after each retry attempt.

### Playlist management

Maintains a named list of playlist URLs used by "Sync all saved playlists."

- **Add** — enter a display name and URL; saved to `mixtape_config.json`
- **Remove** — select by number to delete from the list
- **List** — display all saved playlists with their URLs

Removing a playlist from this list does not delete its downloaded files or archive.

### Force reprocess a video

Re-downloads and re-splits a video that has already been processed. Select a playlist, then select a video from its archive. The existing archive entry is deleted before the download begins so the pipeline runs completely fresh. The previous split files are not automatically deleted — if you want a clean folder, remove them manually before reprocessing.

### Archive stats

Displays a summary table across all playlists:

```
Playlist                             Total  Split  Single  Failed  Last sync
──────────────────────────────────────────────────────────────────────────────
Late Night Jazz                         12     11       1       0  2026-05-10 14:32:01
Korean Piano Mixes                       4      3       0       1  2026-05-18 09:15:44
```

Failed counts are highlighted in red.

---

## Output Structure

```
downloads/
├── mixtape_config.json
├── Late Night Jazz Playlist/
│   ├── sync_archive.json
│   ├── Blue Hour Vol3 - Yawaraka Jazz/
│   │   ├── 01 - Thanks For The Memory - Serge Chaloff.mp3
│   │   ├── 02 - The Uptown - Junior Mance.mp3
│   │   └── Blue Hour Vol3 - Yawaraka Jazz.m3u8
│   └── Evening Sessions - Some Channel/
│       └── ...
└── Korean Piano Playlist/
    ├── sync_archive.json
    └── 들어본 적 없는 왈츠 모음집 - Niwamori Piano/
        └── ...
```

Each successfully split folder also contains an `.m3u8` playlist file listing the tracks in order.

---

## Archive Format

Each playlist folder contains a `sync_archive.json` file. It records every video that has been attempted, whether or not it succeeded.

```json
{
  "qP0dSxLOTEc": {
    "title": "들어본 적 없는 왈츠 모음집",
    "channel": "Niwamori Piano",
    "processed_at": "2026-05-18T09:15:44+00:00",
    "status": "split"
  },
  "b220vKEf2qE": {
    "title": "Horizon Pulse 2026",
    "channel": "Horizon Remixed",
    "processed_at": "2026-05-20T11:02:17+00:00",
    "status": "failed",
    "error": "Could not retrieve video metadata."
  }
}
```

Status values:

| Status | Meaning |
|---|---|
| `split` | Downloaded and split into individual tracks |
| `single` | Downloaded as one file; no timecodes were found |
| `failed` | An error occurred; `error` key contains the message |

To manually re-queue a video, delete its entry from the JSON and run a sync. The tool never modifies or removes existing audio files automatically.

---

## Config File

`mixtape_config.json` is created next to `mixtape_tool.py` on first run.

```json
{
  "output_dir": "./downloads",
  "playlists": [
    {
      "name": "Late Night Jazz",
      "url": "https://www.youtube.com/playlist?list=PLxxx"
    }
  ]
}
```

It is safe to edit by hand. If the file is missing or corrupted, defaults are used and a fresh file is written on the next save.

---

## Track Discovery

When processing a video, the tool attempts to find a tracklist in the following order, stopping at the first successful result:

1. **Official YouTube chapters** — embedded chapter data from the video itself. Most reliable when present.
2. **Video description** — parsed using the heuristic timecode parser in `mixtape_splitter`. Handles a wide range of timestamp formats.

If neither source yields tracks, the video is downloaded as a single uncut MP3 and recorded with status `single`.

---

## Filename Sanitization

All folder and track names pass through the sanitizer before being written to disk:

- Fullwidth Unicode characters (e.g. `｜`, `：`) are normalised to ASCII equivalents
- `&` is replaced with `and`
- Windows-illegal characters (`< > : " / \ | ? *`) are removed
- Periods and apostrophes are removed for compatibility with budget MP3 player firmware
- Consecutive spaces are collapsed
- Folder names are capped at 100 characters; track filenames at 120 characters

Emojis and non-Latin scripts (Korean, Japanese, Chinese, Arabic, etc.) are preserved.

---

## Windows PATH Length

Windows enforces a default maximum path length of 260 characters. With a deeply nested working directory this can become an issue. Two options:

**Enable long path support** (Windows 10/11): `Computer Configuration → Administrative Templates → System → Filesystem → Enable Win32 long paths`. Requires a reboot.

**Move the working directory closer to the root**, e.g. `C:\Music\` rather than a deeply nested project folder.

---

## Scheduling (Headless Mode)

The interactive menu is suppressed when running with `--video` or `--playlist` flags, making the tool suitable for Task Scheduler or other automation:

```
python "C:\Tools\mixtape_tool.py" --playlist "https://www.youtube.com/playlist?list=PLxxx" --output-dir "D:\Music"
```

For multi-playlist scheduled runs, use "Sync all saved playlists" by calling with no flags from a terminal context, or manage the saved list and call each URL separately in a batch file.
