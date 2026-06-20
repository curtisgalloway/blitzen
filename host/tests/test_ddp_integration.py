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
"""End-to-end DDP over a real loopback UDP socket (the live path, sans hardware)."""

import socket

from host.frame import Frame
from host.transports.ddp import DDPReassembler, DDPTransport


def test_live_frame_over_loopback():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2.0)
    port = receiver.getsockname()[1]

    transport = DDPTransport("127.0.0.1", port, max_payload=1440)
    try:
        # A recognisable gradient so a byte-for-byte match is meaningful.
        frame = Frame(32, 32, bytearray((i * 5) % 256 for i in range(32 * 32 * 3)))
        transport.send_live(frame)

        reassembler = DDPReassembler()
        result = None
        for _ in range(16):  # plenty of headroom for the 3 expected datagrams
            packet, _addr = receiver.recvfrom(65535)
            result = reassembler.feed(packet)
            if result is not None:
                break
        assert result == frame.to_bytes()
    finally:
        transport.close()
        receiver.close()
