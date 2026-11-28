"""Bounded foreground app/title capture. No pixels, input hooks or network calls.

Windows reads another process's window caption through User32 and obtains only
the executable name through Kernel32. X11 reads the active window's named EWMH
properties with xprop. Native Wayland and macOS are explicitly unsupported.
"""

import ctypes
import ntpath
import os
import re
import shutil
import subprocess
import sys
import unicodedata

from intentaware.localization import tr
from .models import ActivitySnapshot, CaptureResult


MAX_TITLE_CHARS = 512
MAX_APP_CHARS = 128
_NATIVE_TITLE_LIMIT = 2048
_XPROP_BYTES = 8192
_COMMAND_TIMEOUT = 0.75
_SELF_MESSAGE = tr("正在使用 IntentAware，显示最近一次识别的活动。")
_PRIVATE_MESSAGE = "已跳过隐私窗口或密码管理器。"
_PASSWORD_APPS = (
    "1password", "bitwarden", "keepass", "dashlane", "enpass", "lastpass",
    "roboform", "nordpass", "protonpass", "passwordsafe", "keeperpassword",
)
_PRIVATE_TITLE = re.compile(
    r"\b(?:incognito|inprivate|private browsing|private window)\b"
    r"|[\[(]\s*private\s*[\])]"
    r"|无痕(?:模式|浏览|窗口)|隐私(?:浏览|窗口)|隐身(?:模式|窗口)|私密浏览",
    re.IGNORECASE,
)


def _clean_text(value: str, limit: int | None = None) -> str:
    value = "".join(" " if c.isspace() else c for c in value
                    if unicodedata.category(c) not in {"Cc", "Cf", "Cs"} or c.isspace())
    value = " ".join(value.split())
    return value if limit is None else value[:limit]


def is_private_snapshot(snapshot: ActivitySnapshot) -> bool:
    """Default deny rules, reusable for providers injected into the monitor.

    This detects explicit private-mode markers; unmarked private windows cannot
    be identified from app/title metadata. User app exclusions supplement it.
    """
    if snapshot.process_id == os.getpid():
        return True
    app = re.sub(r"[^a-z0-9]", "", _clean_text(snapshot.app_name).casefold())
    if "intentaware" in app or any(name in app for name in _PASSWORD_APPS):
        return True
    if app in {"keeper", "keeperexe"}:
        return True
    title = _clean_text(snapshot.window_title)
    if _PRIVATE_TITLE.search(title):
        return True
    normalized_title = re.sub(r"[^a-z0-9]", "", title.casefold())
    return (
        any(name in normalized_title for name in _PASSWORD_APPS)
        or bool(re.search(r"\bpassword manager\b|密码管理|密码保险库", title, re.IGNORECASE))
    )


class UnavailableObserver:
    def __init__(self, message: str):
        self.message = message

    def capture(self) -> CaptureResult:
        return CaptureResult(None, "unavailable", self.message)


