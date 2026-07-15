"""Packet validation tests — spec section 22, 'Network tests'."""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raspberry_pi"))

from udp_receiver import validate_packet  # noqa: E402


def make_packet(**overrides):
    base = {
        "version": 1, "session": "abc123", "sequence": 10,
        "mac_time_ms": 123456, "armed": True, "emergency_stop": False,
        "throttle": 0.5, "pitch": 0.0, "roll": 0.0,
        "right_gesture": "THROTTLE_HOLD", "left_gesture": "DIRECTION_NEUTRAL",
    }
    base.update(overrides)
    return base


def test_valid_packet_accepted():
    ok, reason, packet = validate_packet(make_packet())
    assert ok is True
    assert packet["throttle"] == 0.5


def test_missing_field_rejected():
    p = make_packet()
    del p["throttle"]
    ok, reason, _ = validate_packet(p)
    assert ok is False
    assert "missing field" in reason


def test_wrong_type_rejected():
    ok, reason, _ = validate_packet(make_packet(throttle="fast"))
    assert ok is False
    assert "wrong type" in reason


def test_unsupported_version_rejected():
    ok, reason, _ = validate_packet(make_packet(version=99))
    assert ok is False
    assert "version" in reason


def test_nan_rejected():
    ok, reason, _ = validate_packet(make_packet(throttle=float("nan")))
    assert ok is False
    assert "NaN" in reason


def test_inf_rejected():
    ok, reason, _ = validate_packet(make_packet(pitch=float("inf")))
    assert ok is False
    assert "NaN" in reason


def test_out_of_range_throttle_rejected():
    ok, reason, _ = validate_packet(make_packet(throttle=1.5))
    assert ok is False
    assert "range" in reason


def test_out_of_range_roll_rejected():
    ok, reason, _ = validate_packet(make_packet(roll=-2.0))
    assert ok is False
    assert "range" in reason


def test_duplicate_sequence_rejected():
    ok, reason, _ = validate_packet(make_packet(sequence=5), last_sequence=5)
    assert ok is False
    assert "sequence" in reason


def test_old_sequence_rejected():
    ok, reason, _ = validate_packet(make_packet(sequence=3), last_sequence=10)
    assert ok is False
    assert "sequence" in reason


def test_newer_sequence_accepted():
    ok, reason, _ = validate_packet(make_packet(sequence=11), last_sequence=10)
    assert ok is True


def test_session_change_while_armed_rejected():
    ok, reason, _ = validate_packet(
        make_packet(session="different"), current_session="abc123", is_armed=True,
    )
    assert ok is False
    assert "session" in reason


def test_session_change_while_disarmed_allowed():
    ok, reason, _ = validate_packet(
        make_packet(session="different"), current_session="abc123", is_armed=False,
    )
    assert ok is True


def test_not_a_dict_rejected():
    ok, reason, _ = validate_packet("not a dict")
    assert ok is False
    assert "not a JSON object" in reason


def test_values_clamped_even_when_valid():
    ok, reason, packet = validate_packet(make_packet(throttle=1.0, pitch=-1.0, roll=1.0))
    assert ok is True
    assert packet["throttle"] == 1.0
    assert packet["pitch"] == -1.0
    assert packet["roll"] == 1.0
