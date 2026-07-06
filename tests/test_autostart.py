"""MCP server auto-start helper: port detection and spawn decisions (no real server)."""

import socket
import threading

import pytest

from msfs_mcp.autostart import (
    ALREADY_RUNNING,
    DISABLED,
    FAILED,
    STARTED,
    ensure_server_running,
    is_server_running,
    server_url,
)


@pytest.fixture
def listener():
    """A real TCP listener on an ephemeral port that accepts one connection at a time."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]
    stop = threading.Event()

    def serve():
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
                conn.close()
            except TimeoutError:
                continue
            except OSError:
                break

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port
    stop.set()
    sock.close()
    thread.join(timeout=2)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_is_server_running(listener):
    assert is_server_running(port=listener)
    assert not is_server_running(port=_free_port())


def test_already_running_never_spawns(listener):
    spawned = []
    result = ensure_server_running(port=listener, spawn=lambda h, p: spawned.append(p))
    assert result == ALREADY_RUNNING
    assert not spawned


def test_started_when_spawn_brings_up_port():
    port = _free_port()
    started_sockets = []

    def fake_spawn(host, p):
        sock = socket.socket()
        sock.bind((host, p))
        sock.listen(1)
        started_sockets.append(sock)

    result = ensure_server_running(port=port, spawn=fake_spawn, wait_s=2.0)
    assert result == STARTED
    for sock in started_sockets:
        sock.close()


def test_failed_when_spawn_does_nothing():
    result = ensure_server_running(port=_free_port(), spawn=lambda h, p: None, wait_s=0.5)
    assert result == FAILED


def test_failed_when_spawn_raises():
    def bad_spawn(host, port):
        raise OSError("no such executable")

    result = ensure_server_running(port=_free_port(), spawn=bad_spawn, wait_s=0.5)
    assert result == FAILED


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_AUTOSTART", "0")
    spawned = []
    result = ensure_server_running(port=_free_port(), spawn=lambda h, p: spawned.append(p))
    assert result == DISABLED
    assert not spawned


def test_server_url_respects_env(monkeypatch):
    assert server_url() == "http://127.0.0.1:8787/mcp"
    monkeypatch.setenv("MSFS_MCP_PORT", "9999")
    assert server_url() == "http://127.0.0.1:9999/mcp"
