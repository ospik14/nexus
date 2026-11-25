import pytest
from starlette.websockets import WebSocketDisconnect

from nexus.auth import COOKIE
from nexus.models import SessionRecord
from tests.conftest import ORIGIN, PASSWORD


def test_protected_endpoints_and_socket(client):
    for path in (
        "/overview",
        "/history",
        "/auth/session",
        "/processes",
        "/services",
        "/docker",
        "/files/workspaces",
    ):
        assert client.get("/api" + path).status_code == 401
    assert (
        client.get("/api/overview", headers={"Origin": "https://example.invalid"}).status_code
        == 403
    )
    try:
        with client.websocket_connect("/api/live", headers={"Origin": ORIGIN}):
            raise AssertionError("Unauthenticated WebSocket connected")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401


def test_auth_cookie_origin_csrf_and_logout(client):
    credentials = {"username": "admin", "password": PASSWORD}
    assert client.post("/api/auth/login", json=credentials).status_code == 403
    assert (
        client.post(
            "/api/auth/login", json=credentials, headers={"Origin": "https://another.test"}
        ).status_code
        == 403
    )
    login = client.post("/api/auth/login", json=credentials, headers={"Origin": ORIGIN})
    cookie = login.headers["set-cookie"]
    assert login.status_code == 200
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age="):
        assert attribute in cookie
    assert client.get("/api/auth/session").json()["csrf"] == login.json()["csrf"]
    assert client.post("/api/auth/logout", json={}, headers={"Origin": ORIGIN}).status_code == 403
    assert (
        client.post(
            "/api/auth/logout",
            json={},
            headers={"Origin": "https://another.test", "X-CSRF-Token": login.json()["csrf"]},
        ).status_code
        == 403
    )

    session = client.cookies.get(COOKIE)
    result = client.post(
        "/api/auth/logout",
        json={},
        headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf"]},
    )
    assert result.status_code == 204 and not result.content
    client.cookies.set(COOKIE, session)
    assert client.get("/api/overview").status_code == 401


def test_login_rate_limit_is_persisted(client):
    for _ in range(8):
        assert (
            client.post(
                "/api/auth/login",
                headers={"Origin": ORIGIN},
                json={"username": "admin", "password": "wrong"},
            ).status_code
            == 401
        )
    locked = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": "admin", "password": PASSWORD},
    )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


def test_websocket_origin_and_session_expiration(signed_in):
    client, _ = signed_in
    try:
        with client.websocket_connect("/api/live", headers={"Origin": "https://other.test"}):
            raise AssertionError("Foreign origin connected")
    except WebSocketDisconnect as exc:
        assert exc.code == 4403
    with client.websocket_connect(
        "wss://testserver/api/live", headers={"Origin": ORIGIN}
    ) as websocket:
        assert websocket.receive_json()["timestamp"] > 0
        with client.app.state.auth.sessions.begin() as db:
            db.query(SessionRecord).update({"expires": 1})
        assert client.get("/api/overview").status_code == 401
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        assert closed.value.code == 4401


def test_request_body_and_validation_limits(signed_in):
    client, headers = signed_in
    headers = {**headers, "Content-Type": "application/json"}
    response = client.post("/api/auth/login", headers=headers, content=b" " * 8200)
    assert response.status_code == 413
    response = client.post(
        "/api/auth/login", headers=headers, json={"username": "admin", "password": "x" * 2000}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Request fields are invalid"}
