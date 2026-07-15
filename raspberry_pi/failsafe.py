"""
Watchdog and failsafe — spec section 17.

Independent safety authority on the Pi: does not trust the Mac to
behave correctly. If no valid packet arrives within timeout_ms, pitch
and roll centre immediately and throttle ramps down gradually. Exiting
FAILSAFE requires several consecutive valid, armed packets — one
packet reappearing is not enough.
"""

DISARMED = "DISARMED"
ARMED = "ARMED"
FAILSAFE = "FAILSAFE"
EMERGENCY_STOP = "EMERGENCY_STOP"


class Watchdog:
    def __init__(self, timeout_s=0.5, failsafe_descent_rate=0.5,
                 required_consecutive_valid=5, i2c_fail_threshold=5):
        self.timeout_s = timeout_s
        self.failsafe_descent_rate = failsafe_descent_rate
        self.required_consecutive_valid = required_consecutive_valid
        self.i2c_fail_threshold = i2c_fail_threshold

        self.state = DISARMED
        self.last_valid_time = None
        self.consecutive_valid = 0
        self.failsafe_throttle = 0.0
        self.i2c_fail_count = 0

    def on_valid_packet(self, now, armed, emergency_stop):
        self.last_valid_time = now

        if emergency_stop:
            self.state = EMERGENCY_STOP
            self.consecutive_valid = 0
            return

        if self.state == FAILSAFE:
            self.consecutive_valid += 1
            if armed and self.consecutive_valid >= self.required_consecutive_valid:
                self.state = ARMED
                self.consecutive_valid = 0
        elif self.state == EMERGENCY_STOP:
            if not armed:
                self.state = DISARMED
        else:
            self.state = ARMED if armed else DISARMED
            self.consecutive_valid += 1

    def tick(self, now, dt, current_throttle_target):
        """Call every loop iteration. Returns (state, throttle_override).
        throttle_override is None unless in FAILSAFE, in which case the
        caller should use it instead of the packet's throttle value, and
        should force pitch/roll to 0 regardless."""
        if self.last_valid_time is None:
            return self.state, None

        age = now - self.last_valid_time
        if age > self.timeout_s and self.state == ARMED:
            self.state = FAILSAFE
            self.failsafe_throttle = current_throttle_target
            self.consecutive_valid = 0

        if self.state == FAILSAFE:
            self.failsafe_throttle = max(0.0, self.failsafe_throttle - self.failsafe_descent_rate * dt)
            return self.state, self.failsafe_throttle

        return self.state, None

    def record_i2c_failure(self):
        """Returns True if the failure threshold was just crossed and the
        caller should enter a safe state (centre pitch/roll, reduce
        throttle, disarm) per spec."""
        self.i2c_fail_count += 1
        if self.i2c_fail_count >= self.i2c_fail_threshold:
            self.state = DISARMED
            return True
        return False

    def record_i2c_success(self):
        self.i2c_fail_count = 0
