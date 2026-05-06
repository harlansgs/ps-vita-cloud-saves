import json
import os

from flask import Flask, jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import BACKUPS, CONFIG, save_config, state
from sync import disk_usage_mb, run_sync

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


@app.route("/")
def index():
    return f"""<!doctype html>
<html>
<head><title>VitaSync</title></head>
<body>
<h2>VitaSync</h2>
<p><b>Status:</b> <span id="status"></span></p>
<p><b>Mode:</b> <span id="mode"></span></p>
<p><b>Devices:</b> <span id="devices"></span></p>
<p><b>Pending:</b> <span id="pending"></span>
<button id="syncbtn" style="display:none" onclick="triggerSync()">Sync now</button></p>
<p><b>Disk:</b> <span id="disk"></span></p>
<a href="{url_for('config')}">Config</a> | <a href="{url_for('backups')}">Backups</a>
<script>
function triggerSync() {{
    fetch("{url_for('sync_now')}", {{method:"POST"}}).then(r => r.json()).then(d => alert(d.message));
}}
function poll() {{
    fetch("{url_for('api_status')}").then(r => r.json()).then(d => {{
        document.getElementById("status").textContent = d.status;
        document.getElementById("mode").textContent = d.mode;
        document.getElementById("devices").textContent = JSON.stringify(d.devices);
        document.getElementById("pending").textContent = JSON.stringify(d.pending);
        document.getElementById("disk").textContent = d.disk_used + "/" + d.disk_total + "MB";
        document.getElementById("syncbtn").style.display = d.pending.length ? "inline" : "none";
    }});
}}
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


@app.route("/sync", methods=["POST"])
def sync_now():
    if state["pending"]:
        run_sync()
        return jsonify({"ok": True, "message": "Sync triggered"})
    return jsonify({"ok": False, "message": "Nothing pending"})


@app.route("/backups")
def backups():
    items = os.listdir(BACKUPS) if BACKUPS.exists() else []
    return "<br>".join(items)


@app.route("/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        CONFIG["mode"] = request.form.get("mode", "manual")
        CONFIG["devices"] = json.loads(request.form["devices"])
        save_config()
        return redirect(url_for('config'))

    return f"""
    <h3>Config</h3>
    <form method="post">
    Mode: <select name="mode">
        <option value="manual"{"selected" if CONFIG["mode"] == "manual" else ""}>manual</option>
        <option value="automatic-sync"{"selected" if CONFIG["mode"] == "automatic-sync" else ""
        }>automatic-sync</option>
    </select><br>
    Devices JSON:<br>
    <textarea name="devices" rows="5" cols="40">{json.dumps(CONFIG["devices"], indent=2)
    }</textarea><br>
    <button type="submit">Save</button>
    </form>
    """
