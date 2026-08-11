"""PART A - 전체 스위트에 네트워크 차단을 강제한다.

socket.socket 생성 자체를 막으면 asyncio의 이벤트 루프 내부 배관
(Windows ProactorEventLoop의 self-pipe는 루프백 TCP 소켓으로 구현됨)까지
걸려서 무관한 실패가 난다. 그래서 connect/connect_ex만 가로채 루프백
(127.0.0.1/::1) 이외 주소로의 연결 시도를 즉시 예외로 만든다 - 이게
테스트가 실제로 하지 말아야 할 일("바깥으로 나가는 네트워크 호출")이다.
"""

from __future__ import annotations

import socket

import pytest

_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkBlockedError(RuntimeError):
    pass


def _host_of(address: object) -> object:
    return address[0] if isinstance(address, tuple) else address


def _guarded_connect(self: socket.socket, address: object) -> object:
    if _host_of(address) not in _ALLOWED_HOSTS:
        raise NetworkBlockedError(
            f"테스트 중 실제 네트워크 연결 시도가 차단됐다: connect({address!r}). "
            "mock이 빠진 코드 경로일 수 있다."
        )
    return _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: object) -> object:
    if _host_of(address) not in _ALLOWED_HOSTS:
        raise NetworkBlockedError(
            f"테스트 중 실제 네트워크 연결 시도가 차단됐다: connect_ex({address!r}). "
            "mock이 빠진 코드 경로일 수 있다."
        )
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
