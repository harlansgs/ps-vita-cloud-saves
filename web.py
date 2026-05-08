import html
import io
import ipaddress
import json
import os
import zipfile

from flask import Flask, jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import BACKUPS, CONFIG, save_config, state
from sync import disk_usage_mb, port_open, run_sync

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

VALID_MODES = {"manual", "automatic-sync"}


def _valid_devices(devices):
    if not isinstance(devices, dict):
        return False
    for k, v in devices.items():
        if not isinstance(k, str) or not k:
            return False
        try:
            ipaddress.ip_address(v)
        except ValueError:
            return False
    return True


COMMON_STYLE = """
*, *::before, *::after { box-sizing: border-box; }
body { font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px;
       background: #fff; color: #000; }
h1, h2 { margin-bottom: 4px; }
a { color: #00e; }
button { background: #000; color: #fff; border: none; padding: 6px 14px;
         cursor: pointer; font-size: 14px; }
button:hover { background: #333; }
p.nav { margin-top: 32px; font-size: 14px; }
"""


@app.route("/")
def index():
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VitaSync</title>
  <style>{COMMON_STYLE}</style>
</head>
<body>
<h2>VitaSync</h2>
<p><b>Status:</b> <span id="status"></span></p>
<p><b>Mode:</b> <span id="mode"></span></p>
<p><b>Devices:</b> <span id="devices"></span></p>
<p><b>Pending:</b> <span id="pending"></span></p>
<p><b>Disk:</b> <span id="disk"></span></p>
<p><button onclick="openSyncDlg()">Sync...</button></p>
<dialog id="syncdlg">
  <div id="dlgbody"></div>
  <div id="dlgactions"></div>
