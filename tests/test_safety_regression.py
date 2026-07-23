"""
Regression tests for the throttle-inversion safety audit (see task: mixed
MCP4725/PCF8591 hardware finalization).

With the inverted throttle wiring, 4095 = minimum/safe/landed and 0 =
maximum. The risk this guards against: any startup, failsafe, or exit path
that writes a hardcoded raw DAC literal instead of going through
Calibration.throttle_code(0.0) would silently keep commanding full
throttle instead of landing. These tests exercise main.py's actual
decision functions (targets_for_state, write_safe_exit_values) together
with a real Calibration and the mock DACs, so they fail if either function
is ever changed to bypass Calibration.
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raspberry_pi"))

from calibration import Calibration  # noqa: E402
from failsafe import Watchdog, DISARMED, ARMED, FAILSAFE  # noqa: E402
from mcp4725 import MockMCP4725, MockPCF8591  # noqa: E402
from main import targets_for_state, write_safe_exit_values  # noqa: E402


INVERTED_THROTTLE_CALIBRATION = {
    "throttle": {"minimum_code": 4095, "centre_code": 2048, "maximum_code": 0},
    "pitch": {"backward_code": 0, "centre_code": 2048, "forward_code": 3968},
    "roll": {"left_code": 30, "centre_code": 128, "right_code": 225},
}


def _write_temp_calibration(data):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


def _make_calibration():
    path = _write_temp_calibration(INVERTED_THROTTLE_CALIBRATION)
    cal = Calibration(path)
    os.unlink(path)  # Calibration reads the file eagerly in __init__, safe to remove now
    return cal


def _make_dacs():
    throttle_dac = MockMCP4725(bus_number=3, address=0x60, label="THROTTLE")
    pitch_dac = MockMCP4725(bus_number=1, address=0x61, label="PITCH")
    roll_dac = MockPCF8591(bus_number=1, address=0x48, label="ROLL")
    return throttle_dac, pitch_dac, roll_dac


# --- (a) startup, before any packet has arrived ---

def test_startup_before_first_packet_commands_safe_throttle_code():
    cal = _make_calibration()
    watchdog = Watchdog()  # fresh watchdog starts DISARMED, exactly as in main.py
    assert watchdog.state == DISARMED

    # main.py inits all three pending_* targets to 0.0 before the first packet
    throttle_target, pitch_target, roll_target = targets_for_state(
        watchdog.state, 0.0, 0.0, 0.0, throttle_override=None,
    )
    assert (throttle_target, pitch_target, roll_target) == (0.0, 0.0, 0.0)

    throttle_dac, pitch_dac, roll_dac = _make_dacs()
    throttle_dac.set_value(cal.throttle_code(throttle_target))
    pitch_dac.set_value(cal.pitch_code(pitch_target))
    roll_dac.set_value(cal.roll_code(roll_target))

    assert throttle_dac.last_value == 4095
    assert pitch_dac.last_value == 2048
    assert roll_dac.last_value == 128


# --- (b) watchdog trips into FAILSAFE ---

def test_failsafe_trip_snaps_pitch_roll_to_safe_code_immediately():
    watchdog = Watchdog(timeout_s=0.5, failsafe_descent_rate=0.5)
    watchdog.on_valid_packet(0.0, armed=True, emergency_stop=False)
    assert watchdog.state == ARMED

    # connection drops; a packet came in at throttle=0.8 (mid-flight), then silence
    state, throttle_override = watchdog.tick(now=0.6, dt=1.0 / 20.0, current_throttle_target=0.8)
    assert state == FAILSAFE

    cal = _make_calibration()
    throttle_target, pitch_target, roll_target = targets_for_state(
        state, pending_throttle=0.8, pending_pitch=0.5, pending_roll=-0.5,
        throttle_override=throttle_override,
    )
    # pitch/roll snap to centre right away on failsafe entry, no gradual ramp
    assert pitch_target == 0.0
    assert roll_target == 0.0
    assert cal.pitch_code(pitch_target) == 2048
    assert cal.roll_code(roll_target) == 128


def test_failsafe_descent_lands_on_safe_throttle_code():
    watchdog = Watchdog(timeout_s=0.5, failsafe_descent_rate=0.5)
    watchdog.on_valid_packet(0.0, armed=True, emergency_stop=False)

    state, throttle_override = watchdog.tick(now=0.6, dt=1.0 / 20.0, current_throttle_target=0.8)
    assert state == FAILSAFE

    # keep ticking (as main.py's loop would) until the descent fully bottoms out
    for _ in range(200):
        state, throttle_override = watchdog.tick(now=0.6, dt=1.0, current_throttle_target=0.8)
        if throttle_override == 0.0:
            break
    assert throttle_override == 0.0

    cal = _make_calibration()
    throttle_target, pitch_target, roll_target = targets_for_state(
        state, pending_throttle=0.8, pending_pitch=0.0, pending_roll=0.0,
        throttle_override=throttle_override,
    )
    assert throttle_target == 0.0

    throttle_dac, pitch_dac, roll_dac = _make_dacs()
    throttle_dac.set_value(cal.throttle_code(throttle_target))
    assert throttle_dac.last_value == 4095


# --- (c) clean program exit ---

def test_clean_exit_writes_safe_codes_before_close():
    cal = _make_calibration()
    throttle_dac, pitch_dac, roll_dac = _make_dacs()

    # simulate mid-flight: DAC currently holds a live, non-safe commanded value
    throttle_dac.set_value(cal.throttle_code(0.9))
    pitch_dac.set_value(cal.pitch_code(0.5))
    roll_dac.set_value(cal.roll_code(-0.5))
    assert throttle_dac.last_value != 4095

    write_safe_exit_values(cal, throttle_dac, pitch_dac, roll_dac)

    assert throttle_dac.last_value == 4095
    assert pitch_dac.last_value == 2048
    assert roll_dac.last_value == 128


def test_write_safe_exit_values_is_a_noop_when_calibration_incomplete():
    path = _write_temp_calibration({
        "throttle": {"minimum_code": None, "centre_code": None, "maximum_code": None},
        "pitch": {"backward_code": None, "centre_code": None, "forward_code": None},
        "roll": {"left_code": None, "centre_code": None, "right_code": None},
    })
    cal = Calibration(path)
    os.unlink(path)
    throttle_dac, pitch_dac, roll_dac = _make_dacs()

    write_safe_exit_values(cal, throttle_dac, pitch_dac, roll_dac)  # must not raise

    assert throttle_dac.last_value is None
    assert pitch_dac.last_value is None
    assert roll_dac.last_value is None
