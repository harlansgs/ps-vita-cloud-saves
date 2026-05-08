import ftplib
import os
from datetime import datetime, timezone
from pathlib import Path

from config import CONFIG


def ftp_connect(ip):
    ftp = ftplib.FTP()
    ftp.connect(ip, CONFIG["port"], timeout=5)
    ftp.login()
    return ftp


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
            local_file = local / name
            remote_mtime = None
            try:
                resp = ftp.sendcmd(f"MDTM {name}")
                remote_mtime = datetime.strptime(resp[4:], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
                if local_file.exists() and abs(local_file.stat().st_mtime - remote_mtime) < 1:
                    continue
            except Exception:
                pass
            with open(local_file, "wb") as f:
                ftp.retrbinary(f"RETR {name}", f.write)
            if remote_mtime is not None:
                os.utime(local_file, (remote_mtime, remote_mtime))


def ftp_rmtree(ftp, name):
    """Recursively delete a directory on the FTP server."""
    ftp.cwd(name)
    lines = []
    ftp.retrlines("LIST", lines.append)
    for line in lines:
        entry = line.split()[-1]
        if line.startswith("d"):
            ftp_rmtree(ftp, entry)
        else:
            ftp.delete(entry)
    ftp.cwd("..")
    ftp.rmd(name)


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
            try:
                remote_size = int(ftp.sendcmd(f"SIZE {item.name}").split()[1])
                local_size = item.stat().st_size
                if remote_size != local_size:
                    raise IOError(f"{item.name}: uploaded {remote_size} bytes, expected {local_size}")
            except ftplib.error_perm:
                pass  # SIZE not supported by this server
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                ftp.sendcmd(f"MFMT {mtime.strftime('%Y%m%d%H%M%S')} {item.name}")
            except Exception:
                pass
