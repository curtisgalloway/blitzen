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
"""M0 control protocol: message framing, INFO parsing, and ACK/retry behavior."""

import struct

import pytest
from _fakes import (
    FakeM0Socket,
    drop_all_responder,
    flaky_responder,
    ok_responder,
    status_responder,
)

from host.protocol import STATUS_ERR, Encoding, Op, ResumePolicy
from host.transports.m0_control import M0Control, M0Error


def _control(responder):
    return M0Control("127.0.0.1", sock=FakeM0Socket(responder), timeout=0.01, retries=3)


def test_store_message_framing():
    ctl = _control(ok_responder())
    ctl.store(
        2, bytes(512), dwell_ms=100, encoding=Encoding.INDEXED16, palette=bytes(48)
    )
    (packet,) = ctl._sock.sent
    assert packet[0] == Op.STORE
    assert packet[1] == 1  # first sequence
    assert packet[2] == 2  # slot
    assert struct.unpack(">H", packet[3:5])[0] == 100  # dwell_ms
    assert packet[5] == Encoding.INDEXED16
    assert packet[6] == 16  # palette_count = 48 / 3
    assert len(packet[7:55]) == 48  # palette
    assert len(packet[55:]) == 512  # payload


def test_store_rejects_bad_palette_length():
    ctl = _control(ok_responder())
    with pytest.raises(ValueError):
        ctl.store(0, bytes(4), dwell_ms=10, palette=bytes(5))


def test_play_message_framing():
    ctl = _control(ok_responder())
    ctl.play(0, 5, repeat=3)
    (packet,) = ctl._sock.sent
    assert packet[0] == Op.PLAY
    assert packet[2] == 0  # start
    assert packet[3] == 5  # end
    assert struct.unpack(">H", packet[4:6])[0] == 3  # repeat


def test_stop_and_clear_framing():
    ctl = _control(ok_responder())
    ctl.stop()
    ctl.clear()
    assert ctl._sock.sent[0][0] == Op.STOP
    assert ctl._sock.sent[1][0] == Op.CLEAR


def test_config_message_framing():
    ctl = _control(ok_responder())
    ctl.config(ResumePolicy.IDLE_TIMEOUT, idle_ms=2000)
    (packet,) = ctl._sock.sent
    assert packet[0] == Op.CONFIG
    assert packet[2] == ResumePolicy.IDLE_TIMEOUT
    assert struct.unpack(">H", packet[3:5])[0] == 2000


def test_info_parses_reply():
    body = struct.pack(">IBB", 12345, 28, 3)
    ctl = _control(ok_responder(info_body=body))
    result = ctl.info()
    assert result == {"free_ram": 12345, "slot_capacity": 28, "slots_used": 3}


def test_retry_succeeds_after_dropped_ack():
    ctl = _control(flaky_responder(drop=1))
    ctl.stop()  # should not raise
    assert len(ctl._sock.sent) == 2  # one dropped, one delivered


def test_timeout_after_exhausting_retries():
    ctl = M0Control(
        "127.0.0.1", sock=FakeM0Socket(drop_all_responder), timeout=0.01, retries=2
    )
    with pytest.raises(TimeoutError):
        ctl.stop()
    assert len(ctl._sock.sent) == 2


def test_error_status_raises():
    ctl = _control(status_responder(STATUS_ERR))
    with pytest.raises(M0Error):
        ctl.stop()
