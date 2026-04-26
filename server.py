import ftplib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, redirect, request
from twilio.rest import Client


BASE = Path("./vitasync_data")
CONFIG_FILE = BASE / "config.json"
LATEST = BASE / "latest"
BACKUPS = BASE / "backups"

CHECK_INTERVAL = 10


def load_config():
    if not CONFIG_FILE.exists():
        BASE.mkdir(parents=True, exist_ok=True)
        default = {
            "devices": {},
            "port": 1337,
            "remote_path": "ux0:/user/00/savedata",
            "mode": "manual",
            "sms_enabled": True,
            "twilio": {"sid": "", "token": "", "from": "", "to": ""},
            "backup_hours": 8,
            "storage_warn_mb": 28000,
        }
        CONFIG_FILE.write_text(json.dumps(default, indent=2))

    return json.loads(CONFIG_FILE.read_text())


def save_config():
    CONFIG_FILE.write_text(json.dumps(CONFIG, indent=2))


CONFIG = load_config()

state = {
    "last_backup": {},
    "pending": [],
    "notified": False,
    "status": "Idle",
}


def ping(ip):
    result = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True)
    return result.returncode == 0


def port_open(ip):
    try:
        with socket.create_connection((ip, CONFIG["port"]), timeout=2):
            return True
    except OSError:
        return False


def ftp_connect(ip):
    ftp = ftplib.FTP()
    ftp.connect(ip, CONFIG["port"], timeout=5)
    ftp.login()
    return ftp


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


def ftp_download_dir(ftp, local):
    """Recursively download the current FTP directory into local. Caller must cwd first."""
    local.mkdir(parents=True, exist_ok=True)
    lines = []
    ftp.retrlines("LIST", lines.append)
    for line in lines:
        name = line.split()[-1]
        if line.startswith("d"):
            ftp.cwd(name)
            ftp_download_dir(ftp, local / name)
            ftp.cwd("..")
        else:
            with open(local / name, "wb") as f:
                ftp.retrbinary(f"RETR {name}", f.write)


def ftp_upload_dir(ftp, local):
    """Recursively upload local into the current FTP directory. Caller must cwd first."""
    for item in Path(local).iterdir():
        if item.is_dir():
            try:
                ftp.mkd(item.name)
            except ftplib.error_perm:
                pass
            ftp.cwd(item.name)
            ftp_upload_dir(ftp, item)
            ftp.cwd("..")
        else:
            with open(item, "rb") as f:
                ftp.storbinary(f"STOR {item.name}", f)


def backup_device(name, ip):
    ftp = ftp_connect(ip)
    dest = LATEST / name
    dest.mkdir(parents=True, exist_ok=True)

    ftp.cwd(CONFIG["remote_path"])
    lines = []
    ftp.retrlines("LIST", lines.append)
    for line in lines:
        game = line.split()[-1]
        if line.startswith("d"):
            ftp.cwd(game)
            ftp_download_dir(ftp, dest / game)
            ftp.cwd("..")

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


def sync_loop():
    while True:
        ready = [name for name, ip in CONFIG["devices"].items() if ping(ip) and port_open(ip)]

        if len(ready) >= 2:
            state["status"] = "Devices ready"

            for name in ready:
                backup_device(name, CONFIG["devices"][name])

            actions = compare_saves()

            if actions:
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

        time.sleep(CHECK_INTERVAL)


app = Flask(__name__)


@app.route("/")
def index():
    used, total = disk_usage_mb()
    return f"""
    <h2>VitaSync</h2>
    <b>Status:</b> {state['status']}<br>
    <b>Mode:</b> {CONFIG['mode']}<br>
    <b>Devices:</b> {CONFIG['devices']}<br>
    <b>Pending:</b> {state['pending']}<br>
    <b>Disk:</b> {used}/{total}MB<br><br>
    <a href="/config">Config</a><br>
    <a href="/backups">Backups</a>
    """


@app.route("/backups")
def backups():
    items = os.listdir(BACKUPS) if BACKUPS.exists() else []
    return "<br>".join(items)


@app.route("/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        CONFIG["mode"] = request.form.get("mode", "manual")
        CONFIG["sms_enabled"] = "sms" in request.form
        CONFIG["devices"] = json.loads(request.form["devices"])
        CONFIG["twilio"]["sid"] = request.form["sid"]
        CONFIG["twilio"]["token"] = request.form["token"]
        CONFIG["twilio"]["from"] = request.form["from"]
        CONFIG["twilio"]["to"] = request.form["to"]
        save_config()
        return redirect("/config")

    sms_checked = "checked" if CONFIG["sms_enabled"] else ""
    return f"""
    <h3>Config</h3>
    <form method="post">
    Mode: <input name="mode" value="{CONFIG['mode']}"><br>
    SMS Enabled: <input type="checkbox" name="sms" {sms_checked}><br>
    Devices JSON:<br>
    <textarea name="devices" rows="5" cols="40">{json.dumps(CONFIG["devices"], indent=2)
    }</textarea><br>
    <h4>Twilio (stored in plaintext JSON)</h4>
    SID: <input name="sid" value="{CONFIG['twilio']['sid']}"><br>
    Token: <input name="token" value="{CONFIG['twilio']['token']}"><br>
    From: <input name="from" value="{CONFIG['twilio']['from']}"><br>
    To: <input name="to" value="{CONFIG['twilio']['to']}"><br>
    <button type="submit">Save</button>
    </form>
    """


@app.route("/sms", methods=["POST"])
def sms():
    msg = request.form.get("Body", "").lower()

    if msg == "y":
        run_sync()
        send_sms("Sync complete")
    elif msg == "auto":
        CONFIG["mode"] = "automatic-sync"
        save_config()
        send_sms("Auto mode enabled")
    elif msg == "manual":
        CONFIG["mode"] = "manual"
        save_config()
        send_sms("Manual mode enabled")

    return "OK"


if __name__ == "__main__":
    LATEST.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)

    threading.Thread(target=sync_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
