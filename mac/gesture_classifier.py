"""
Gesture classification — spec sections 6, 7, 9.

Classification functions are pure (take landmarks, return a state string)
so they can be unit tested without a camera or MediaPipe running.
Landmarks just need .x / .y attributes (MediaPipe's NormalizedLandmark
works directly; tests can use a simple namedtuple/SimpleNamespace).
"""

import math
import time
from dataclasses import dataclass

# --- Right hand states ---
THROTTLE_UP = "THROTTLE_UP"
THROTTLE_DOWN = "THROTTLE_DOWN"
THROTTLE_HOLD = "THROTTLE_HOLD"
RIGHT_UNKNOWN = "RIGHT_UNKNOWN"
RIGHT_MISSING = "RIGHT_MISSING"

# --- Left hand states ---
ROLL_LEFT = "ROLL_LEFT"
ROLL_RIGHT = "ROLL_RIGHT"
PITCH_FORWARD = "PITCH_FORWARD"
PITCH_BACKWARD = "PITCH_BACKWARD"
DIRECTION_NEUTRAL = "DIRECTION_NEUTRAL"
LEFT_UNKNOWN = "LEFT_UNKNOWN"
LEFT_MISSING = "LEFT_MISSING"

# Finger vectors, reused from the reference repo (base -> tip)
_FINGER_BASE_TIP = {
    "index": (5, 8),
    "middle": (9, 12),
    "ring": (13, 16),
    "pinky": (17, 20),
}
WRIST = 0
THUMB_TIP, THUMB_IP, THUMB_MCP = 4, 3, 2


def _angle_from_vertical(dx, dy):
    """0deg = straight up, 180deg = straight down."""
    return math.degrees(math.atan2(abs(dx), -dy))


def _is_finger_extended(landmarks, tip_idx, pip_idx, mcp_idx):
    tip, pip, mcp = landmarks[tip_idx], landmarks[pip_idx], landmarks[mcp_idx]
    return tip.y < pip.y < mcp.y


# PIP indices for the four main fingers (needed for extended/folded checks)
_FINGER_PIP = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}
_FINGER_MCP = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}
_FINGER_TIP = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}


def _finger_openness(landmarks):
    """Direction-agnostic fist check: ratio of tip-to-wrist distance vs
    mcp-to-wrist distance, averaged over the four main fingers. A curled
    fist has tips close to the wrist regardless of which way the hand is
    facing; a check based on 'tip above pip above mcp' only catches
    fingers pointing up, which incorrectly flags a fingers-down pose as
    a fist too."""
    wrist = landmarks[WRIST]
    tip_total, mcp_total = 0.0, 0.0
    for base_idx, tip_idx in _FINGER_BASE_TIP.values():
        mcp, tip = landmarks[base_idx], landmarks[tip_idx]
        tip_total += math.hypot(tip.x - wrist.x, tip.y - wrist.y)
        mcp_total += math.hypot(mcp.x - wrist.x, mcp.y - wrist.y)
    return tip_total / max(mcp_total, 1e-6)


def classify_right_hand(landmarks, angle_threshold_deg=45.0, openness_threshold=1.3):
    """Right hand: throttle up/down/hold. Spec section 6.
    Thumb is intentionally excluded."""
    up_count, down_count = 0, 0

    for base_idx, tip_idx in _FINGER_BASE_TIP.values():
        base, tip = landmarks[base_idx], landmarks[tip_idx]
        dx, dy = tip.x - base.x, tip.y - base.y
        ang = _angle_from_vertical(dx, dy)
        if ang <= angle_threshold_deg:
            up_count += 1
        elif ang >= (180 - angle_threshold_deg):
            down_count += 1

    if _finger_openness(landmarks) < openness_threshold:
        return THROTTLE_HOLD
    if up_count == 4:
        return THROTTLE_UP
    if down_count == 4:
        return THROTTLE_DOWN
    return RIGHT_UNKNOWN


def classify_left_hand(landmarks, thumb_angle_threshold_deg=45.0):
    """Left hand: roll/pitch. Spec section 7, recognition priority order:
    1. open palm -> neutral
    2. index only -> forward
    3. index+middle only -> backward
    4. thumb-only left/right -> roll
    5. anything else -> neutral
    """
    index_ext = _is_finger_extended(landmarks, _FINGER_TIP["index"], _FINGER_PIP["index"], _FINGER_MCP["index"])
    middle_ext = _is_finger_extended(landmarks, _FINGER_TIP["middle"], _FINGER_PIP["middle"], _FINGER_MCP["middle"])
    ring_ext = _is_finger_extended(landmarks, _FINGER_TIP["ring"], _FINGER_PIP["ring"], _FINGER_MCP["ring"])
    pinky_ext = _is_finger_extended(landmarks, _FINGER_TIP["pinky"], _FINGER_PIP["pinky"], _FINGER_MCP["pinky"])

    wrist = landmarks[WRIST]
    thumb_tip = landmarks[THUMB_TIP]
    thumb_mcp = landmarks[THUMB_MCP]
    thumb_dx = thumb_tip.x - wrist.x
    thumb_dy = thumb_tip.y - wrist.y
    thumb_extended = math.hypot(thumb_tip.x - thumb_mcp.x, thumb_tip.y - thumb_mcp.y) > \
        math.hypot(landmarks[THUMB_IP].x - thumb_mcp.x, landmarks[THUMB_IP].y - thumb_mcp.y) * 0.8

    # 1. Open palm -> neutral (all four main fingers extended)
    if index_ext and middle_ext and ring_ext and pinky_ext:
        return DIRECTION_NEUTRAL

    # 2. Index only -> forward
    if index_ext and not middle_ext and not ring_ext and not pinky_ext:
        return PITCH_FORWARD

    # 3. Index + middle only -> backward
    if index_ext and middle_ext and not ring_ext and not pinky_ext:
        return PITCH_BACKWARD

    # 4. Thumb-only left/right -> roll (requires all four main fingers folded)
    all_main_folded = not index_ext and not middle_ext and not ring_ext and not pinky_ext
    if all_main_folded and thumb_extended:
        angle_from_horizontal = math.degrees(math.atan2(abs(thumb_dy), abs(thumb_dx)))
        if angle_from_horizontal <= thumb_angle_threshold_deg:
            return ROLL_LEFT if thumb_dx < 0 else ROLL_RIGHT

    # 5. Anything else -> neutral
    return DIRECTION_NEUTRAL


@dataclass
class DebouncedState:
    stable: str
    candidate: str = None
    candidate_since: float = 0.0


class GestureDebouncer:
    """Time-based debouncing per spec section 9: a new gesture only
    becomes stable after remaining consistent for debounce_ms."""

    def __init__(self, initial_state, debounce_ms=125):
        self.debounce_s = debounce_ms / 1000.0
        self._state = DebouncedState(stable=initial_state)

    def update(self, raw_gesture, now=None):
        now = now if now is not None else time.monotonic()
        s = self._state
        if raw_gesture == s.stable:
            s.candidate = None
            s.candidate_since = 0.0
            return s.stable

        if raw_gesture != s.candidate:
            s.candidate = raw_gesture
            s.candidate_since = now
            return s.stable

        if now - s.candidate_since >= self.debounce_s:
            s.stable = raw_gesture
            s.candidate = None
            s.candidate_since = 0.0

        return s.stable

    @property
    def stable(self):
        return self._state.stable
