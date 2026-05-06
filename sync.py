import os
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta

from twilio.rest import Client

from config import BASE, BACKUPS, CHECK_INTERVAL, CONFIG, LATEST, state
from ftp import ftp_connect, ftp_download_dir, ftp_upload_dir


def ping(ip):
    result = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True)
    return result.returncode == 0


def port_open(ip):
    try:
        with socket.create_connection((ip, CONFIG["port"]), timeout=2):
            return True
    except OSError as e:
        print(f"    ftp {ip}:{CONFIG['port']} error: {e}")
        return False


def latest_mtime(path):
    mtimes = [
        os.path.getmtime(os.path.join(root, f))
        for root, _, files in os.walk(path)
        for f in files
    ]
    return max(mtimes) if mtimes else 0


def disk_usage_mb():
    total, used, _ = shutil.disk_usage(BASE)
    return used // (1024 ** 2), total // (1024 ** 2)


def due_for_backup(name):
    last = state["last_backup"].get(name)
    return not last or datetime.now() - last > timedelta(hours=CONFIG["backup_hours"])


def send_sms(msg):
    if not CONFIG["sms_enabled"]:
        return
    t = CONFIG["twilio"]
    Client(t["sid"], t["token"]).messages.create(body=msg, from_=t["from"], to=t["to"])


def backup_device(name, ip):
    ftp = ftp_connect(ip)
    dest = LATEST / name
    dest.mkdir(parents=True, exist_ok=True)
    ftp.cwd(CONFIG["remote_path"])
    ftp_download_dir(ftp, dest)
    ftp.quit()

    if due_for_backup(name):
        ts = datetime.now().strftime("%Y-%m-%d_%H")
        shutil.copytree(dest, BACKUPS / f"{name}_{ts}", dirs_exist_ok=True)
        state["last_backup"][name] = datetime.now()


def compare_saves():
    """Return list of (game, src_device, dst_device) where src has a newer save than dst."""
    actions = []
    devices = list(CONFIG["devices"].keys())

    for i in range(len(devices)):
        for j in range(i + 1, len(devices)):
            dev_a, dev_b = devices[i], devices[j]
            dir_a, dir_b = LATEST / dev_a, LATEST / dev_b
            games_a = set(os.listdir(dir_a)) if dir_a.exists() else set()
            games_b = set(os.listdir(dir_b)) if dir_b.exists() else set()

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
        ftp.cwd(game)
        ftp_upload_dir(ftp, LATEST / src / game)
        ftp.quit()

    state["pending"] = []
    state["notified"] = False


def sync_loop(dry_run=False):
    while True:
        try:
            ready = []
            for name, ip in CONFIG["devices"].items():
                p, o = ping(ip), port_open(ip)
                print(f"  {name} ({ip}): ping={'ok' if p else 'fail'}, ftp={'ok' if o else 'fail'}", flush=True)
                if p and o:
                    ready.append(name)

            if len(ready) >= 2:
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
                    used, total = disk_usage_mb()

                    if CONFIG["mode"] == "automatic-sync":
                        state["pending"] = actions
                        run_sync()
                        send_sms(f"AUTO SYNC DONE\n{summary}\n{used}/{total}MB")
                    elif not state["notified"]:
                        state["pending"] = actions
                        send_sms(f"{summary}\nReply Y to sync\nMode: {CONFIG['mode']}")
                        state["notified"] = True
            else:
                state["status"] = "Waiting for devices"
                print(f"Waiting ({len(ready)}/{len(CONFIG['devices'])} devices ready)", flush=True)

        except Exception as e:
            print(f"sync_loop error: {e}", flush=True)

        time.sleep(CHECK_INTERVAL)
