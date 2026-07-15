"""Calibration mapping tests — spec section 22."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raspberry_pi"))

from calibration import map_bipolar_axis, map_throttle  # noqa: E402


def test_throttle_minimum():
    assert map_throttle(0.0, 800, 2600) == 800


def test_throttle_maximum():
    assert map_throttle(1.0, 800, 2600) == 2600


def test_throttle_midpoint():
    assert map_throttle(0.5, 800, 2600) == 1700


def test_throttle_clamps_below_zero():
    assert map_throttle(-0.5, 800, 2600) == 800


def test_throttle_clamps_above_one():
    assert map_throttle(1.5, 800, 2600) == 2600


def test_bipolar_centre():
    assert map_bipolar_axis(0.0, 900, 2048, 3100) == 2048


def test_bipolar_full_positive():
    assert map_bipolar_axis(1.0, 900, 2048, 3100) == 3100


def test_bipolar_full_negative():
    assert map_bipolar_axis(-1.0, 900, 2048, 3100) == 900


def test_bipolar_asymmetric_ranges():
    # centre not halfway between negative/positive — real hardware often
    # isn't symmetric, this is the reason map_bipolar_axis is piecewise
    result_pos = map_bipolar_axis(0.5, 900, 2048, 3100)
    result_neg = map_bipolar_axis(-0.5, 900, 2048, 3100)
    assert result_pos == 2048 + 0.5 * (3100 - 2048)
    assert result_neg == 2048 + 0.5 * (900 - 2048)
    assert result_pos != result_neg  # ranges are not mirror-symmetric here


def test_bipolar_clamps():
    assert map_bipolar_axis(2.0, 900, 2048, 3100) == 3100
    assert map_bipolar_axis(-2.0, 900, 2048, 3100) == 900


def test_bipolar_reversed_direction():
    # negative_code > centre_code > positive_code is valid — the
    # calibration file determines actual voltage direction, not the code
    result = map_bipolar_axis(1.0, 3000, 2000, 1000)
    assert result == 1000
