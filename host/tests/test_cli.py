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
"""CLI config loading, target construction, and assignment parsing."""

import argparse

import pytest

from host import cli
from host.targets import DisplayTarget, M0Target, WLEDTarget

_CONFIG = """
[targets.arr]
type = "wled"
host = "1.2.3.4"
width = 32
height = 8

[targets.panel]
type = "m0"
host = "5.6.7.8"
width = 32
height = 32

[targets.sink]
type = "ddp"
host = "127.0.0.1"
width = 32
height = 32
"""


def _config(tmp_path):
    path = tmp_path / "devices.toml"
    path.write_text(_CONFIG)
    return str(path)


def test_load_targets(tmp_path):
    targets = cli._load_targets(_config(tmp_path))
    assert set(targets) == {"arr", "panel", "sink"}


def test_build_target_types(tmp_path):
    targets = cli._load_targets(_config(tmp_path))
    arr = cli.build_target("arr", targets["arr"])
    panel = cli.build_target("panel", targets["panel"])
    sink = cli.build_target("sink", targets["sink"])
    try:
        assert isinstance(arr, WLEDTarget)
        assert isinstance(panel, M0Target)
        assert isinstance(sink, DisplayTarget) and not isinstance(
            sink, (WLEDTarget, M0Target)
        )
        assert panel.geometry == (32, 32)
    finally:
        arr.close()
        panel.close()
        sink.close()


def test_resolve_config_missing():
    with pytest.raises(cli.CLIError):
        cli._resolve_config("/no/such/devices.toml")


def test_unknown_target_type_rejected():
    with pytest.raises(cli.CLIError):
        cli.build_target("z", {"type": "bogus", "host": "x", "width": 8, "height": 8})


def test_missing_required_field_rejected():
    with pytest.raises(cli.CLIError):
        cli.build_target("z", {"type": "wled", "host": "x", "width": 8})


def test_target_cfg_unknown_name():
    with pytest.raises(cli.CLIError):
        cli._target_cfg({"a": {}}, "missing")


def test_parse_assignments_explicit():
    args = argparse.Namespace(
        assign=["x=plasma@10", "y=scroll"], pattern=None, target=[]
    )
    assert cli._parse_assignments(args) == [
        ("x", "plasma", 10.0),
        ("y", "scroll", None),
    ]


def test_parse_assignments_pattern_and_targets():
    args = argparse.Namespace(assign=[], pattern="plasma", target=["x", "y"])
    assert cli._parse_assignments(args) == [
        ("x", "plasma", None),
        ("y", "plasma", None),
    ]


def test_parse_assignments_requires_input():
    args = argparse.Namespace(assign=[], pattern=None, target=[])
    with pytest.raises(cli.CLIError):
        cli._parse_assignments(args)


def test_parse_assignments_bad_spec():
    args = argparse.Namespace(assign=["broken"], pattern=None, target=[])
    with pytest.raises(cli.CLIError):
        cli._parse_assignments(args)
