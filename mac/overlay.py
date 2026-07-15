"""Preview window overlay — spec section 21."""

import cv2

GREEN = (0, 200, 0)
RED = (0, 0, 220)
BLUE = (220, 120, 0)
GRAY = (150, 150, 150)
ORANGE = (0, 140, 255)

_THROTTLE_COLOR = {"THROTTLE_UP": GREEN, "THROTTLE_DOWN": RED}
_LEFT_COLOR = {
    "ROLL_LEFT": BLUE, "ROLL_RIGHT": BLUE,
    "PITCH_FORWARD": BLUE, "PITCH_BACKWARD": BLUE,
}


def draw_overlay(frame, *, right_hand_present, left_hand_present,
                  right_raw, right_stable, left_raw, left_stable,
                  throttle, pitch, roll, state, pi_connected,
                  status_age_s, fps):
    y = 24
    line_h = 22

    def put(text, color=(255, 255, 255)):
        nonlocal y
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        y += line_h

    put(f"RIGHT: {'detected' if right_hand_present else 'MISSING'}",
        GREEN if right_hand_present else ORANGE)
    put(f"  raw={right_raw}  stable={right_stable}",
        _THROTTLE_COLOR.get(right_stable, GRAY))

    put(f"LEFT: {'detected' if left_hand_present else 'MISSING'}",
        GREEN if left_hand_present else ORANGE)
    put(f"  raw={left_raw}  stable={left_stable}",
        _LEFT_COLOR.get(left_stable, GRAY))

    put(f"Throttle: {throttle * 100:.0f}%")
    put(f"Pitch: {pitch:+.2f}   Roll: {roll:+.2f}")

    state_color = {
        "ARMED": GREEN, "DISARMED": GRAY,
        "FAILSAFE": ORANGE, "EMERGENCY_STOP": RED,
    }.get(state, GRAY)
    put(f"STATE: {state}", state_color)

    put(f"PI: {'CONNECTED' if pi_connected else 'NO STATUS'}",
        GREEN if pi_connected else RED)
    if status_age_s is not None:
        put(f"Last Pi status: {status_age_s * 1000:.0f} ms ago")

    put(f"FPS: {fps:.1f}")
