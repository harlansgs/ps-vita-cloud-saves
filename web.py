import json
import os

from flask import Flask, redirect, request

from config import BACKUPS, CONFIG, save_config, state
from sync import disk_usage_mb, run_sync, send_sms

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
