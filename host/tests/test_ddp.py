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
"""DDP framing: golden header bytes, offset chunking, and reassembly."""

import struct

from _fakes import RecordingUDPSocket

from host.frame import Frame
from host.transports import ddp
from host.transports.ddp import (
    DDP_FLAG_PUSH,
    DDP_FLAGS_VERSION1,
    DDP_HEADER_LEN,
    DDPReassembler,
    DDPTransport,
    build_packets,
)

_HEADER = struct.Struct(">BBBBIH")


def _unpack(packet):
    flags, seq, dtype, dest, offset, length = _HEADER.unpack(packet[:DDP_HEADER_LEN])
    return {
        "flags": flags,
        "seq": seq,
        "dtype": dtype,
        "dest": dest,
        "offset": offset,
        "length": length,
        "payload": packet[DDP_HEADER_LEN:],
    }


def test_single_packet_golden_header():
    payload = bytes(768)  # an 8x32 RGB frame
    (packet,) = build_packets(payload, sequence=5)
    h = _unpack(packet)
    assert h["flags"] == DDP_FLAGS_VERSION1 | DDP_FLAG_PUSH  # 0x41
    assert h["seq"] == 5
    assert h["dtype"] == ddp.DDP_DATA_TYPE_RGB
    assert h["dest"] == ddp.DDP_ID_DEFAULT_OUTPUT
    assert h["offset"] == 0
    assert h["length"] == 768
    assert len(h["payload"]) == 768


def test_32x32_frame_chunks_with_push_on_last_only():
    payload = bytes(range(256)) * 12  # 3072 bytes, deterministic
    assert len(payload) == 3072
    packets = build_packets(payload, sequence=1, max_payload=1440)
    assert [len(_unpack(p)["payload"]) for p in packets] == [1440, 1440, 192]
    assert [_unpack(p)["offset"] for p in packets] == [0, 1440, 2880]
    flags = [_unpack(p)["flags"] for p in packets]
    assert flags[:-1] == [DDP_FLAGS_VERSION1, DDP_FLAGS_VERSION1]  # no PUSH
    assert flags[-1] & DDP_FLAG_PUSH  # PUSH only on the last


def test_custom_max_payload_chunking():
    payload = bytes(768)
    packets = build_packets(payload, max_payload=300)
    assert [_unpack(p)["offset"] for p in packets] == [0, 300, 600]
    assert [len(_unpack(p)["payload"]) for p in packets] == [300, 300, 168]


def test_reassembler_round_trip():
    payload = bytes((i * 7) % 256 for i in range(3072))
    reassembler = DDPReassembler()
    result = None
    for packet in build_packets(payload, max_payload=1440):
        result = reassembler.feed(packet)
    assert result == payload


def test_reassembler_returns_none_until_push():
    payload = bytes(3072)
    packets = build_packets(payload, max_payload=1440)
    reassembler = DDPReassembler()
    assert reassembler.feed(packets[0]) is None
    assert reassembler.feed(packets[1]) is None
    assert reassembler.feed(packets[2]) == payload


def test_transport_increments_sequence_per_frame():
    sock = RecordingUDPSocket()
    transport = DDPTransport("127.0.0.1", 4048, sock=sock)
    frame = Frame.blank(8, 32, (1, 2, 3))
    transport.send_live(frame)
    transport.send_live(frame)
    seqs = [_unpack(data)["seq"] for data, _addr in sock.sent]
    assert seqs == [1, 2]
    # Both addressed to the configured host/port.
    assert all(addr == ("127.0.0.1", 4048) for _data, addr in sock.sent)


def test_transport_serializes_full_frame():
    sock = RecordingUDPSocket()
    transport = DDPTransport("10.0.0.9", 4048, sock=sock, max_payload=1440)
    frame = Frame.blank(32, 32, (255, 0, 0))
    transport.send_live(frame)
    reassembler = DDPReassembler()
    result = None
    for data, _addr in sock.sent:
        result = reassembler.feed(data)
    assert result == frame.to_bytes()
