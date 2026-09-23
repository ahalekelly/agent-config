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
# T3 restarts itself during updates; wait this many polls before relaunching.
GRACE_POLLS = 5
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7

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
startup: subprocess.Popen | None = None
minimized_window: int | None = None
missing_polls = 0
log("Watching T3; existing windows remain unchanged")
while True:
    time.sleep(1)
    if startup:
        if startup.poll() is not None:
            startup = None
            minimized_window = None
        elif minimized_window:
            log(f"T3 is minimized (PID {startup.pid})"
                if user32.IsIconic(minimized_window)
                else "T3 is visible after the minimize request; leaving its window alone")
            startup = None
            minimized_window = None
            continue
        else:
            hwnd = visible_window(startup.pid)
            if hwnd:
                if not user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, SW_MINIMIZE)
                # Observe the result on the next poll, like the macOS watcher.
                minimized_window = hwnd
            continue

    if any(p.info["name"] == IMAGE for p in psutil.process_iter(["name"])):
        missing_polls = 0
        continue
    missing_polls += 1
    if missing_polls < GRACE_POLLS:
        continue

    missing_polls = 0
    try:
        startup = subprocess.Popen(
            [EXE],
            startupinfo=subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=SW_SHOWMINNOACTIVE),
        )
    except OSError as error:
        log(f"Cannot launch T3: {error}")
        sys.exit(1)
    log(f"Launched T3 (PID {startup.pid}); waiting to minimize its window")
