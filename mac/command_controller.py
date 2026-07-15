"""
Command controller — spec sections 6 (throttle integration), 8
(simultaneous control), 10 (arming state machine).

Keeps three independent axis commands: throttle (0.0-1.0, persistent,
rate-integrated), pitch and roll (-1.0..1.0, magnitude-based, not
integrated). Right and left hand gestures are processed independently —
no combined gesture classes.
"""

import time

from gesture_classifier import (
    THROTTLE_UP, THROTTLE_DOWN, THROTTLE_HOLD, RIGHT_MISSING,
    ROLL_LEFT, ROLL_RIGHT, PITCH_FORWARD, PITCH_BACKWARD,
)

DISARMED = "DISARMED"
ARMED = "ARMED"
FAILSAFE = "FAILSAFE"
EMERGENCY_STOP = "EMERGENCY_STOP"


class CommandController:
    def __init__(self, throttle_rate=0.25, direction_strength=0.25,
                 right_missing_descent_rate=0.25):
        self.throttle_target = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.throttle_rate = throttle_rate
        self.direction_strength = direction_strength
        self.right_missing_descent_rate = right_missing_descent_rate

        self.state = DISARMED
        self._last_update = time.monotonic()

    # --- arming ---

    def try_arm(self, network_healthy):
        if self.state == EMERGENCY_STOP:
            return False, "cannot arm from EMERGENCY_STOP, disarm first"
        if self.throttle_target > 0.01:
            return False, "throttle target must be at minimum to arm"
        if not network_healthy:
            return False, "network connection to Raspberry Pi is not healthy"
        self.state = ARMED
        return True, "armed"

    def disarm(self):
        self.state = DISARMED

    def emergency_stop(self):
        self.throttle_target = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.state = EMERGENCY_STOP

    # --- per-frame update ---

    def update(self, right_gesture, left_gesture, now=None):
        now = now if now is not None else time.monotonic()
        dt = max(0.0, now - self._last_update)
        self._last_update = now

        if self.state in (DISARMED, EMERGENCY_STOP):
            # Commands still computed for display, but not meaningful
            # until armed — main.py is responsible for not transmitting
            # non-zero commands while disarmed.
            pass

        # Right hand -> throttle target (persistent, rate-integrated)
        if right_gesture == THROTTLE_UP:
            self.throttle_target += self.throttle_rate * dt
        elif right_gesture == THROTTLE_DOWN:
            self.throttle_target -= self.throttle_rate * dt
        elif right_gesture == THROTTLE_HOLD:
            pass  # unchanged
        elif right_gesture == RIGHT_MISSING:
            self.throttle_target -= self.right_missing_descent_rate * dt
        # RIGHT_UNKNOWN -> hold current throttle briefly (no-op, same as HOLD)

        self.throttle_target = max(0.0, min(1.0, self.throttle_target))

        # Left hand -> pitch/roll (not integrated, just magnitude-based)
        if left_gesture == PITCH_FORWARD:
            self.pitch = self.direction_strength
        elif left_gesture == PITCH_BACKWARD:
            self.pitch = -self.direction_strength
        elif left_gesture == ROLL_LEFT:
            self.roll = -self.direction_strength
        elif left_gesture == ROLL_RIGHT:
            self.roll = self.direction_strength
        else:  # DIRECTION_NEUTRAL, LEFT_UNKNOWN, LEFT_MISSING
            self.pitch = 0.0
            self.roll = 0.0

        return self.throttle_target, self.pitch, self.roll
