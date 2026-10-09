"""Unit tests stay offline: any network access outside loopback fails the test (#148).

A unit test that reached OpenAI through the KB's extraction pipeline took 24 s
with a key and failed without one. With this guard such a test fails at once,
with or without a key, naming the host it tried to reach. LLM behaviour is
measured by tests/benchmarks, which record and replay cassettes.
"""
from __future__ import annotations

import ipaddress
import socket

import pytest

_LOCAL_NAMES = {"localhost", "localhost.localdomain", ""}


def _is_local(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    host = str(host)
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


class NetworkAccessInUnitTest(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _check(sock: socket.socket, address: object) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
            if not _is_local(address[0]):
                raise NetworkAccessInUnitTest(f"unit test tried to connect to {address[0]!r}")

    def connect(self: socket.socket, address: object) -> None:
        _check(self, address)
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: object) -> int:
        _check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if not _is_local(host):
            raise NetworkAccessInUnitTest(f"unit test tried to resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
