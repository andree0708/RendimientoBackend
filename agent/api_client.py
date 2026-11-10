"""HTTP client for the agent — sends metrics and handles offline buffering."""

import json
import logging
import time
from collections import deque
from typing import Any

import requests

from agent.config import AgentConfig

logger = logging.getLogger(__name__)


class AgentAPIClient:
    """Backend API client with authentication, retry, and local buffering."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.base_url = config.backend_url.rstrip("/")
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.session_id: str | None = None
        # Set when the backend rejects ingestion because consent was withdrawn.
        self.consent_revoked = False
        # Each entry keeps its own session id so buffered metrics are never
        # attributed to a different (later) session.
        self._buffer: deque[dict[str, Any]] = deque(maxlen=config.max_buffer_size)
        self._load_buffer()

    def _buffer_file(self):
        from pathlib import Path

        from agent.config import CONFIG_DIR

        return Path(CONFIG_DIR) / "metrics_buffer.json"

    def _load_buffer(self) -> None:
        """Restore buffered metrics from disk after a restart/crash."""
        if not self.config.enable_local_buffer:
            return
        try:
            path = self._buffer_file()
            if not path.exists():
                return
            entries = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(entries, list):
                for entry in entries[-self.config.max_buffer_size:]:
                    if isinstance(entry, dict) and "metric" in entry:
                        self._buffer.append(entry)
                if entries:
                    logger.info("Restored %d buffered metrics from disk", len(self._buffer))
        except Exception as exc:  # corrupt file must never crash the agent
            logger.warning("Could not load metrics buffer: %s", exc)

    def _save_buffer(self) -> None:
        """Persist the in-memory buffer so it survives restarts."""
        if not self.config.enable_local_buffer:
            return
        try:
            path = self._buffer_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(list(self._buffer)), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save metrics buffer: %s", exc)

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    def login(self) -> bool:
        """Authenticate with the backend and store tokens."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"email": self.config.email, "password": self.config.password},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data["access_token"]
                self.refresh_token = data["refresh_token"]
                self.consent_revoked = False
                logger.info("Agent authenticated as %s", self.config.email)
                return True
            logger.error("Login failed: %s", resp.text)
            return False
        except requests.RequestException as exc:
            logger.error("Login error: %s", exc)
            return False

    def _refresh(self) -> bool:
        """Refresh the access token using the refresh token (rotating)."""
        if not self.refresh_token:
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/auth/refresh",
                json={"refresh_token": self.refresh_token},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data["access_token"]
                # The backend rotates refresh tokens (single-use).
                if data.get("refresh_token"):
                    self.refresh_token = data["refresh_token"]
                return True
        except requests.RequestException:
            pass
        return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    def get_consent(self) -> bool | None:
        """Return whether collection consent is granted, or None on error."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/consent",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return bool(resp.json().get("granted", False))
            if resp.status_code == 401 and self._refresh():
                return self.get_consent()
            logger.error("Could not read consent status: %s", resp.text)
        except requests.RequestException as exc:
            logger.error("Consent check error: %s", exc)
        return None

    def get_active_session(self, _retry: bool = True) -> str | None:
        """Fetch the backend's current active session for this user."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/sessions/active/current",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self.session_id = data.get("id") if data else None
                return self.session_id
            if resp.status_code == 401 and _retry and self._refresh():
                return self.get_active_session(_retry=False)
            logger.error("Get active session failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.error("Get active session error: %s", exc)
        return None

    def start_session(self, _retry: bool = True) -> str | None:
        """Start a work session, reusing an existing one if necessary."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/sessions",
                json={"notes": "Started by local agent"},
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 201:
                self.session_id = resp.json()["id"]
                logger.info("Session started: %s", self.session_id)
                return self.session_id
            if resp.status_code == 409:
                # A session is already active (e.g. after an agent crash):
                # reuse it instead of failing to start.
                logger.warning("An active session already exists; reusing it")
                return self.get_active_session()
            if resp.status_code == 401 and _retry and self._refresh():
                return self.start_session(_retry=False)
            logger.error("Start session failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.error("Start session error: %s", exc)
        return None

    def stop_session(self, _retry: bool = True) -> bool:
        """Stop the active work session, resolving it if this process lacks it."""
        if not self.session_id:
            self.get_active_session()
        if not self.session_id:
            logger.info("No active session to stop")
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/sessions/{self.session_id}/stop",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Session stopped: %s", self.session_id)
                self.session_id = None
                return True
            if resp.status_code == 401 and _retry and self._refresh():
                return self.stop_session(_retry=False)
            if resp.status_code == 404:
                self.session_id = None
            logger.error("Stop session failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.error("Stop session error: %s", exc)
        return False

    # ------------------------------------------------------------------ #
    # Metrics ingestion                                                    #
    # ------------------------------------------------------------------ #

    def _buffer_metrics(
        self, metrics: list[dict[str, Any]], session_id: str | None = None
    ) -> None:
        """Keep metrics for a later retry, preserving their original session."""
        sid = session_id or self.session_id
        for metric in metrics:
            self._buffer.append({"session_id": sid, "metric": metric})
        self._save_buffer()

    def send_metrics(
        self, metrics: list[dict[str, Any]], _retry: bool = True
    ) -> bool:
        """Send a batch of metrics.

        Behaviour by response:
        - 201: success, then flush any buffered metrics.
        - 401: refresh the token once and retry.
        - 403: consent was withdrawn; mark it and do NOT buffer or retry.
        - 5xx / network error: buffer with the current session id.
        - Other 4xx: drop the batch (invalid data) and log it.
        """
        if not self.session_id:
            logger.warning("No active session; buffering %d metrics", len(metrics))
            self._buffer_metrics(metrics)
            return False

        payload = {"session_id": self.session_id, "metrics": metrics}

        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/metrics/batch",
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 201:
                logger.info("Sent %d metrics", len(metrics))
                self._flush_buffer()
                return True
            if resp.status_code == 401 and _retry and self._refresh():
                return self.send_metrics(metrics, _retry=False)
            if resp.status_code == 403:
                self.consent_revoked = True
                logger.error(
                    "Metrics rejected: data-collection consent is not granted. "
                    "Stopping collection."
                )
                return False
            if resp.status_code >= 500:
                logger.warning("Backend error %s; buffering metrics", resp.status_code)
                self._buffer_metrics(metrics)
                return False
            logger.error("Send metrics failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.warning("Backend unreachable, buffering: %s", exc)
            self._buffer_metrics(metrics)
        return False

    def _flush_buffer(self) -> None:
        """Attempt to send buffered metrics, grouped by their original session."""
        if not self._buffer or not self.config.enable_local_buffer:
            return
        if self.consent_revoked:
            self._buffer.clear()
            self._save_buffer()
            return

        pending = list(self._buffer)
        self._buffer.clear()

        by_session: dict[str, list[dict[str, Any]]] = {}
        for entry in pending:
            sid = entry.get("session_id")
            if not sid:
                continue
            by_session.setdefault(sid, []).append(entry["metric"])

        failed: list[dict[str, Any]] = []
        for sid, metrics in by_session.items():
            try:
                resp = requests.post(
                    f"{self.base_url}/api/v1/metrics/batch",
                    json={"session_id": sid, "metrics": metrics},
                    headers=self._headers(),
                    timeout=15,
                )
                if resp.status_code == 201:
                    logger.info("Flushed %d buffered metrics for %s", len(metrics), sid)
                elif resp.status_code == 403:
                    self.consent_revoked = True
                    logger.error("Buffered metrics discarded: consent withdrawn")
                    self._buffer.clear()
                    self._save_buffer()
                    return
                else:
                    failed.extend(
                        {"session_id": sid, "metric": m} for m in metrics
                    )
            except requests.RequestException:
                failed.extend({"session_id": sid, "metric": m} for m in metrics)

        for entry in failed:
            self._buffer.append(entry)
        self._save_buffer()

    # ------------------------------------------------------------------ #
    # Self-reports                                                         #
    # ------------------------------------------------------------------ #

    def submit_self_report(
        self, report: dict[str, Any], _retry: bool = True
    ) -> bool:
        """Submit a self-report, linking it to the active session when possible."""
        payload = dict(report)
        if not self.session_id:
            # The CLI report command runs in a separate process and may not
            # know the session started by `agent start`.
            self.get_active_session()
        if self.session_id:
            payload["session_id"] = self.session_id
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/self-reports",
                json=payload,
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 201:
                return True
            if resp.status_code == 401 and _retry and self._refresh():
                return self.submit_self_report(report, _retry=False)
            logger.error("Self-report failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.error("Self-report error: %s", exc)
        return False

    # ------------------------------------------------------------------ #
    # AI triggers                                                          #
    # ------------------------------------------------------------------ #

    def request_fatigue_assessment(
        self, _retry: bool = True
    ) -> dict | None:
        """Request a fatigue assessment from the AI module."""
        if not self.session_id:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/ai/predict/fatigue",
                params={"session_id": self.session_id},
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 and _retry and self._refresh():
                return self.request_fatigue_assessment(_retry=False)
            logger.warning("Fatigue assessment failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.warning("Fatigue assessment error: %s", exc)
        return None

    def request_performance_prediction(
        self, _retry: bool = True
    ) -> dict | None:
        """Request a performance prediction from the AI module."""
        if not self.session_id:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/ai/predict/performance",
                params={"session_id": self.session_id},
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 and _retry and self._refresh():
                return self.request_performance_prediction(_retry=False)
            logger.warning("Performance prediction failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.warning("Performance prediction error: %s", exc)
        return None
