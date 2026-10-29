"""The synthetic benchmark must not connect to a real or non-local database."""

import socket

import pytest

from scripts.benchmark_user_directory import local_target


def test_rejects_non_disposable_database_before_dns(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("DNS must not be queried for an invalid database")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected)
    with pytest.raises(ValueError):
        local_target("postgresql://user:password@localhost/neondb")


def test_rejects_remote_resolved_address(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 5432))
        ],
    )
    with pytest.raises(ValueError):
        local_target("postgresql://user:password@example.test/shonchoy_search_benchmark_test")


def test_accepts_disposable_loopback_database(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5432))
        ],
    )
    url = local_target("postgresql://user:password@localhost/shonchoy_search_benchmark_test")
    assert url.drivername == "postgresql+psycopg"
