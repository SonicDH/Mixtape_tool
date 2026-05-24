#!/usr/bin/env python3
"""
mixtape_tool.py
----------------
Unified CLI tool for:
    1. Processing a single YouTube mixtape video
    2. Syncing an entire YouTube playlist

Features:
    - Official YouTube chapter support
    - Description fallback parsing
    - Playlist archive tracking with retry/reprocess
    - Livestream rejection
    - Retro interactive menu when launched without args

Config is stored in mixtape_config.json next to this script.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import mixtape_splitter as splitter


# ---------------------------------------------------------------------------
# ANSI styling
# ---------------------------------------------------------------------------

RESET   = '\033[0m'
CYAN    = '\033[96m'
MAGENTA = '\033[95m'
YELLOW  = '\033[93m'
GREEN   = '\033[92m'
RED     = '\033[91m'
WHITE   = '\033[97m'
DIM     = '\033[2m'
BOLD    = '\033[1m'


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / 'mixtape_config.json'

DEFAULT_CONFIG = {
    'output_dir': './downloads',
    'playlists':  [],          # [{'name': str, 'url': str}]
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg = json.load(f)
                # Back-fill any keys added after first run
                for k, v in DEFAULT_CONFIG.items():
                    cfg.setdefault(k, v)
                return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Archive helpers
# ---------------------------------------------------------------------------


def load_archive(archive_path: Path) -> dict:
    if archive_path.exists():
        try:
            with open(archive_path, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print(f'⚠️  Could not read archive: {archive_path}')
    return {}


def save_archive(archive: dict, archive_path: Path):
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


def find_all_archives(output_base: Path) -> list[Path]:
    """Return all sync_archive.json files under output_base."""
    return sorted(output_base.glob('*/sync_archive.json'))


# ---------------------------------------------------------------------------
# Interactive menu helpers
# ---------------------------------------------------------------------------


def interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def clear_screen():
    print('\033[2J\033[H', end='')


def pause():
    input(f'\n{DIM}Press ENTER to continue...{RESET}')


def prompt(label: str) -> str:
    return input(f'{YELLOW}{label}:{RESET} ').strip()


def numbered_menu(title: str, options: list[str]) -> str:
    """
    Print a titled numbered menu and return the user's stripped input.
    options is a list of label strings; the last one is always treated as Back/Exit.
    """
    print(f'\n{CYAN}{BOLD}{title}{RESET}')
    print(f'{DIM}{"─" * 40}{RESET}')
    for i, opt in enumerate(options, 1):
        colour = RED if i == len(options) else MAGENTA
        print(f'{colour}{i}.{RESET} {opt}')
    print()
    return input(f'{YELLOW}Select:{RESET} ').strip()


# ---------------------------------------------------------------------------
# Playlist fetching
# ---------------------------------------------------------------------------


def fetch_playlist(url: str) -> tuple[str, list[dict]]:
    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--dump-single-json',
        '--no-warnings',
        url,
    ]

    result = subprocess.run(cmd, capture_output=True)

    if result.returncode != 0:
        err = result.stderr.decode('utf-8', errors='replace')
        raise RuntimeError(f'yt-dlp failed fetching playlist:\n{err}')

    data = json.loads(result.stdout.decode('utf-8', errors='replace'))

    playlist_name = splitter.clean_title(
        data.get('title') or data.get('id') or 'Unknown Playlist'
    )

    videos = []
    for entry in data.get('entries') or []:
        vid_id = entry.get('id')
        if not vid_id:
            continue
        videos.append({
            'id':      vid_id,
            'title':   entry.get('title', vid_id),
            'channel': entry.get('uploader') or entry.get('channel', ''),
            'url':     f'https://www.youtube.com/watch?v={vid_id}',
        })

    return playlist_name, videos


# ---------------------------------------------------------------------------
# Video processing core
# ---------------------------------------------------------------------------


def process_single_video(
    url: str,
    output_base: Path,
    keep_original: bool,
    playlist_dir: Path | None = None,
) -> str:
    """
    Download and split one video. Returns 'split' or 'single'.
    Raises RuntimeError on unrecoverable problems.
    """
    print(f"\n{'═' * 60}")
    print(f'🎵  Processing video')
    print(f'🔗  {url}\n')

    info = splitter.get_video_info(url)

    if not info:
        raise RuntimeError('Could not retrieve video metadata.')

    if info.get('is_live') or info.get('live_status') == 'is_live':
        raise RuntimeError('Livestreams are not supported.')

    description   = info.get('description', '')
    video_title   = info.get('title', 'Unknown Video')
    video_channel = info.get('channel', '')

    folder_name = splitter.make_folder_name(video_title, video_channel)
    output_dir  = (playlist_dir / folder_name) if playlist_dir else (output_base / folder_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Track discovery: chapters → description
    tracks = splitter.extract_chapters(info)

    if tracks:
        print(f'✅  Found {len(tracks)} official YouTube chapters.')

    if not tracks:
        print('⚠️  No official chapters — parsing description...')
        tracks = splitter.extract_tracks(description)

    if tracks:
        print(f'📋  {len(tracks)} tracks found.')
    else:
        print('⚠️  No tracks found — saving as single file.')

    mp3_path = splitter.download_audio(url, output_dir)
    print(f'💾  Downloaded: {mp3_path.name}')

    if tracks:
        splitter.split_audio(mp3_path, tracks, output_dir)
        if not keep_original:
            mp3_path.unlink(missing_ok=True)
            print('🗑   Removed original full-length MP3.')
        return 'split'

    return 'single'


# ---------------------------------------------------------------------------
# Playlist sync
# ---------------------------------------------------------------------------


def sync_playlist(
    url: str,
    output_base: Path,
    keep_original: bool,
    dry_run: bool,
    force_ids: set | None = None,
):
    """
    Sync a playlist URL. force_ids bypasses the archive check for specific video IDs.
    """
    print(f"\n{'═' * 60}")
    print(f'🎵  Playlist sync')
    print(f'🔗  {url}\n')

    playlist_name, videos = fetch_playlist(url)

    playlist_dir = output_base / playlist_name
    playlist_dir.mkdir(parents=True, exist_ok=True)

    archive_path = playlist_dir / 'sync_archive.json'
    archive      = load_archive(archive_path)

    force_ids  = force_ids or set()
    new_videos = [
        v for v in videos
        if v['id'] not in archive or v['id'] in force_ids
    ]

    archived_count = len(archive)
    failed_count   = sum(1 for e in archive.values() if e.get('status') == 'failed')
    last_sync      = max(
        (e.get('processed_at', '') for e in archive.values()),
        default=None,
    )

    print(f'📂  Playlist  : {playlist_name}')
    print(f'🎞   Total     : {len(videos)}')
    print(f'📦  Archived  : {archived_count}  ({failed_count} failed)')
    print(f'🕒  Last sync : {last_sync or "never"}')
    print(f'🆕  To process: {len(new_videos)}')

    if not new_videos:
        print('\n✅  Playlist already up to date.')
        return

    if dry_run:
        print(f'\n{DIM}{"─" * 40}{RESET}')
        print('🧪  Dry run — would process:\n')
        for v in new_videos:
            flag = f'{YELLOW}[RETRY]{RESET} ' if v['id'] in force_ids else ''
            status = archive.get(v['id'], {}).get('status', 'new')
            print(f'  {flag}{v["title"]}  {DIM}[{status}]{RESET}')
        return

    results = {'split': 0, 'single': 0, 'failed': 0}

    for idx, video in enumerate(new_videos, 1):
        print(f'\n{DIM}─── [{idx}/{len(new_videos)}]{RESET} {video["title"]}')

        try:
            status = process_single_video(
                video['url'],
                output_base,
                keep_original,
                playlist_dir=playlist_dir,
            )
            results[status] += 1
            archive[video['id']] = {
                'title':        video['title'],
                'channel':      video['channel'],
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'status':       status,
            }

        except Exception as e:
            print(f'✗  Failed: {e}')
            results['failed'] += 1
            archive[video['id']] = {
                'title':        video['title'],
                'channel':      video['channel'],
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'status':       'failed',
                'error':        str(e),
            }

        save_archive(archive, archive_path)

    print(f"\n✅  Done.  Split: {results['split']}  |  Single: {results['single']}  |  Failed: {results['failed']}")


# ---------------------------------------------------------------------------
# Tools submenu actions
# ---------------------------------------------------------------------------


def action_retry_failed(output_base: Path):
    """Find all failed entries across all archives and offer to retry them."""
    archives = find_all_archives(output_base)

    if not archives:
        print('\nNo archives found.')
        pause()
        return

    # Collect failed entries
    failed = []   # [(archive_path, video_id, entry)]
    for ap in archives:
        archive = load_archive(ap)
        for vid_id, entry in archive.items():
            if entry.get('status') == 'failed':
                failed.append((ap, vid_id, entry))

    if not failed:
        print(f'\n{GREEN}No failed entries found across any playlist.{RESET}')
        pause()
        return

    print(f'\n{YELLOW}Failed entries:{RESET}\n')
    for i, (ap, vid_id, entry) in enumerate(failed, 1):
        playlist = ap.parent.name
        print(f'  {MAGENTA}{i}.{RESET} [{playlist}] {entry["title"]}')
        if entry.get('error'):
            print(f'     {DIM}{entry["error"]}{RESET}')

    print(f'\n  {MAGENTA}A.{RESET} Retry all')
    print(f'  {RED}B.{RESET} Cancel\n')

    choice = input(f'{YELLOW}Select:{RESET} ').strip().upper()

    if choice == 'B':
        return

    to_retry = failed if choice == 'A' else []
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(failed):
            to_retry = [failed[idx]]

    if not to_retry:
        print('Invalid selection.')
        pause()
        return

    for ap, vid_id, entry in to_retry:
        url = f'https://www.youtube.com/watch?v={vid_id}'
        print(f'\n▶  Retrying: {entry["title"]}')
        archive = load_archive(ap)
        try:
            status = process_single_video(url, output_base, keep_original=False, playlist_dir=ap.parent)
            archive[vid_id] = {
                'title':        entry['title'],
                'channel':      entry.get('channel', ''),
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'status':       status,
            }
        except Exception as e:
            print(f'✗  Still failed: {e}')
            archive[vid_id]['error'] = str(e)
        save_archive(archive, ap)

    pause()


def action_archive_stats(output_base: Path):
    """Print a stats summary for every playlist archive found."""
    archives = find_all_archives(output_base)

    if not archives:
        print('\nNo archives found.')
        pause()
        return

    print(f'\n{CYAN}{BOLD}Archive Stats{RESET}\n')
    print(f'{"Playlist":<35} {"Total":>6} {"Split":>6} {"Single":>7} {"Failed":>7} {"Last sync":<25}')
    print(DIM + '─' * 90 + RESET)

    for ap in archives:
        archive = load_archive(ap)
        total  = len(archive)
        split  = sum(1 for e in archive.values() if e.get('status') == 'split')
        single = sum(1 for e in archive.values() if e.get('status') == 'single')
        failed = sum(1 for e in archive.values() if e.get('status') == 'failed')
        last   = max((e.get('processed_at', '') for e in archive.values()), default='—')
        # Trim to date+time, drop microseconds
        last   = last[:19].replace('T', ' ') if last != '—' else '—'
        name   = ap.parent.name[:34]
        failed_col = (RED + str(failed) + RESET) if failed else str(failed)
        print(f'{name:<35} {total:>6} {split:>6} {single:>7} {failed_col:>7} {last:<25}')

    pause()


def action_force_reprocess(output_base: Path):
    """Pick a playlist, pick a video, wipe its archive entry, re-download."""
    archives = find_all_archives(output_base)

    if not archives:
        print('\nNo archives found.')
        pause()
        return

    # Step 1: pick playlist
    print(f'\n{YELLOW}Select playlist:{RESET}\n')
    for i, ap in enumerate(archives, 1):
        archive = load_archive(ap)
        print(f'  {MAGENTA}{i}.{RESET} {ap.parent.name}  {DIM}({len(archive)} videos){RESET}')
    print(f'  {RED}{len(archives)+1}.{RESET} Cancel\n')

    choice = input(f'{YELLOW}Select:{RESET} ').strip()
    if not choice.isdigit() or int(choice) == len(archives) + 1:
        return

    idx = int(choice) - 1
    if not (0 <= idx < len(archives)):
        return

    ap      = archives[idx]
    archive = load_archive(ap)
    entries = list(archive.items())   # [(vid_id, entry)]

    # Step 2: pick video
    print(f'\n{YELLOW}Select video to reprocess:{RESET}\n')
    for i, (vid_id, entry) in enumerate(entries, 1):
        status_col = (RED + entry.get('status','?') + RESET) if entry.get('status') == 'failed' else DIM + entry.get('status','?') + RESET
        print(f'  {MAGENTA}{i}.{RESET} {entry["title"]}  [{status_col}]')
    print(f'  {RED}{len(entries)+1}.{RESET} Cancel\n')

    choice2 = input(f'{YELLOW}Select:{RESET} ').strip()
    if not choice2.isdigit() or int(choice2) == len(entries) + 1:
        return

    vidx = int(choice2) - 1
    if not (0 <= vidx < len(entries)):
        return

    vid_id, entry = entries[vidx]
    url = f'https://www.youtube.com/watch?v={vid_id}'

    print(f'\n▶  Reprocessing: {entry["title"]}')

    # Remove from archive so process_single_video runs fresh
    del archive[vid_id]
    save_archive(archive, ap)

    try:
        status = process_single_video(url, output_base, keep_original=False, playlist_dir=ap.parent)
        archive[vid_id] = {
            'title':        entry['title'],
            'channel':      entry.get('channel', ''),
            'processed_at': datetime.now(timezone.utc).isoformat(),
            'status':       status,
        }
    except Exception as e:
        print(f'✗  Failed: {e}')
        archive[vid_id] = {**entry, 'status': 'failed', 'error': str(e)}

    save_archive(archive, ap)
    pause()


def action_playlist_management(cfg: dict):
    """Add, remove, and list saved playlists."""
    while True:
        playlists = cfg.get('playlists', [])

        choice = numbered_menu(
            'Playlist Management',
            ['Add playlist', 'Remove playlist', 'List saved playlists', 'Back'],
        )

        if choice == '1':
            name = prompt('Playlist name')
            url  = prompt('Playlist URL')
            if name and url:
                playlists.append({'name': name, 'url': url})
                cfg['playlists'] = playlists
                save_config(cfg)
                print(f'{GREEN}✓ Saved.{RESET}')
            pause()

        elif choice == '2':
            if not playlists:
                print('\nNo saved playlists.')
                pause()
                continue

            print()
            for i, pl in enumerate(playlists, 1):
                print(f'  {MAGENTA}{i}.{RESET} {pl["name"]}  {DIM}{pl["url"]}{RESET}')
            print(f'  {RED}{len(playlists)+1}.{RESET} Cancel\n')

            sel = input(f'{YELLOW}Remove #{RESET}: ').strip()
            if sel.isdigit():
                ridx = int(sel) - 1
                if 0 <= ridx < len(playlists):
                    removed = playlists.pop(ridx)
                    cfg['playlists'] = playlists
                    save_config(cfg)
                    print(f'{GREEN}✓ Removed: {removed["name"]}{RESET}')
            pause()

        elif choice == '3':
            if not playlists:
                print('\nNo saved playlists.')
            else:
                print()
                for i, pl in enumerate(playlists, 1):
                    print(f'  {i}. {pl["name"]}')
                    print(f'     {DIM}{pl["url"]}{RESET}')
            pause()

        elif choice == '4':
            break


# ---------------------------------------------------------------------------
# Tools submenu
# ---------------------------------------------------------------------------


def tools_menu(cfg: dict, output_base: Path):
    while True:
        choice = numbered_menu(
            'Tools',
            [
                'Retry failed downloads',
                'Playlist management',
                'Force reprocess a video',
                'Archive stats',
                'Back',
            ],
        )

        if choice == '1':
            action_retry_failed(output_base)

        elif choice == '2':
            action_playlist_management(cfg)

        elif choice == '3':
            action_force_reprocess(output_base)

        elif choice == '4':
            action_archive_stats(output_base)

        elif choice == '5':
            break


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------


def draw_main_menu(cfg: dict):
    clear_screen()
    print(f'{CYAN}{BOLD}')
    print('╔══════════════════════════════════════╗')
    print('║          MIXTAPE TOOL v1.1           ║')
    print('╚══════════════════════════════════════╝')
    print(f'{RESET}')
    print(f'{MAGENTA}1.{RESET} Process single video')
    print(f'{MAGENTA}2.{RESET} Sync playlist')
    print(f'{MAGENTA}3.{RESET} Sync all saved playlists  {DIM}({len(cfg.get("playlists", []))} saved){RESET}')
    print(f'{MAGENTA}4.{RESET} Open download folder')
    print(f'{MAGENTA}5.{RESET} Download dir: {YELLOW}{cfg["output_dir"]}{RESET}')
    print(f'{MAGENTA}6.{RESET} Tools')
    print(f'{RED}7.{RESET} Exit')
    print()


def interactive_menu(cfg: dict):
    while True:
        draw_main_menu(cfg)
        output_base = Path(cfg['output_dir'])

        choice = input(f'{YELLOW}Select:{RESET} ').strip()

        if choice == '1':
            url = prompt('\nVideo URL')
            if url:
                try:
                    process_single_video(url, output_base, keep_original=False)
                except Exception as e:
                    print(f'\n{RED}Error: {e}{RESET}')
            pause()

        elif choice == '2':
            url = prompt('\nPlaylist URL')
            if url:
                try:
                    sync_playlist(url, output_base, keep_original=False, dry_run=False)
                except Exception as e:
                    print(f'\n{RED}Error: {e}{RESET}')
            pause()

        elif choice == '3':
            playlists = cfg.get('playlists', [])
            if not playlists:
                print(f'\n{YELLOW}No saved playlists. Add some via Tools → Playlist Management.{RESET}')
            else:
                for pl in playlists:
                    print(f'\n▶  {pl["name"]}')
                    try:
                        sync_playlist(pl['url'], output_base, keep_original=False, dry_run=False)
                    except Exception as e:
                        print(f'{RED}Error: {e}{RESET}')
            pause()

        elif choice == '4':
            output_base.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(['explorer.exe', str(output_base.resolve())])

        elif choice == '5':
            new_dir = prompt(f'\nNew download directory (current: {cfg["output_dir"]})')
            if new_dir:
                cfg['output_dir'] = new_dir
                save_config(cfg)
                print(f'{GREEN}✓ Saved.{RESET}')
            pause()

        elif choice == '6':
            tools_menu(cfg, output_base)

        elif choice == '7':
            print('\nGoodbye.\n')
            sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description='Mixtape processing utility')

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--video',    '-v', help='Process a single YouTube video URL')
    mode.add_argument('--playlist', '-p', help='Sync a YouTube playlist URL')

    parser.add_argument('--output-dir',    '-o', default=None,          help='Output directory')
    parser.add_argument('--keep-original', action='store_true',          help='Keep unsplit full-length MPs')
    parser.add_argument('--dry-run',       action='store_true',          help='Preview playlist sync without downloading')

    args = parser.parse_args()

    cfg         = load_config()
    output_base = Path(args.output_dir or cfg['output_dir'])

    if not args.video and not args.playlist:
        if interactive_terminal():
            interactive_menu(cfg)
        else:
            parser.print_usage()
            sys.exit('\nError: expected --video or --playlist URL')
        return

    if args.video:
        process_single_video(args.video, output_base, args.keep_original)

    elif args.playlist:
        sync_playlist(args.playlist, output_base, args.keep_original, args.dry_run)


if __name__ == '__main__':
    main()