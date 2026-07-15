"""
Gesture classification tests — spec section 22.
Uses synthetic landmarks (simple objects with .x/.y) instead of a real
camera or MediaPipe, so these run without any hardware.
"""

import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mac"))

from gesture_classifier import (  # noqa: E402
    classify_right_hand, classify_left_hand, GestureDebouncer,
    THROTTLE_UP, THROTTLE_DOWN, THROTTLE_HOLD, RIGHT_UNKNOWN,
    ROLL_LEFT, ROLL_RIGHT, PITCH_FORWARD, PITCH_BACKWARD, DIRECTION_NEUTRAL,
)


def lm(x, y):
    return SimpleNamespace(x=x, y=y)


def make_hand(overrides):
    """21 landmarks, default = closed fist at wrist (0.5, 0.5)."""
    base = [lm(0.5, 0.5) for _ in range(21)]
    for i, (x, y) in overrides.items():
        base[i] = lm(x, y)
    return base


def right_fingers_up():
    # base (MCP) at y=0.5, tip above (smaller y = up), for index/middle/ring/pinky
    return make_hand({
        5: (0.45, 0.5), 8: (0.45, 0.2),
        9: (0.50, 0.5), 12: (0.50, 0.2),
        13: (0.55, 0.5), 16: (0.55, 0.2),
        17: (0.60, 0.5), 20: (0.60, 0.2),
        6: (0.45, 0.35), 10: (0.50, 0.35), 14: (0.55, 0.35), 18: (0.60, 0.35),
    })


def right_fingers_down():
    return make_hand({
        5: (0.45, 0.5), 8: (0.45, 0.8),
        9: (0.50, 0.5), 12: (0.50, 0.8),
        13: (0.55, 0.5), 16: (0.55, 0.8),
        17: (0.60, 0.5), 20: (0.60, 0.8),
        6: (0.45, 0.65), 10: (0.50, 0.65), 14: (0.55, 0.65), 18: (0.60, 0.65),
    })


def right_fist():
    # Curled fist: tips pulled in close to the wrist, well inside the
    # mcp radius -> low tip-to-wrist/mcp-to-wrist ratio (< 1.3).
    return make_hand({
        5: (0.40, 0.40), 8: (0.48, 0.47),
        9: (0.50, 0.35), 12: (0.50, 0.45),
        13: (0.60, 0.40), 16: (0.53, 0.47),
        17: (0.65, 0.45), 20: (0.55, 0.48),
    })


def folded_fingers_base():
    """Main fingers folded per the direction-based check used by the
    LEFT hand classifier (tip not above pip not above mcp). Distinct
    from right_fist() above, which uses a distance-ratio check instead."""
    return make_hand({
        5: (0.45, 0.5), 6: (0.45, 0.55), 8: (0.45, 0.6),
        9: (0.50, 0.5), 10: (0.50, 0.55), 12: (0.50, 0.6),
        13: (0.55, 0.5), 14: (0.55, 0.55), 16: (0.55, 0.6),
        17: (0.60, 0.5), 18: (0.60, 0.55), 20: (0.60, 0.6),
    })


def left_thumb_left():
    hand = folded_fingers_base()
    hand[0] = lm(0.5, 0.5)   # wrist
    hand[2] = lm(0.48, 0.5)  # thumb mcp
    hand[3] = lm(0.40, 0.5)  # thumb ip
    hand[4] = lm(0.30, 0.5)  # thumb tip, far left, same y as wrist
    return hand


def left_thumb_right():
    hand = folded_fingers_base()
    hand[0] = lm(0.5, 0.5)
    hand[2] = lm(0.52, 0.5)
    hand[3] = lm(0.60, 0.5)
    hand[4] = lm(0.70, 0.5)
    return hand


def left_index_only():
    hand = folded_fingers_base()
    hand[5] = lm(0.45, 0.5)
    hand[6] = lm(0.45, 0.35)
    hand[8] = lm(0.45, 0.2)  # index extended (tip above pip above mcp)
    return hand


def left_index_middle():
    hand = left_index_only()
    hand[9] = lm(0.50, 0.5)
    hand[10] = lm(0.50, 0.35)
    hand[12] = lm(0.50, 0.2)  # middle extended too
    return hand


def left_open_palm():
    return right_fingers_up()  # all four main fingers extended = open palm


def test_right_fingers_up():
    assert classify_right_hand(right_fingers_up()) == THROTTLE_UP


def test_right_fingers_down():
    assert classify_right_hand(right_fingers_down()) == THROTTLE_DOWN


def test_right_fist():
    assert classify_right_hand(right_fist()) == THROTTLE_HOLD


def test_left_thumb_left():
    assert classify_left_hand(left_thumb_left()) == ROLL_LEFT


def test_left_thumb_right():
    assert classify_left_hand(left_thumb_right()) == ROLL_RIGHT


def test_left_index_only_is_forward():
    assert classify_left_hand(left_index_only()) == PITCH_FORWARD


def test_left_index_middle_is_backward():
    assert classify_left_hand(left_index_middle()) == PITCH_BACKWARD


def test_left_open_palm_is_neutral():
    assert classify_left_hand(left_open_palm()) == DIRECTION_NEUTRAL


def test_debouncer_holds_until_stable_duration():
    d = GestureDebouncer(THROTTLE_HOLD, debounce_ms=100)
    t = 0.0
    assert d.update(THROTTLE_UP, now=t) == THROTTLE_HOLD  # not yet stable
    t += 0.05
    assert d.update(THROTTLE_UP, now=t) == THROTTLE_HOLD  # still not 100ms
    t += 0.06
    assert d.update(THROTTLE_UP, now=t) == THROTTLE_UP  # now stable


def test_debouncer_resets_candidate_on_flicker():
    d = GestureDebouncer(THROTTLE_HOLD, debounce_ms=100)
    t = 0.0
    d.update(THROTTLE_UP, now=t)
    t += 0.08
    d.update(RIGHT_UNKNOWN, now=t)  # flicker resets the candidate timer
    t += 0.05
    assert d.update(RIGHT_UNKNOWN, now=t) == THROTTLE_HOLD  # only 50ms since flicker


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
