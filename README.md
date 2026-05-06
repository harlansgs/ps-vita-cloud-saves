# Vita "cloud" saves server [VCS]

A poor man's cloud saves for PS Vita / PS TV consoles.

Open VitaShell -> Network -> FTP server on each console you want to sync.
VitaSync detects them on the network, pulls saves from each, and pushes
the most recent version of each game's save to any device that is behind.

Saves are validated against the NoPayStation game database so only real
game saves are synced -- homebrew and utility directories are ignored.
A local backup snapshot is kept and only updated when save content actually
changes, so identical snapshots do not accumulate.

## Setup

```sh
git clone <repo>
cd VitaSync
bash setup.sh

# Register your consoles (check the IP shown in VitaShell)
python3 server.py --add-device vita_1 192.168.1.x
python3 server.py --add-device vita_tv 192.168.1.x

# Verify detection before running for real
python3 server.py --dry-run

# Run
python3 server.py
```

The web interface is available at http://localhost:5000.

## Configuration reference

Settings are stored in `vitasync_data/config.json`.

| Key | Default | Description |
|-----|---------|-------------|
| `devices` | `{}` | Map of name -> IP for each console |
| `port` | `1337` | VitaShell FTP port |
| `remote_path` | `ux0:/user/00/savedata` | Save directory on device |
| `mode` | `manual` | `manual` or `automatic-sync` |
| `backup_hours` | `8` | Max interval between backup snapshots (hours) |
| `storage_warn_mb` | `28000` | Disk warning threshold (MB) |

In `manual` mode, detected sync actions are queued and shown in the web UI
with a "Sync now" button. In `automatic-sync` mode, syncs run immediately
with no confirmation required.

## How to add devices

1. Open VitaShell on the console, go to Network -> FTP server. Note the IP shown.
2. Run: `python3 server.py --add-device NAME IP`
3. Repeat for each console. At least two must be online simultaneously for sync to run.

If you changed the default VitaShell FTP port from 1337:
```
python3 server.py --ftp-port PORT
```

## Restrictions

- All devices must be on the same local network.
- The server must be running when you want to sync. A Raspberry Pi or similar
  always-on device is recommended for seamless operation.
