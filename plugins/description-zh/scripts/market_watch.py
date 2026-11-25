"""Wake the desktop worker when one of its Windows catalog directories changes."""
import contextlib
import ctypes
from ctypes import wintypes
import time


@contextlib.contextmanager
def market_notifications(home):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    first = kernel.FindFirstChangeNotificationW
    first.argtypes = (wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD)
    first.restype = wintypes.HANDLE
    rearm = kernel.FindNextChangeNotification
    rearm.argtypes = (wintypes.HANDLE,)
    close = kernel.FindCloseChangeNotification
    close.argtypes = (wintypes.HANDLE,)
    wait = kernel.WaitForMultipleObjects
    wait.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD)
    wait.restype = wintypes.DWORD
    handles = []
    for root in (home / "marketplaces", home / ".tmp/marketplaces"):
        # File names, directory names, and last-write timestamps.
        handle = first(str(root), True, 0x13)
        if handle and handle != ctypes.c_void_p(-1).value:
            handles.append(handle)

    def changed(seconds):
        if handles:
            array = (wintypes.HANDLE * len(handles))(*handles)
            index = wait(len(handles), array, False, int(seconds * 1000))
            if index < len(handles):
                handle = handles[index]
                if not rearm(handle):
                    close(handle)
                    handles.pop(index)
                time.sleep(0.6)  # Let a catalog refresh finish replacing its files.
                return True
            if index == 258:  # WAIT_TIMEOUT
                return False
        time.sleep(seconds)
        return False

    try:
        yield changed
    finally:
        for handle in handles:
            close(handle)
