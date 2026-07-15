"""EMA output smoothing on the Pi side — spec section 16.
Runs on normalized command values (throttle 0..1, pitch/roll -1..1),
BEFORE calibration mapping to DAC codes."""


class AxisFilter:
    def __init__(self, alpha=0.3, initial=0.0):
        self.alpha = alpha
        self.filtered = initial

    def update(self, target):
        self.filtered += self.alpha * (target - self.filtered)
        return self.filtered

    def snap_to(self, value):
        self.filtered = value
        return self.filtered


class OutputFilters:
    def __init__(self, throttle_alpha=0.3, pitch_alpha=0.4, roll_alpha=0.4):
        self.throttle = AxisFilter(throttle_alpha, initial=0.0)
        self.pitch = AxisFilter(pitch_alpha, initial=0.0)
        self.roll = AxisFilter(roll_alpha, initial=0.0)

    def update(self, throttle_target, pitch_target, roll_target):
        return (
            self.throttle.update(throttle_target),
            self.pitch.update(pitch_target),
            self.roll.update(roll_target),
        )
