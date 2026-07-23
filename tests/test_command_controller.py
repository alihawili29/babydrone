"""Tests for CommandController's pitch/roll magnitude split — roll's usable
PCF8591 voltage range is narrower than pitch's MCP4725 range, so they're
independently configurable instead of sharing one direction_strength."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mac"))

from command_controller import CommandController  # noqa: E402
from gesture_classifier import (  # noqa: E402
    PITCH_FORWARD, PITCH_BACKWARD, ROLL_LEFT, ROLL_RIGHT, THROTTLE_HOLD,
)


def test_direction_strength_still_sets_both_when_pitch_roll_not_given():
    c = CommandController(direction_strength=0.4)
    assert c.pitch_strength == 0.4
    assert c.roll_strength == 0.4


def test_pitch_and_roll_strength_independently_configurable():
    c = CommandController(direction_strength=0.25, pitch_strength=0.6, roll_strength=0.15)
    assert c.pitch_strength == 0.6
    assert c.roll_strength == 0.15


def test_pitch_command_uses_pitch_strength_not_direction_strength():
    c = CommandController(direction_strength=0.25, pitch_strength=0.6, roll_strength=0.15)
    throttle, pitch, roll = c.update(THROTTLE_HOLD, PITCH_FORWARD)
    assert pitch == 0.6


def test_roll_command_uses_roll_strength_not_direction_strength():
    c = CommandController(direction_strength=0.25, pitch_strength=0.6, roll_strength=0.15)
    throttle, pitch, roll = c.update(THROTTLE_HOLD, ROLL_RIGHT)
    assert roll == 0.15


def test_negative_pitch_backward_scales_with_pitch_strength():
    c = CommandController(pitch_strength=0.6, roll_strength=0.15)
    throttle, pitch, roll = c.update(THROTTLE_HOLD, PITCH_BACKWARD)
    assert pitch == -0.6


def test_negative_roll_left_scales_with_roll_strength():
    c = CommandController(pitch_strength=0.6, roll_strength=0.15)
    throttle, pitch, roll = c.update(THROTTLE_HOLD, ROLL_LEFT)
    assert roll == -0.15
