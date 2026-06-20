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
"""WLED control: JSON bodies, URL formation, and the capability probe."""

import json

import pytest
from _fakes import FakeUrlopen

from host.transports.wled_control import WLEDControl, WLEDError, _parse_version


def test_select_preset_posts_state():
    opener = FakeUrlopen(lambda req: b"{}")
    wled = WLEDControl("1.2.3.4", urlopen=opener)
    wled.select_preset(3)
    req = opener.requests[0]
    assert req.method == "POST"
    assert req.get_full_url() == "http://1.2.3.4/json/state"
    assert json.loads(req.data) == {"ps": 3}


def test_set_power_with_brightness():
    opener = FakeUrlopen(lambda req: b"{}")
    wled = WLEDControl("host", urlopen=opener)
    wled.set_power(True, 128)
    assert json.loads(opener.requests[0].data) == {"on": True, "bri": 128}


def test_non_default_port_in_url():
    opener = FakeUrlopen(lambda req: b"{}")
    wled = WLEDControl("host", port=8080, urlopen=opener)
    wled.select_preset(1)
    assert opener.requests[0].get_full_url() == "http://host:8080/json/state"


def test_probe_modern_2d():
    info = {"ver": "0.14.1", "leds": {"matrix": {"w": 32, "h": 8}}}
    opener = FakeUrlopen(lambda req: json.dumps(info).encode())
    result = WLEDControl("host", urlopen=opener).probe()
    assert result["version"] == "0.14.1"
    assert result["version_ok"] is True
    assert result["is_2d"] is True
    assert result["matrix"] == {"w": 32, "h": 8}
    assert opener.requests[0].method == "GET"
    assert opener.requests[0].get_full_url().endswith("/json/info")


def test_probe_old_non_2d():
    info = {"ver": "0.13.3", "leds": {}}
    opener = FakeUrlopen(lambda req: json.dumps(info).encode())
    result = WLEDControl("host", urlopen=opener).probe()
    assert result["version_ok"] is False
    assert result["is_2d"] is False
    assert result["matrix"] is None


def test_invalid_json_raises():
    opener = FakeUrlopen(lambda req: b"not json")
    with pytest.raises(WLEDError):
        WLEDControl("host", urlopen=opener).get_info()


def test_parse_version():
    assert _parse_version("0.14.0-b1") == (0, 14, 0)
    assert _parse_version("0.13") == (0, 13)
    assert _parse_version("") == ()
