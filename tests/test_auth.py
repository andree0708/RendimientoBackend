"""Tests for authentication endpoints."""

import pytest


class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "new@worksense.ai",
            "password": "newpass123",
            "full_name": "New User",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_register_duplicate_email(self, client):
        # First registration
        client.post("/api/v1/auth/register", json={
            "email": "dup@worksense.ai",
            "password": "testpass123",
            "full_name": "Dup User",
        })
        # Second registration with same email
        resp = client.post("/api/v1/auth/register", json={
            "email": "dup@worksense.ai",
            "password": "testpass123",
            "full_name": "Dup User",
        })
        assert resp.status_code == 409

    def test_register_invalid_email(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "testpass123",
            "full_name": "Bad User",
        })
        assert resp.status_code == 422


class TestLogin:
    def test_login_success(self, client, test_user):
        user, _ = test_user
        resp = client.post("/api/v1/auth/login", json={
            "email": user.email,
            "password": "testpass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_login_wrong_password(self, client, test_user):
        user, _ = test_user
        resp = client.post("/api/v1/auth/login", json={
            "email": user.email,
            "password": "wrongpass",
        })
        assert resp.status_code == 401

    def test_login_unknown_email(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": "unknown@worksense.ai",
            "password": "testpass123",
        })
        assert resp.status_code == 401


class TestMe:
    def test_get_me_authenticated(self, client, auth_headers, test_user):
        user, _ = test_user
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == user.email
        assert data["full_name"] == user.full_name

    def test_get_me_unauthenticated(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestRefreshToken:
    def test_refresh_success(self, client, test_user):
        user, _ = test_user
        login = client.post("/api/v1/auth/login", json={
            "email": user.email, "password": "testpass123"
        })
        refresh_token = login.json()["refresh_token"]
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_refresh_invalid_token(self, client):
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid_token"})
        assert resp.status_code == 401
