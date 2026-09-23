# /// script
# requires-python = ">=3.11"
# dependencies = ["psutil"]
# ///
import ctypes
import logging
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil

IMAGE = "T3 Code (Alpha).exe"
EXE = Path(os.environ["LOCALAPPDATA"]) / "Programs/t3code" / IMAGE
LOG = Path(os.environ["LOCALAPPDATA"]) / "t3-keepalive/t3-keepalive.log"
SW_MINIMIZE = 6

user32 = ctypes.WinDLL("user32")
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

LOG.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG)],
    format="%(asctime)s: %(message)s",
    level=logging.INFO,
)
log = logging.info


def visible_window(pid: int) -> int | None:
    found = []

    def check(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(check), 0)
    return found[0] if found else None


# Only minimize launches initiated here; opening T3 from the Start menu stays visible.
log("Watching T3; existing windows remain unchanged")
while True:
    if not any(p.info["name"] == IMAGE for p in psutil.process_iter(["name"])):
        # T3 holds Electron's single-instance lock, so a launch that races its self-update restart just quits.
        try:
            startup = subprocess.Popen([EXE])
        except OSError as error:
            log(f"Cannot launch T3: {error}")
            sys.exit(1)
        log(f"Launched T3 (PID {startup.pid}); waiting to minimize its window")
        # Electron ignores a STARTUPINFO show state, so the window opens visible until minimized here.
        for _ in range(600):
            hwnd = visible_window(startup.pid)
            if hwnd or startup.poll() is not None:
                break
            time.sleep(0.1)
        if startup.poll() is not None:
            log(f"T3 exited with code {startup.returncode} before showing a window")
        elif not hwnd:
            log("T3 showed no window within 60 seconds")
        else:
            user32.ShowWindow(hwnd, SW_MINIMIZE)
            log("T3 opened visible and is now minimized"
                if user32.IsIconic(hwnd)
                else "T3 is visible after the minimize request; leaving its window alone")
    time.sleep(300)