</dialog>
<p class="nav"><a href="/">Home</a> | <a href="{url_for('config')}">Config</a> | <a href="{url_for('backups')}">Backups</a></p>
<script>
var _pending = [];
function closeSyncDlg() {{ document.getElementById("syncdlg").close(); }}
function openSyncDlg() {{
    var body = document.getElementById("dlgbody");
    var actions = document.getElementById("dlgactions");
    var dlg = document.getElementById("syncdlg");
    if (_pending.length === 0) {{
        body.textContent = "All saves are in sync.";
        actions.innerHTML = '<button onclick="closeSyncDlg()">Close</button>';
    }} else {{
        body.innerHTML = _pending.map(function(p) {{
            return "<p>" + p.game + ": " + p.src + " -&gt; " + p.dst + "</p>";
        }}).join("");
        actions.innerHTML = '<button onclick="doSync()">Sync</button> <button onclick="closeSyncDlg()">Cancel</button>';
    }}
    dlg.showModal();
}}
function doSync() {{
    fetch("{url_for('sync_now')}", {{method:"POST"}})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
            if (d.ok) {{
                closeSyncDlg();
            }} else {{
                document.getElementById("dlgbody").textContent = d.message;
                document.getElementById("dlgactions").innerHTML = '<button onclick="closeSyncDlg()">Close</button>';
            }}
        }});
}}
function poll() {{
    fetch("{url_for('api_status')}").then(r => r.json()).then(d => {{
        _pending = d.pending;
        document.getElementById("status").textContent = d.status;
        document.getElementById("mode").textContent = d.mode;
        document.getElementById("devices").textContent = JSON.stringify(d.devices);
        document.getElementById("pending").textContent = d.pending.length ? d.pending.length + " pending" : "none";
        document.getElementById("disk").textContent = d.disk_used + "/" + d.disk_total + "MB";
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
    if not state["pending"]:
        return jsonify({"ok": False, "message": "Nothing pending"})
    dst_names = {dst for _, _, dst in state["pending"]}
    offline = sorted(n for n in dst_names if not port_open(CONFIG["devices"][n], verbose=False))
    if offline:
        return jsonify({"ok": False, "message": f"Device(s) offline: {', '.join(offline)}"})
    run_sync()
    return jsonify({"ok": True, "message": "Sync complete"})


@app.route("/backups")
def backups():
    items = sorted(os.listdir(BACKUPS)) if BACKUPS.exists() else []
    rows = "".join(
        f'<p><a href="{url_for("backup_detail", snapshot=item)}">{html.escape(item)}</a></p>'
        for item in items
    ) or "<p>No backups yet.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VitaSync - Backups</title>
  <style>{COMMON_STYLE}</style>
</head>
<body>
<h2>Backups</h2>
{rows}
<p class="nav"><a href="/">Home</a> | <a href="{url_for('index')}">VitaSync</a> | <a href="{url_for('config')}">Config</a></p>
</body>
</html>"""


@app.route("/backups/<snapshot>")
def backup_detail(snapshot):
    snap_path = (BACKUPS / snapshot).resolve()
    if snap_path.parent != BACKUPS.resolve() or not snap_path.is_dir():
        return "Not found", 404
    games = sorted(p.name for p in snap_path.iterdir() if p.is_dir())
    rows = "".join(
        f'<p><a href="{url_for("backup_download", snapshot=snapshot, game=game)}">'
        f'{html.escape(game)}</a></p>'
        for game in games
    ) or "<p>No saves in this backup.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VitaSync - {html.escape(snapshot)}</title>
  <style>{COMMON_STYLE}</style>
</head>
<body>
<h2>{html.escape(snapshot)}</h2>
{rows}
<p class="nav"><a href="/">Home</a> | <a href="{url_for('index')}">VitaSync</a> | <a href="{url_for('backups')}">Backups</a></p>
</body>
</html>"""


@app.route("/backups/<snapshot>/<game>")
def backup_download(snapshot, game):
    snap_path = (BACKUPS / snapshot).resolve()
    game_path = (snap_path / game).resolve()
    if (snap_path.parent != BACKUPS.resolve() or game_path.parent != snap_path
            or not game_path.is_dir()):
        return "Not found", 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(game_path.rglob("*")):
            if fpath.is_file():
                zf.write(fpath, fpath.relative_to(game_path))
    buf.seek(0)
    filename = f"{snapshot}_{game}.zip"
    return app.response_class(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/config", methods=["GET", "POST"])
def config():
    error = None
    if request.method == "POST":
        mode = request.form.get("mode", "manual")
        if mode not in VALID_MODES:
            mode = "manual"
        try:
            devices = json.loads(request.form["devices"])
        except (json.JSONDecodeError, KeyError):
            devices = None
            error = "Invalid JSON in devices field."
        if devices and not _valid_devices(devices):
            error = 'Devices must be {"name": "ip"} pairs, e.g. {"Vita": "192.168.1.10"}.'
        if not error:
            CONFIG["mode"] = mode
            CONFIG["devices"] = devices
            save_config()
            return redirect(url_for('config'))

    devices_json = html.escape(json.dumps(CONFIG["devices"], indent=2))
    error_html = f'<p style="color:red">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VitaSync - Config</title>
  <style>{COMMON_STYLE}
    select, textarea {{ font-family: monospace; font-size: 14px; border: 1px solid #ccc; padding: 4px; }}
    label {{ display: block; margin: 12px 0 4px; }}
  </style>
</head>
<body>
<h2>Config</h2>
{error_html}
<form method="post">
  <label>Mode:
    <select name="mode">
      <option value="manual"{" selected" if CONFIG["mode"] == "manual" else ""}>manual</option>
      <option value="automatic-sync"{" selected" if CONFIG["mode"] == "automatic-sync" else ""}>automatic-sync</option>
    </select>
  </label>
  <label>Devices JSON:</label>
  <textarea name="devices" rows="5" cols="40">{devices_json}</textarea>
  <p><button type="submit">Save</button></p>
</form>
<p class="nav"><a href="/">Home</a> | <a href="{url_for('index')}">VitaSync</a> | <a href="{url_for('backups')}">Backups</a></p>
</body>
</html>"""
