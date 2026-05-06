import ftplib
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
