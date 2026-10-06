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

# Each release channel names its executable differently.
IMAGES = ("T3 Code (Nightly).exe", "T3 Code (Alpha).exe")
INSTALL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs/t3code"
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
    if not any(p.info["name"] in IMAGES for p in psutil.process_iter(["name"])):
        exe = next((INSTALL_DIR / image for image in IMAGES if (INSTALL_DIR / image).is_file()), None)
        if not exe:
            log(f"Cannot launch T3: none of {IMAGES} is installed in {INSTALL_DIR}")
            sys.exit(1)
        # T3 holds Electron's single-instance lock, so a launch that races its self-update restart just quits.
        try:
            startup = subprocess.Popen([exe])
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
