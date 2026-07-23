"""
Turns gestures into actual throttle/pitch/roll numbers, plus the arm/disarm/
emergency-stop state machine.

Throttle is 0-1 and "sticky" — it integrates over time (holding the gesture
keeps changing it), while pitch/roll are -1 to 1 and just snap straight to
a value based on whatever gesture is currently held. Right and left hands
are handled completely separately, there's no combined gesture logic.
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
                 pitch_strength=None, roll_strength=None,
                 right_missing_descent_rate=0.25):
        self.throttle_target = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.throttle_rate = throttle_rate
        # pitch/roll used to share one "direction_strength" knob. Roll's usable
        # voltage range (PCF8591) is much narrower than pitch's (MCP4725), so
        # they're now independently configurable — both still default to
        # direction_strength when not given, for backward compatibility.
        self.pitch_strength = pitch_strength if pitch_strength is not None else direction_strength
        self.roll_strength = roll_strength if roll_strength is not None else direction_strength
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
            # still crunching the numbers here even while disarmed, just so the
            # HUD has something to show. main.py is the one that actually makes
            # sure we don't send non-zero commands while disarmed.
            pass

        # right hand controls throttle, and it "remembers" — holding UP keeps climbing
        if right_gesture == THROTTLE_UP:
            self.throttle_target += self.throttle_rate * dt
        elif right_gesture == THROTTLE_DOWN:
            self.throttle_target -= self.throttle_rate * dt
        elif right_gesture == THROTTLE_HOLD:
            pass  # leave it where it is
        elif right_gesture == RIGHT_MISSING:
            # lost track of the hand entirely, ease throttle back down instead of just freezing it
            self.throttle_target -= self.right_missing_descent_rate * dt
        # RIGHT_UNKNOWN just falls through and holds too, same as THROTTLE_HOLD

        self.throttle_target = max(0.0, min(1.0, self.throttle_target))

        # left hand controls pitch/roll — these don't accumulate, they just snap to a value
        if left_gesture == PITCH_FORWARD:
            self.pitch = self.pitch_strength
        elif left_gesture == PITCH_BACKWARD:
            self.pitch = -self.pitch_strength
        elif left_gesture == ROLL_LEFT:
            self.roll = -self.roll_strength
        elif left_gesture == ROLL_RIGHT:
            self.roll = self.roll_strength
        else:  # DIRECTION_NEUTRAL, LEFT_UNKNOWN, LEFT_MISSING all just mean "do nothing"
            self.pitch = 0.0
            self.roll = 0.0

        return self.throttle_target, self.pitch, self.roll
