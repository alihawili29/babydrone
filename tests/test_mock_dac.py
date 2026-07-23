"""Tests for the mock DAC + calibration, so I can check the networking/
failsafe logic works before I've actually got real I2C hardware wired up."""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raspberry_pi"))

from mcp4725 import MockMCP4725, MockPCF8591  # noqa: E402
from calibration import Calibration  # noqa: E402
from main import build_dac  # noqa: E402


def test_mock_dac_set_value_clamps():
    dac = MockMCP4725(bus_number=1, address=0x62, label="TEST")
    dac.set_value(-100)
    assert dac.last_value == 0
    dac.set_value(9999)
    assert dac.last_value == 4095
    dac.set_value(2048)
    assert dac.last_value == 2048


def test_mock_dac_set_normalized():
    dac = MockMCP4725(bus_number=1, address=0x63, label="TEST")
    dac.set_normalized(0.0)
    assert dac.last_value == 0
    dac.set_normalized(1.0)
    assert dac.last_value == 4095
    dac.set_normalized(0.5)
    assert dac.last_value == 2048  # round(0.5 * 4095)


def _write_temp_calibration(data):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


def test_calibration_incomplete_by_default():
    path = _write_temp_calibration({
        "throttle": {"minimum_code": None, "centre_code": None, "maximum_code": None},
        "pitch": {"backward_code": None, "centre_code": None, "forward_code": None},
        "roll": {"left_code": None, "centre_code": None, "right_code": None},
    })
    cal = Calibration(path)
    assert cal.is_complete() is False
    os.unlink(path)


def test_calibration_complete_once_filled_in():
    path = _write_temp_calibration({
        "throttle": {"minimum_code": 800, "centre_code": 1700, "maximum_code": 2600},
        "pitch": {"backward_code": 1000, "centre_code": 2048, "forward_code": 3000},
        "roll": {"left_code": 900, "centre_code": 2000, "right_code": 3100},
    })
    cal = Calibration(path)
    assert cal.is_complete() is True
    assert cal.throttle_code(0.0) == 800
    assert cal.pitch_code(0.0) == 2048
    assert cal.roll_code(1.0) == 3100
    os.unlink(path)


def test_calibration_raises_when_incomplete():
    path = _write_temp_calibration({
        "throttle": {"minimum_code": None, "centre_code": None, "maximum_code": None},
        "pitch": {"backward_code": None, "centre_code": None, "forward_code": None},
        "roll": {"left_code": None, "centre_code": None, "right_code": None},
    })
    cal = Calibration(path)
    try:
        cal.throttle_code(0.5)
        assert False, "should have raised"
    except ValueError:
        pass
    os.unlink(path)


def test_mock_dac_used_end_to_end_with_calibration():
    path = _write_temp_calibration({
        "throttle": {"minimum_code": 800, "centre_code": 1700, "maximum_code": 2600},
        "pitch": {"backward_code": 1000, "centre_code": 2048, "forward_code": 3000},
        "roll": {"left_code": 900, "centre_code": 2000, "right_code": 3100},
    })
    cal = Calibration(path)
    dac = MockMCP4725(bus_number=1, address=0x62, label="THROTTLE")
    dac.set_value(cal.throttle_code(0.5))
    assert dac.last_value == 1700
    os.unlink(path)


# --- PCF8591 (roll axis) ---
# Same public interface as MockMCP4725, but clamped/scaled to 0-255 (8-bit)
# instead of 0-4095 (12-bit) since the real PCF8591 write is a single byte.

def test_mock_pcf8591_set_value_clamps_to_8_bit():
    dac = MockPCF8591(bus_number=1, address=0x48, label="ROLL")
    dac.set_value(-100)
    assert dac.last_value == 0
    dac.set_value(9999)
    assert dac.last_value == 255
    dac.set_value(128)
    assert dac.last_value == 128


def test_mock_pcf8591_set_normalized_scales_to_8_bit():
    dac = MockPCF8591(bus_number=1, address=0x48, label="ROLL")
    dac.set_normalized(0.0)
    assert dac.last_value == 0
    dac.set_normalized(1.0)
    assert dac.last_value == 255
    dac.set_normalized(0.5)
    assert dac.last_value == 128  # round(0.5 * 255)


# --- build_dac() device dispatch (config.json "device" field, Part 2) ---

def _mixed_hardware_cfg():
    return {
        "dac": {
            "throttle": {"device": "MCP4725", "bus": 3, "address": "0x60"},
            "pitch": {"device": "MCP4725", "bus": 1, "address": "0x61"},
            "roll": {"device": "PCF8591", "bus": 1, "address": "0x48"},
        }
    }


def test_build_dac_picks_mock_mcp4725_for_mcp4725_axes():
    cfg = _mixed_hardware_cfg()
    throttle_dac = build_dac(cfg, "throttle", mock=True, label="THROTTLE")
    pitch_dac = build_dac(cfg, "pitch", mock=True, label="PITCH")
    assert isinstance(throttle_dac, MockMCP4725)
    assert isinstance(pitch_dac, MockMCP4725)
    assert throttle_dac.bus_number == 3
    assert throttle_dac.address == 0x60


def test_build_dac_picks_mock_pcf8591_for_roll():
    cfg = _mixed_hardware_cfg()
    roll_dac = build_dac(cfg, "roll", mock=True, label="ROLL")
    assert isinstance(roll_dac, MockPCF8591)
    assert roll_dac.bus_number == 1
    assert roll_dac.address == 0x48


def test_build_dac_defaults_to_mcp4725_when_device_field_missing():
    cfg = {"dac": {"throttle": {"bus": 1, "address": "0x60"}}}
    dac = build_dac(cfg, "throttle", mock=True, label="THROTTLE")
    assert isinstance(dac, MockMCP4725)


# --- roll calibration (real, multimeter-confirmed hardware-limited endpoints) ---
# raspberry_pi/calibration.json's roll section is 0/128/255 — the PCF8591's
# digital range IS the calibration here (not a linear guess from voltage),
# since the measured usable swing under load doesn't reach the rails.

def test_roll_code_matches_real_measured_calibration():
    path = os.path.join(os.path.dirname(__file__), "..", "raspberry_pi", "calibration.json")
    cal = Calibration(path)
    assert cal.roll_code(-1.0) == 0
    assert cal.roll_code(0.0) == 128
    assert cal.roll_code(1.0) == 255
    mid = cal.roll_code(0.5)
    assert 128 < mid < 255  # consistent with map_bipolar_axis's piecewise interpolation
