import json
import os

from flask import Flask, jsonify, redirect, request

from config import BACKUPS, CONFIG, save_config, state
from sync import disk_usage_mb, run_sync, send_sms

app = Flask(__name__)


@app.route("/")
def index():
    return """<!doctype html>
<html>
<head><title>VitaSync</title></head>
<body>
<h2>VitaSync</h2>
<p><b>Status:</b> <span id="status"></span></p>
<p><b>Mode:</b> <span id="mode"></span></p>
<p><b>Devices:</b> <span id="devices"></span></p>
<p><b>Pending:</b> <span id="pending"></span></p>
<p><b>Disk:</b> <span id="disk"></span></p>
<a href="/config">Config</a> | <a href="/backups">Backups</a>
<script>
function poll() {
    fetch("/api/status").then(r => r.json()).then(d => {
        document.getElementById("status").textContent = d.status;
        document.getElementById("mode").textContent = d.mode;
        document.getElementById("devices").textContent = JSON.stringify(d.devices);
        document.getElementById("pending").textContent = JSON.stringify(d.pending);
        document.getElementById("disk").textContent = d.disk_used + "/" + d.disk_total + "MB";
    });
}
poll();
setInterval(poll, 5000);
</script>
</body>
</html>"""


@app.route("/api/status")
def api_status():
    used, total = disk_usage_mb()
    return jsonify({
        "status": state["status"],
        "mode": CONFIG["mode"],
        "devices": CONFIG["devices"],
        "pending": [{"game": g, "src": s, "dst": d} for g, s, d in state["pending"]],
        "disk_used": used,
        "disk_total": total,
    })


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
