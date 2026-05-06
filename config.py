import json
from pathlib import Path

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
    "last_backup_hash": {},
    "pending": [],
    "notified": False,
    "status": "Idle",
}
