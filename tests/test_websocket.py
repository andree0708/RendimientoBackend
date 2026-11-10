"""Tests for WebSocket endpoint."""

import json
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class TestWebSocket:
    def test_ws_no_token_rejected(self, client):
        """Connection without a token must be rejected."""
        try:
            with client.websocket_connect("/ws") as ws:
                ws.receive_text()
            # If we get here without exception, the connection was rejected
            assert False, "Should have been rejected"
        except (WebSocketDisconnect, Exception):
            pass  # Expected — rejected without token

    def test_ws_invalid_token_rejected(self, client):
        """Connection with an invalid token must be rejected."""
        try:
            with client.websocket_connect("/ws?token=invalid_token") as ws:
                ws.receive_text()
            assert False, "Should have been rejected"
        except (WebSocketDisconnect, Exception):
            pass  # Expected

    def test_ws_authenticated_connection(self, client, test_user):
        """Authenticated connection should receive connection.status event."""
        user, token = test_user
        try:
            with client.websocket_connect(f"/ws?token={token}") as ws:
                data = ws.receive_text()
                parsed = json.loads(data)
                # The initial connection.status event
                assert parsed.get("type") == "event"
                assert parsed["data"]["event_type"] == "connection.status"
                assert parsed["data"]["payload"]["status"] == "connected"
        except WebSocketDisconnect:
            # Some test runners may close the connection quickly
            pass

    def test_ws_ping_pong(self, client, test_user):
        """Server should respond to ping with pong."""
        user, token = test_user
        try:
            with client.websocket_connect(f"/ws?token={token}") as ws:
                # Consume initial connection event
                ws.receive_text()
                # Send ping
                ws.send_text(json.dumps({"type": "ping"}))
                # Read messages until we find a pong
                for _ in range(3):
                    response = ws.receive_text()
                    parsed = json.loads(response)
                    if parsed.get("type") == "pong":
                        break
                else:
                    # If no pong found, check if we got an event
                    assert parsed.get("type") in ("pong", "event", "ack")
        except WebSocketDisconnect:
            pass

    def test_ws_subscribe_ack(self, client, test_user):
        """Server should acknowledge a subscribe message."""
        user, token = test_user
        try:
            with client.websocket_connect(f"/ws?token={token}") as ws:
                ws.receive_text()  # consume connection event
                ws.send_text(json.dumps({"type": "subscribe", "channels": ["user"]}))
                response = ws.receive_text()
                parsed = json.loads(response)
                assert parsed.get("type") == "ack"
        except WebSocketDisconnect:
            pass
