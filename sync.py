import csv
import ftplib
import hashlib
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from config import BASE, BACKUPS, CHECK_INTERVAL, CONFIG, LATEST, state
from ftp import ftp_connect, ftp_download_dir, ftp_upload_dir

NPS_PSV_TSV = "https://nopaystation.com/tsv/PSV_GAMES.tsv"
GAME_IDS_CACHE = BASE / "psv_game_ids.txt"
BUNDLED_TSV = Path(__file__).parent / "data" / "psv_games.tsv"
GAME_ID_RE = re.compile(r"^[A-Z]{4}\d{5}$")
QUIET_THRESHOLD = 3        # consecutive waiting cycles before quiet mode
QUIET_LOG_INTERVAL = 3600  # seconds between log lines when in quiet mode

_game_ids: set = set()
_last_skipped: dict = {}  # device_name -> set of last-printed skipped dirs


def _parse_game_ids_tsv(content: str) -> set:
    ids = set()
    reader = csv.reader(content.splitlines(), delimiter="\t")
    next(reader, None)
    for row in reader:
        if row and GAME_ID_RE.match(row[0]):
            ids.add(row[0])
    return ids


def _fetch_game_ids() -> set:
    try:
        req = urllib.request.Request(NPS_PSV_TSV, headers={"User-Agent": "VitaSync/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
        ids = _parse_game_ids_tsv(content)
        GAME_IDS_CACHE.write_text("\n".join(sorted(ids)))
        print(f"Game ID database updated: {len(ids)} titles cached", flush=True)
        return ids
    except Exception as e:
        print(f"Warning: could not fetch game ID database: {e}", flush=True)
        return set()


def load_game_ids() -> set:
    global _game_ids
    if _game_ids:
        return _game_ids

    stale = not GAME_IDS_CACHE.exists() or (
        datetime.now() - datetime.fromtimestamp(GAME_IDS_CACHE.stat().st_mtime) > timedelta(days=7)
    )
    if stale:
        fetched = _fetch_game_ids()
        if fetched:
            _game_ids = fetched
            return _game_ids

    if GAME_IDS_CACHE.exists():
        _game_ids = set(GAME_IDS_CACHE.read_text().splitlines())
        print(f"Loaded {len(_game_ids)} game IDs from cache", flush=True)
        return _game_ids

    if BUNDLED_TSV.exists():
        _game_ids = _parse_game_ids_tsv(BUNDLED_TSV.read_text(encoding="utf-8"))
        print(f"Loaded {len(_game_ids)} game IDs from bundled TSV", flush=True)
        return _game_ids

    print("Warning: game ID database unavailable, falling back to regex filter", flush=True)
    return set()


def is_game_id(name: str, game_ids: set) -> bool:
    if game_ids:
        return name in game_ids
    return bool(GAME_ID_RE.match(name))


def ping(ip):
    result = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True)
    return result.returncode == 0


def port_open(ip, verbose=True):
    try:
        with socket.create_connection((ip, CONFIG["port"]), timeout=2):
            return True
    except OSError as e:
        if verbose:
            print(f"    ftp {ip}:{CONFIG['port']} error: {e}", flush=True)
        return False


def latest_mtime(path):
    mtimes = [
        os.path.getmtime(os.path.join(root, f))
        for root, _, files in os.walk(path)
        for f in files
    ]
    return max(mtimes) if mtimes else 0


def hash_save_tree(path: Path) -> str:
    h = hashlib.sha1()
    for fpath in sorted(path.rglob("*")):
        if fpath.is_file():
            h.update(fpath.relative_to(path).as_posix().encode())
            h.update(fpath.read_bytes())
    return h.hexdigest()


def disk_usage_mb():
    total, used, _ = shutil.disk_usage(BASE)
    return used // (1024 ** 2), total // (1024 ** 2)


def due_for_backup(name: str, current_hash: str) -> bool:
    last = state["last_backup"].get(name)
    last_hash = state["last_backup_hash"].get(name)
    if not last or not last_hash:
        return True
    if current_hash != last_hash:
        return True
    return datetime.now() - last > timedelta(hours=CONFIG["backup_hours"])


def backup_device(name, ip):
    game_ids = load_game_ids()
    ftp = ftp_connect(ip)
    dest = LATEST / name
    dest.mkdir(parents=True, exist_ok=True)
    ftp.cwd(CONFIG["remote_path"])

    lines = []
    ftp.retrlines("LIST", lines.append)
    skipped = []
    for line in lines:
        entry = line.split()[-1]
        if not line.startswith("d"):
            continue
        if not is_game_id(entry, game_ids):
            skipped.append(entry)
            continue
        ftp.cwd(entry)
        ftp_download_dir(ftp, dest / entry)
        ftp.cwd("..")

    skipped_set = set(skipped)
    if skipped_set and skipped_set != _last_skipped.get(name):
        print(f"  Skipped non-game dirs: {', '.join(sorted(skipped_set))}", flush=True)
        _last_skipped[name] = skipped_set

    for item in dest.iterdir():
        if item.is_dir() and not is_game_id(item.name, game_ids):
            shutil.rmtree(item)

    ftp.quit()

    current_hash = hash_save_tree(dest)
    if due_for_backup(name, current_hash):
        ts = datetime.now().strftime("%Y-%m-%d_%H")
        shutil.copytree(dest, BACKUPS / f"{name}_{ts}", dirs_exist_ok=True)
        state["last_backup"][name] = datetime.now()
        state["last_backup_hash"][name] = current_hash
    else:
        print(f"  Skipping backup for {name}: saves unchanged.", flush=True)


def compare_saves():
    actions = []
    game_ids = load_game_ids()
    devices = list(CONFIG["devices"].keys())

    for i in range(len(devices)):
        for j in range(i + 1, len(devices)):
            dev_a, dev_b = devices[i], devices[j]
            dir_a, dir_b = LATEST / dev_a, LATEST / dev_b
            games_a = {e for e in os.listdir(dir_a) if is_game_id(e, game_ids)} if dir_a.exists() else set()
            games_b = {e for e in os.listdir(dir_b) if is_game_id(e, game_ids)} if dir_b.exists() else set()

            for game in games_a | games_b:
                path_a, path_b = dir_a / game, dir_b / game
                mtime_a = latest_mtime(path_a) if path_a.exists() else 0
                mtime_b = latest_mtime(path_b) if path_b.exists() else 0

                if mtime_a > mtime_b:
                    actions.append((game, dev_a, dev_b))
                elif mtime_b > mtime_a:
                    actions.append((game, dev_b, dev_a))

    return actions


def run_sync():
    for game, src, dst in state["pending"]:
        ftp = ftp_connect(CONFIG["devices"][dst])
        ftp.cwd(CONFIG["remote_path"])
        try:
            ftp.mkd(game)
        except ftplib.error_perm:
            pass
        ftp.cwd(game)
        ftp_upload_dir(ftp, LATEST / src / game)
        ftp.quit()

    state["pending"] = []
    state["notified"] = False


def sync_loop(dry_run=False):
    waiting_streak = 0
    last_quiet_log = 0.0
    quiet = False
    prev_device_state = {}  # name -> (ping_ok, ftp_ok)

    while True:
        try:
            ready = []
            for name, ip in CONFIG["devices"].items():
                p, o = ping(ip), port_open(ip, verbose=not quiet)
                prev = prev_device_state.get(name)
                cur = (p, o)
                if cur != prev:
                    print(
                        f"  {name} ({ip}): ping={'ok' if p else 'fail'}, ftp={'ok' if o else 'fail'}",
                        flush=True,
                    )
                    prev_device_state[name] = cur
                    if quiet:
                        last_quiet_log = time.monotonic()
                elif not quiet:
                    print(f"  {name} ({ip}): ping={'ok' if p else 'fail'}, ftp={'ok' if o else 'fail'}",
                          flush=True)
                if p and o:
                    ready.append(name)

            if len(ready) >= 2:
                if quiet:
                    print("Devices online, resuming normal logging.", flush=True)
                quiet = False
                waiting_streak = 0
                state["status"] = "Devices ready"

                for name in ready:
                    print(f"Backing up {name}...", flush=True)
                    backup_device(name, CONFIG["devices"][name])

                actions = compare_saves()

                if dry_run:
                    if actions:
                        print("Dry-run: would sync:", flush=True)
                        for game, src, dst in actions:
                            print(f"  {game}: {src} -> {dst}", flush=True)
                    else:
                        print("Dry-run: saves are in sync, nothing to do", flush=True)
                elif actions:
                    summary = "\n".join(f"{g}: {s} -> {d}" for g, s, d in actions)

                    if CONFIG["mode"] == "automatic-sync":
                        state["pending"] = actions
                        run_sync()
                        print(f"Auto sync complete:\n{summary}", flush=True)
                    elif not state["notified"]:
                        state["pending"] = actions
                        state["notified"] = True
                        print(f"Sync needed (manual mode):\n{summary}", flush=True)
            else:
                waiting_streak += 1
                state["status"] = "Waiting for devices"

                if waiting_streak == QUIET_THRESHOLD:
                    quiet = True
                    last_quiet_log = time.monotonic()
                    print(
                        "Continuing polling, but will only report on 1hr schedule "
                        "to reduce log spam...",
                        flush=True,
                    )
                elif not quiet:
                    print(f"Waiting ({len(ready)}/{len(CONFIG['devices'])} devices ready)", flush=True)
                elif time.monotonic() - last_quiet_log >= QUIET_LOG_INTERVAL:
                    print(f"Still waiting ({len(ready)}/{len(CONFIG['devices'])} devices ready)", flush=True)
                    last_quiet_log = time.monotonic()

        except Exception as e:
            print(f"sync_loop error: {e}", flush=True)

        time.sleep(CHECK_INTERVAL)
