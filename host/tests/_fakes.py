# Copyright 2026 The Blitzen Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Test doubles: fake UDP sockets, an HTTP opener, and a controllable clock."""

from __future__ import annotations

import socket
from collections import deque
from typing import Callable, List, Optional, Tuple

from host.protocol import ACK_FLAG, STATUS_OK


class RecordingUDPSocket:
    """A datagram socket that only records what was sent (for DDP send tests)."""

    def __init__(self) -> None:
        self.sent: List[Tuple[bytes, tuple]] = []

    def sendto(self, data: bytes, addr: tuple) -> None:
        self.sent.append((bytes(data), addr))

    def settimeout(self, _timeout) -> None:
        pass

    def close(self) -> None:
        pass


class FakeM0Socket:
    """A UDP socket whose ``responder(request) -> list[bytes] | None`` supplies replies.

    Returning ``None`` (or an empty list) leaves the inbox empty, so the next
    :meth:`recvfrom` raises ``socket.timeout`` — exactly what a dropped/late ack looks
    like, which keeps retry tests fast and deterministic.
    """

    def __init__(self, responder: Callable[[bytes], Optional[List[bytes]]]) -> None:
        self.responder = responder
        self.sent: List[bytes] = []
        self._inbox: deque = deque()

    def settimeout(self, _timeout) -> None:
        pass

    def sendto(self, data: bytes, _addr: tuple) -> None:
        self.sent.append(bytes(data))
        replies = self.responder(bytes(data))
        if replies:
            self._inbox.extend(replies)

    def recvfrom(self, _bufsize: int) -> Tuple[bytes, tuple]:
        if self._inbox:
            return self._inbox.popleft(), ("127.0.0.1", 4049)
        raise socket.timeout()

    def close(self) -> None:
        pass


def ok_responder(info_body: bytes = b"") -> Callable[[bytes], List[bytes]]:
    """Always-ACK responder. INFO replies carry ``info_body``."""

    def respond(request: bytes) -> List[bytes]:
        opcode, seq = request[0], request[1]
        body = info_body if opcode == 0x05 else b""  # 0x05 == Op.INFO
        return [bytes((opcode | ACK_FLAG, seq, STATUS_OK)) + body]

    return respond


def status_responder(status: int) -> Callable[[bytes], List[bytes]]:
    """Responder that always replies with a fixed (non-OK) status byte."""

    def respond(request: bytes) -> List[bytes]:
        opcode, seq = request[0], request[1]
        return [bytes((opcode | ACK_FLAG, seq, status))]

    return respond


def flaky_responder(drop: int) -> Callable[[bytes], Optional[List[bytes]]]:
    """Drop the first ``drop`` requests (no reply), then ACK OK."""
    state = {"n": 0}

    def respond(request: bytes) -> Optional[List[bytes]]:
        state["n"] += 1
        if state["n"] <= drop:
            return None
        opcode, seq = request[0], request[1]
        return [bytes((opcode | ACK_FLAG, seq, STATUS_OK))]

    return respond


def drop_all_responder(request: bytes) -> None:
    """Never reply (simulates an unreachable device)."""
    return None


class FakeHTTPResponse:
    """Minimal context-manager response with ``read()`` for the WLED opener fake."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeUrlopen:
    """Records each :class:`urllib.request.Request` and returns a canned response."""

    def __init__(self, responder: Callable[[object], bytes]) -> None:
        self.responder = responder
        self.requests: list = []

    def __call__(self, req, timeout=None) -> FakeHTTPResponse:
        self.requests.append(req)
        return FakeHTTPResponse(self.responder(req))


class FakeClock:
    """A clock advanced only by :meth:`sleep` — deterministic scheduler testing."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        if dt > 0:
            self.t += dt
