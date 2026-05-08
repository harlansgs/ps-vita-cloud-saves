import argparse
import threading

from waitress import serve

from config import BACKUPS, CONFIG, LATEST, save_config
from sync import sync_loop
from web import app


def main():
    parser = argparse.ArgumentParser(description="VitaSync save synchronization server")
    parser.add_argument("--web-port", type=int, default=5000, metavar="PORT",
                        help="port for the web interface (default: 5000)")
    parser.add_argument("--ftp-port", type=int, metavar="PORT",
                        help="set the FTP port used to connect to Vita devices and save")
    parser.add_argument("--add-device", nargs=2, metavar=("NAME", "IP"), action="append",
                        default=[], help="add a device (can be repeated)")
    parser.add_argument("--list-devices", action="store_true",
                        help="print configured devices and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="back up and compare saves but do not sync or send SMS")
    args = parser.parse_args()

    if args.ftp_port:
        CONFIG["port"] = args.ftp_port
        save_config()
        print(f"FTP port set to {args.ftp_port}")

    for name, ip in args.add_device:
        CONFIG["devices"][name] = ip
        save_config()
        print(f"Added device: {name} = {ip}")

    if args.list_devices:
        if CONFIG["devices"]:
            for name, ip in CONFIG["devices"].items():
                print(f"  {name}: {ip}")
        else:
            print("No devices configured. Use --add-device NAME IP to add one.")
        return

    LATEST.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)

    threading.Thread(target=sync_loop, args=(args.dry_run,), daemon=True).start()
    serve(app, host="127.0.0.1", port=args.web_port)


if __name__ == "__main__":
    main()
