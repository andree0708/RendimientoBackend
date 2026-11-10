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
        self._buffer: deque = deque(maxlen=config.max_buffer_size)

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
                logger.info("Agent authenticated as %s", self.config.email)
                return True
            logger.error("Login failed: %s", resp.text)
            return False
        except requests.RequestException as exc:
            logger.error("Login error: %s", exc)
            return False

    def _refresh(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/auth/refresh",
                json={"refresh_token": self.refresh_token},
                timeout=10,
            )
            if resp.status_code == 200:
                self.access_token = resp.json()["access_token"]
                return True
        except requests.RequestException:
            pass
        return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    def start_session(self) -> str | None:
        """Start a work session on the backend."""
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
            logger.error("Start session failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.error("Start session error: %s", exc)
        return None

    def stop_session(self) -> bool:
        """Stop the active work session."""
        if not self.session_id:
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
        except requests.RequestException:
            pass
        return False

    # ------------------------------------------------------------------ #
    # Metrics ingestion                                                    #
    # ------------------------------------------------------------------ #

    def send_metrics(self, metrics: list[dict[str, Any]]) -> bool:
        """Send a batch of metrics.  Buffers locally if the backend is unreachable."""
        if not self.session_id:
            logger.warning("No active session; buffering %d metrics", len(metrics))
            for m in metrics:
                self._buffer.append(m)
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
                # Try to flush buffer after successful send
                self._flush_buffer()
                return True
            if resp.status_code == 401:
                if self._refresh():
                    return self.send_metrics(metrics)
            logger.error("Send metrics failed: %s", resp.text)
        except requests.RequestException as exc:
            logger.warning("Backend unreachable, buffering: %s", exc)
            for m in metrics:
                self._buffer.append(m)
        return False

    def _flush_buffer(self) -> None:
        """Attempt to send buffered metrics collected while offline."""
        if not self._buffer or not self.config.enable_local_buffer:
            return

        buffered = list(self._buffer)
        self._buffer.clear()

        payload = {"session_id": self.session_id, "metrics": buffered}
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/metrics/batch",
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 201:
                logger.info("Flushed %d buffered metrics", len(buffered))
            else:
                # Put them back in the buffer
                self._buffer.extend(buffered)
        except requests.RequestException:
            self._buffer.extend(buffered)

    # ------------------------------------------------------------------ #
    # Self-reports                                                         #
    # ------------------------------------------------------------------ #

    def submit_self_report(self, report: dict[str, Any]) -> bool:
        """Submit a self-report to the backend."""
        if self.session_id:
            report["session_id"] = self.session_id
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/self-reports",
                json=report,
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 201
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------ #
    # AI triggers                                                          #
    # ------------------------------------------------------------------ #

    def request_fatigue_assessment(self) -> dict | None:
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
        except requests.RequestException:
            pass
        return None

    def request_performance_prediction(self) -> dict | None:
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
        except requests.RequestException:
            pass
        return None
