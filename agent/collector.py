"""Privacy-respecting metric collector for Windows.

Collects ONLY aggregated, non-sensitive metadata:
- Active/idle time (via system idle time, not keystroke logging)
- App category time (process name -> category, never content)
- App switch frequency
- Pause detection (idle > threshold)

NEVER collects: keystrokes, passwords, messages, document content,
screenshots, clipboard, browsing history, or personal data.
"""

import time
from datetime import datetime, timezone
from typing import Any

import logging

import psutil

logger = logging.getLogger(__name__)

try:
    import ctypes
    _WIN32 = True
except ImportError:
    _WIN32 = False


# Map common process names to categories (never reads window titles/content)
APP_CATEGORY_MAP = {
    # Development
    "code": "development",
    "devenv": "development",
    "python": "development",
    "pycharm64": "development",
    "idea64": "development",
    "node": "development",
    # Browsing
    "chrome": "browser",
    "msedge": "browser",
    "firefox": "browser",
    # Communication
    "teams": "communication",
    "slack": "communication",
    "outlook": "communication",
    "zoom": "communication",
    # Productivity
    "winword": "productivity",
    "excel": "productivity",
    "powerpnt": "productivity",
    "onenote": "productivity",
    # Terminal
    "powershell": "terminal",
    "cmd": "terminal",
    "windowsterminal": "terminal",
}


def _get_idle_seconds() -> int:
    """Return system idle time in seconds (Win32 API)."""
    if not _WIN32:
        return 0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return int(millis / 1000)
    except Exception:
        return 0


def _get_foreground_app_category() -> str | None:
    """Return the category of the foreground process (never reads window titles).

    Uses only the process executable name, which is mapped to a category.
    No window title, document name, or content is ever read.
    """
    if not _WIN32:
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_uint()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        try:
            proc = psutil.Process(pid.value)
            exe_name = proc.name().lower().replace(".exe", "")
            return APP_CATEGORY_MAP.get(exe_name, "other")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    except Exception:
        return None