class WindowsForegroundObserver:
    """Win32 caption capture with explicit signatures on 32- and 64-bit hosts."""

    def __init__(self, *, user32=None, kernel32=None):
        self._user32 = user32 if user32 is not None else ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = kernel32 if kernel32 is not None else ctypes.WinDLL("kernel32", use_last_error=True)
        # Fixed-width Win32 integers also let the adapter be tested on LP64 Unix.
        dword, boolean, handle = ctypes.c_uint32, ctypes.c_int32, ctypes.c_void_p
        signatures = (
            (self._user32.GetForegroundWindow, [], handle),
            (self._user32.GetWindowThreadProcessId, [handle, ctypes.POINTER(dword)], dword),
            (self._user32.GetWindowTextW, [handle, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
            (self._kernel32.OpenProcess, [dword, boolean, dword], handle),
            (self._kernel32.QueryFullProcessImageNameW,
             [handle, dword, ctypes.c_wchar_p, ctypes.POINTER(dword)], boolean),
            (self._kernel32.CloseHandle, [handle], boolean),
        )
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

    def _app_name(self, process_id: int) -> str:
        # Query-only rights, never memory access or elevation. Every real handle
        # is closed even when image lookup fails.
        process = self._kernel32.OpenProcess(0x1000, False, process_id)
        if not process:
            return ""
        try:
            size = ctypes.c_uint32(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self._kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return ""
            return _clean_text(ntpath.basename(buffer.value), MAX_APP_CHARS)
        finally:
            self._kernel32.CloseHandle(process)

    def capture(self) -> CaptureResult:
        try:
            window = self._user32.GetForegroundWindow()
            if not window:
                return CaptureResult(None, "idle", tr("当前没有前台窗口。"))
            process_id = ctypes.c_uint32()
            if not self._user32.GetWindowThreadProcessId(window, ctypes.byref(process_id)) or not process_id.value:
                return CaptureResult(None, "unavailable", tr("暂时无法识别前台应用。"))
            if process_id.value == os.getpid():
                return CaptureResult(None, "idle", _SELF_MESSAGE)
            app = self._app_name(process_id.value)
            if not app:
                return CaptureResult(None, "unavailable", tr("无法读取前台应用名称，已跳过本次采集。"))
            if is_private_snapshot(ActivitySnapshot(app, "", process_id.value)):
                return CaptureResult(None, "excluded", tr(_PRIVATE_MESSAGE))
            # GetWindowTextW retrieves the caption of other-process windows
            # without sending WM_GETTEXT to them. Own-process windows were
            # rejected first because their WM_GETTEXT handler could block.
            buffer = ctypes.create_unicode_buffer(_NATIVE_TITLE_LIMIT + 1)
            count = self._user32.GetWindowTextW(window, buffer, len(buffer))
            if count >= _NATIVE_TITLE_LIMIT:
                return CaptureResult(None, "unavailable", tr("窗口标题过长，已跳过本次采集。"))
            title = _clean_text(buffer.value)
            if not count or not title:
                return CaptureResult(None, "idle", tr("当前窗口没有可用于识别的标题。"))
            snapshot = ActivitySnapshot(app, title, process_id.value)
            if is_private_snapshot(snapshot):
                return CaptureResult(None, "excluded", tr(_PRIVATE_MESSAGE))
            if self._user32.GetForegroundWindow() != window:
                return CaptureResult(None, "idle", tr("前台窗口正在切换。"))
            return CaptureResult(ActivitySnapshot(app, title[:MAX_TITLE_CHARS], process_id.value))
        except (OSError, ValueError, AttributeError):
            return CaptureResult(None, "unavailable", tr("暂时无法读取 Windows 前台窗口，请稍后重试。"))


def _quoted_values(line: str) -> list[str]:
    """Decode xprop's quoted strings, including escaped UTF-8 octets."""
    values = []
    for raw in re.findall(r'"((?:\\.|[^"\\])*)"', line):
        data = bytearray()
        for token in re.split(r"(\\(?:[0-7]{1,3}|x[0-9a-fA-F]{2}|.))", raw):
            if re.fullmatch(r"\\[0-7]{1,3}", token):
                data.append(int(token[1:], 8) % 256)
            elif re.fullmatch(r"\\x[0-9a-fA-F]{2}", token):
                data.append(int(token[2:], 16))
            else:
                token = {r"\n": " ", r"\r": " ", r"\t": " ", r'\"': '"', r"\\": "\\"}.get(token, token)
                data.extend(token.encode("utf-8", errors="replace"))
        values.append(data.decode("utf-8", errors="replace"))
    return values


class X11ForegroundObserver:
    def __init__(self, xprop_path: str = "xprop"):
        self._xprop = xprop_path

    def _query(self, *arguments: str) -> str:
        environment = os.environ.copy()
        environment.pop("XPROPFORMATS", None)
        environment["LC_ALL"] = "C.UTF-8"
        result = subprocess.run(
            [self._xprop, "-len", str(_XPROP_BYTES), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_COMMAND_TIMEOUT, check=False, env=environment,
        )
        if result.returncode:
            raise OSError("xprop unavailable")
        return result.stdout

    def _active_window(self) -> str | None:
        output = self._query("-root", "_NET_ACTIVE_WINDOW")
        match = re.search(r"^_NET_ACTIVE_WINDOW(?:\([^)]*\))?\s*[:=][^\n]*?\b(0x[0-9a-f]+)\b", output, re.I | re.M)
        return match.group(1).lower() if match else None

    def capture(self) -> CaptureResult:
        try:
            window = self._active_window()
            if window is None:
                return CaptureResult(None, "unavailable", tr("X11 窗口管理器未提供前台窗口信息。"))
            if int(window, 16) == 0:
                return CaptureResult(None, "idle", tr("当前没有前台窗口。"))
            output = self._query("-id", window, "_NET_WM_PID", "WM_CLASS", "_NET_WM_NAME", "WM_NAME")
            properties = {}
            for line in output.splitlines():
                name = re.match(r"^([A-Z_]+)(?:\([^)]*\))?\s*=", line)
                if name:
                    properties[name.group(1)] = line.split("=", 1)[1].strip()
            pid_match = re.fullmatch(r"[0-9]+", properties.get("_NET_WM_PID", ""))
            if not pid_match or int(pid_match.group()) <= 0:
                return CaptureResult(None, "unavailable", tr("窗口未提供进程标识，已跳过本次采集。"))
            process_id = int(pid_match.group())
            if process_id == os.getpid():
                return CaptureResult(None, "idle", _SELF_MESSAGE)
            classes = _quoted_values(properties.get("WM_CLASS", ""))
            app = _clean_text(classes[-1], MAX_APP_CHARS) if classes else ""
            if not app:
                return CaptureResult(None, "unavailable", tr("窗口未提供应用名称，已跳过本次采集。"))
            if is_private_snapshot(ActivitySnapshot(app, "", process_id)):
                return CaptureResult(None, "excluded", tr(_PRIVATE_MESSAGE))
            names = _quoted_values(properties.get("_NET_WM_NAME", ""))
            if not names or not names[0]:
                names = _quoted_values(properties.get("WM_NAME", ""))
            title = _clean_text(names[0]) if names else ""
            if len(title) >= _NATIVE_TITLE_LIMIT:
                return CaptureResult(None, "unavailable", tr("窗口标题过长，已跳过本次采集。"))
            if not title:
                return CaptureResult(None, "idle", tr("当前窗口没有可用于识别的标题。"))
            if is_private_snapshot(ActivitySnapshot(app, title, process_id)):
                return CaptureResult(None, "excluded", tr(_PRIVATE_MESSAGE))
            if self._active_window() != window:
                return CaptureResult(None, "idle", tr("前台窗口正在切换。"))
            return CaptureResult(ActivitySnapshot(app, title[:MAX_TITLE_CHARS], process_id))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return CaptureResult(None, "unavailable", tr("暂时无法读取 X11 前台窗口，请检查显示会话和 xprop。"))


def create_observer():
    """Select a real adapter; unsupported environments never emit demo data."""
    if sys.platform == "win32":
        try:
            return WindowsForegroundObserver()
        except (OSError, AttributeError):
            return UnavailableObserver(tr("Windows 前台窗口接口不可用，可继续手动填写任务。"))
    if sys.platform.startswith("linux"):
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland":
            return UnavailableObserver(tr("Wayland 暂不支持前台窗口识别，可继续手动填写任务。"))
        if not os.environ.get("DISPLAY"):
            return UnavailableObserver(tr("未检测到 X11 显示会话，可继续手动填写任务。"))
        executable = shutil.which("xprop")
        if not executable:
            return UnavailableObserver(tr("X11 识别需要 xprop；安装后重启应用，或继续手动填写任务。"))
        return X11ForegroundObserver(executable)
    if sys.platform == "darwin":
        return UnavailableObserver(tr("macOS 暂未接入前台窗口识别，可继续手动填写任务。"))
    return UnavailableObserver(tr("当前平台暂不支持前台窗口识别，可继续手动填写任务。"))
