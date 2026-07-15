"""Mock DAC tests — spec section 22, 'Raspberry Pi mock tests'.
Lets networking/failsafe logic be verified before real I2C hardware
is connected."""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raspberry_pi"))

from mcp4725 import MockMCP4725  # noqa: E402
from calibration import Calibration  # noqa: E402


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