class MetricCollector:
    """Collects aggregated activity metrics in a privacy-respecting way.

    NOTE: ``interruptions_count`` is a reserved field and is always 0 in the
    current version (no focus-loss tracking implemented). It is kept in the
    schema for forward compatibility and is never presented as measured data.
    """

    _non_windows_warned = False

    def __init__(self, idle_threshold: int = 300):
        self.idle_threshold = idle_threshold
        self._last_active = time.time()
        self._last_app_category: str | None = None
        self._app_category_seconds: dict[str, int] = {}
        self._app_switches = 0
        self._continuous_work_start: float | None = None
        self._pause_count = 0
        self._pause_total_seconds = 0
        self._was_idle = False
        self._pause_start: float | None = None
        self._tasks_started = 0
        self._tasks_completed = 0
        self._errors_reported = 0
        # Last values sent to the backend, used to emit per-interval deltas.
        self._prev_pause_count = 0
        self._prev_pause_total_seconds = 0
        self._prev_tasks_started = 0
        self._prev_tasks_completed = 0
        self._prev_errors_reported = 0

    def record_task_started(self) -> None:
        self._tasks_started += 1

    def record_task_completed(self) -> None:
        self._tasks_completed += 1

    def record_error(self) -> None:
        self._errors_reported += 1

    def collect(self, interval: int) -> dict[str, Any]:
        """Collect one interval's worth of aggregated metrics.

        Returns a dict suitable for sending to the backend.
        """
        if not _WIN32 and not MetricCollector._non_windows_warned:
            logger.warning(
                "Non-Windows platform: idle time and app category are "
                "unavailable, so active_seconds/app_category will be 0. "
                "Use Windows for real collection."
            )
            MetricCollector._non_windows_warned = True
        now = time.time()
        idle_seconds = _get_idle_seconds()
        is_idle = idle_seconds >= self.idle_threshold

        active_seconds = interval - idle_seconds if idle_seconds < interval else 0
        active_seconds = max(0, active_seconds)

        # Track app category time and switches
        current_category = _get_foreground_app_category()
        if current_category and current_category != self._last_app_category:
            if self._last_app_category is not None:
                self._app_switches += 1
            self._last_app_category = current_category

        if current_category and not is_idle:
            self._app_category_seconds[current_category] = (
                self._app_category_seconds.get(current_category, 0) + active_seconds
            )

        # Continuous work and pause tracking
        if is_idle:
            if not self._was_idle:
                # Transition to idle = start a pause
                self._pause_start = now
                self._pause_count += 1
                self._continuous_work_start = None
            self._was_idle = True
        else:
            if self._was_idle and self._pause_start is not None:
                # End of pause
                self._pause_total_seconds += int(now - self._pause_start)
                self._pause_start = None
            self._was_idle = False
            if self._continuous_work_start is None:
                self._continuous_work_start = now

        continuous_work = 0
        if self._continuous_work_start and not is_idle:
            continuous_work = int(now - self._continuous_work_start)

        # App-category time for THIS interval only. The collector samples the
        # foreground category once per interval, so the interval's active time
        # is attributed to that category. Sending a per-interval delta keeps the
        # backend and feature aggregation consistent (no double counting).
        interval_category_seconds = (
            active_seconds if current_category and not is_idle else 0
        )

        # Get the dominant app category for this interval
        dominant_category = max(self._app_category_seconds, key=self._app_category_seconds.get) if self._app_category_seconds else None

        # Convert cumulative internal counters into per-interval deltas. The
        # backend and feature pipeline treat every metric row as an interval,
        # so sending snapshots would double-count on every batch.
        pause_count_delta = max(0, self._pause_count - self._prev_pause_count)
        pause_total_delta = max(
            0, self._pause_total_seconds - self._prev_pause_total_seconds
        )
        tasks_started_delta = max(0, self._tasks_started - self._prev_tasks_started)
        tasks_completed_delta = max(
            0, self._tasks_completed - self._prev_tasks_completed
        )
        errors_delta = max(0, self._errors_reported - self._prev_errors_reported)

        self._prev_pause_count = self._pause_count
        self._prev_pause_total_seconds = self._pause_total_seconds
        self._prev_tasks_started = self._tasks_started
        self._prev_tasks_completed = self._tasks_completed
        self._prev_errors_reported = self._errors_reported

        metric = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "interval_seconds": interval,
            "active_seconds": active_seconds,
            "idle_seconds": idle_seconds if idle_seconds < interval else interval,
            "continuous_work_seconds": continuous_work,
            # Per-interval deltas (see note above).
            "pause_count": pause_count_delta,
            "pause_total_seconds": pause_total_delta,
            "app_switch_count": self._app_switches,
            "interruptions_count": 0,  # Could track focus loss events
            "app_category_id": None,  # Resolved by backend
            "app_category_seconds": interval_category_seconds,
            "app_category_name": dominant_category,
            "tasks_started": tasks_started_delta,
            "tasks_completed": tasks_completed_delta,
            "errors_reported": errors_delta,
        }

        # Reset interval counters (keep cumulative totals)
        self._app_switches = 0

        return metric

    def reset_session(self) -> None:
        """Reset all session-level accumulators."""
        self._continuous_work_start = time.time()
        self._pause_count = 0
        self._pause_total_seconds = 0
        self._app_switches = 0
        self._app_category_seconds.clear()
        self._tasks_started = 0
        self._tasks_completed = 0
        self._errors_reported = 0
        # Last values sent to the backend, used to emit per-interval deltas.
        self._prev_pause_count = 0
        self._prev_pause_total_seconds = 0
        self._prev_tasks_started = 0
        self._prev_tasks_completed = 0
        self._prev_errors_reported = 0
        self._was_idle = False
