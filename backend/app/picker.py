"""Native Windows folder picker and common-folder shortcuts.

A web page can't learn the full path of a folder (browsers hide it on purpose), so the
local backend opens the standard Windows "Select Folder" dialog for the user instead.
The dialog runs in a short-lived child process, so Tk never touches the server's threads.
Nothing here reads or writes the chosen folder; it only returns its path.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

PICK_TIMEOUT_S = 600  # the user may browse for a while

_DIALOG = r"""
import os, sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
initial = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.expanduser("~")
path = filedialog.askdirectory(parent=root, initialdir=initial, mustexist=True,
                               title="Choose a folder for ShadowTree to read (your files stay untouched)")
root.destroy()
if path:
    sys.stdout.write(os.path.normpath(path))
"""

_lock = threading.Lock()


class PickerBusy(Exception):
    """A folder dialog is already open."""


def pick_folder(initial: str | None = None) -> str | None:
    """Open the Windows folder dialog and return the chosen path, or None if cancelled."""
    if not _lock.acquire(blocking=False):
        raise PickerBusy()
    try:
        args = [sys.executable, "-I", "-c", _DIALOG]
        if initial:
            args.append(initial)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           timeout=PICK_TIMEOUT_S, creationflags=flags)
        path = (r.stdout or "").strip()
        return path if path and Path(path).is_dir() else None
    except subprocess.TimeoutExpired:
        return None
    finally:
        _lock.release()


# Registry names of the user's real Desktop, Documents, Downloads and Pictures
# (these follow OneDrive and other redirections, unlike ~/Documents).
_KNOWN = [
    ("Documents", "Personal", "Documents"),
    ("Desktop", "Desktop", "Desktop"),
    ("Downloads", "{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
    ("Pictures", "My Pictures", "Pictures"),
]


def quick_folders() -> list[dict]:
    """[{name, path}] for the common folders that exist on this PC."""
    reg = {}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            for _, key, _ in _KNOWN:
                try:
                    reg[key] = winreg.QueryValueEx(k, key)[0]
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    out = []
    for name, key, fallback in _KNOWN:
        p = Path(os.path.expandvars(reg.get(key) or str(Path.home() / fallback)))
        if p.is_dir():
            out.append({"name": name, "path": str(p)})
    return out
