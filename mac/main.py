"""
Mac side main loop — Hand-Gesture Drone Flight
CSIS-418 | Team Ginyard International Co.

Usage:
    python main.py --pi-host 192.168.1.50 --port 5005 --camera 0 --mirror --show-landmarks
    python main.py --dry-run   # full tracking, no packets sent
"""

import argparse
import csv
import json
import os
import time

import cv2
import mediapipe as mp

from camera import Camera
from hand_tracker import HandTracker
from gesture_classifier import (
    classify_right_hand, classify_left_hand, GestureDebouncer,
    RIGHT_MISSING, LEFT_MISSING,
    THROTTLE_UP, THROTTLE_DOWN, THROTTLE_HOLD,
    ROLL_LEFT, ROLL_RIGHT, PITCH_FORWARD, PITCH_BACKWARD, DIRECTION_NEUTRAL,
    right_hand_diagnostics, left_hand_diagnostics,
)
from command_controller import CommandController, ARMED, EMERGENCY_STOP
from target_tracker import TargetChangeTracker
from udp_sender import UdpLink
import overlay


TARGET_NONE = "NONE"

# keys for tagging what gesture the tester is ACTUALLY doing, so logs can
# later be scored against what got detected. kept separate from the real
# flight controls (a/d/space/q) so they can't be mixed up mid-flight.
# right hand = digit row (1/2/3 = up/down/hold, 0 = clear back to NONE)
# left hand = first letter of the gesture (f/b/l/r/n, x = clear)
RIGHT_TARGET_KEYS = {
    ord("1"): THROTTLE_UP,
    ord("2"): THROTTLE_DOWN,
    ord("3"): THROTTLE_HOLD,
    ord("0"): TARGET_NONE,
}
LEFT_TARGET_KEYS = {
    ord("f"): PITCH_FORWARD,
    ord("b"): PITCH_BACKWARD,
    ord("l"): ROLL_LEFT,
    ord("r"): ROLL_RIGHT,
    ord("n"): DIRECTION_NEUTRAL,
    ord("x"): TARGET_NONE,
}

GROUND_TRUTH_LEGEND = (
    "Ground truth (right): 1=THROTTLE_UP  2=THROTTLE_DOWN  3=THROTTLE_HOLD  0=NONE\n"
    "Ground truth (left):  f=PITCH_FORWARD  b=PITCH_BACKWARD  l=ROLL_LEFT  "
    "r=ROLL_RIGHT  n=DIRECTION_NEUTRAL  x=NONE"
)


def load_config(path):
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    parser.add_argument("--pi-host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--mirror", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true", help="track hands, do not send UDP packets")
    parser.add_argument("--show-landmarks", action="store_true")
    parser.add_argument("--show-angles", action="store_true")
    parser.add_argument("--log-file", default=os.path.join(os.path.dirname(__file__), "..", "logs", "mac_log.csv"))
    parser.add_argument("--throttle-rate", type=float, default=None)
    parser.add_argument("--direction-strength", type=float, default=None,
                         help="fallback for --pitch-strength/--roll-strength when they're not set")
    parser.add_argument("--pitch-strength", type=float, default=None)
    parser.add_argument("--roll-strength", type=float, default=None)
    parser.add_argument("--debounce-ms", type=int, default=None)
    parser.add_argument("--test-label", default="unlabeled",
                         help="tag for this test session, written to every CSV row as test_condition "
                              "(e.g. --test-label low-light-3m)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    overlay.SHOW_LANDMARKS = args.show_landmarks
    pi_host = args.pi_host or cfg["network"]["pi_host"]
    port = args.port or cfg["network"]["port"]
    throttle_rate = args.throttle_rate or cfg["control"]["throttle_rate"]
    direction_strength = args.direction_strength or cfg["control"]["direction_strength"]
    pitch_strength = args.pitch_strength or args.direction_strength \
        or cfg["control"].get("pitch_strength", direction_strength)
    roll_strength = args.roll_strength or args.direction_strength \
        or cfg["control"].get("roll_strength", direction_strength)
    debounce_ms = args.debounce_ms or cfg["control"]["debounce_ms"]
    angle_thresh = cfg["control"]["angle_threshold_deg"]

    model_path = os.path.join(os.path.dirname(__file__), "..", "models", "hand_landmarker.task")

    camera = Camera(index=args.camera, width=cfg["camera"]["width"], height=cfg["camera"]["height"])
    tracker = HandTracker(
        model_path=model_path,
        min_hand_detection_confidence=cfg["mediapipe"]["min_hand_detection_confidence"],
        min_hand_presence_confidence=cfg["mediapipe"]["min_hand_presence_confidence"],
        min_tracking_confidence=cfg["mediapipe"]["min_tracking_confidence"],
    )
    controller = CommandController(
        throttle_rate=throttle_rate,
        pitch_strength=pitch_strength,
        roll_strength=roll_strength,
        right_missing_descent_rate=cfg["control"]["right_missing_descent_rate"],
    )
    link = None if args.dry_run else UdpLink(pi_host, port)

    right_debouncer = GestureDebouncer(RIGHT_MISSING, debounce_ms=debounce_ms)
    left_debouncer = GestureDebouncer(LEFT_MISSING, debounce_ms=debounce_ms)

    # csv log setup — this is what the analysis script in tools/ reads later
    os.makedirs(os.path.dirname(args.log_file), exist_ok=True)
    log_f = open(args.log_file, "w", newline="")
    log_writer = csv.writer(log_f)
    log_writer.writerow([
        "timestamp", "right_detected", "left_detected", "right_raw", "right_stable",
        "left_raw", "left_stable", "throttle", "pitch", "roll", "sequence",
        "armed_state", "pi_status_age_ms",
        "target_right_gesture", "target_left_gesture", "round_trip_ms", "test_condition",
        "right_margin_deg", "left_thumb_margin_deg",
        "right_hand_raw_label", "left_hand_raw_label", "frames_since_target_change", "fps",
    ])

    fps_t0 = time.monotonic()
    fps_count = 0
    fps = 0.0

    # nobody's tagged a ground-truth gesture yet, so default to NONE for both
    # hands — otherwise frames before the tester sets anything would get
    # counted as "wrong" against whatever the last target happened to be
    target_right = TARGET_NONE
    target_left = TARGET_NONE
    target_change_tracker = TargetChangeTracker()

    print("Controls: a=arm  d=disarm  space=emergency stop  q=quit")
    print(GROUND_TRUTH_LEGEND)

    try:
        while True:
            frame = camera.read(mirror=args.mirror)
            if frame is None:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            tracker.detect_async(mp_image)
            hands = tracker.get_latest_hands()

            right_landmarks = None
            right_hand_raw_label = None
            left_landmarks = None
            left_hand_raw_label = None
            for role, raw_label, landmarks in hands:
                if role == "Right":
                    right_landmarks = landmarks
                    right_hand_raw_label = raw_label
                elif role == "Left":
                    left_landmarks = landmarks
                    left_hand_raw_label = raw_label

            right_raw = classify_right_hand(right_landmarks, angle_thresh) if right_landmarks else RIGHT_MISSING
            left_raw = classify_left_hand(left_landmarks, angle_thresh) if left_landmarks else LEFT_MISSING

            # just for the CSV/report, doesn't feed into control at all
            right_margin_deg = right_hand_diagnostics(right_landmarks, angle_thresh)["margin_deg"] \
                if right_landmarks else None
            left_thumb_margin_deg = left_hand_diagnostics(left_landmarks, angle_thresh)["thumb_margin_deg"] \
                if left_landmarks else None

            right_stable = right_debouncer.update(right_raw)
            left_stable = left_debouncer.update(left_raw)

            throttle, pitch, roll = controller.update(right_stable, left_stable)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("a"):
                network_healthy = link is not None and link.status_age_s() is not None and link.status_age_s() < 2.0
                ok, msg = controller.try_arm(network_healthy or args.dry_run)
                print(f"[ARM] {msg}")
            elif key == ord("d"):
                controller.disarm()
                print("[DISARM]")
            elif key == ord(" "):
                controller.emergency_stop()
                print("[EMERGENCY STOP]")
            elif key in RIGHT_TARGET_KEYS:
                target_right = RIGHT_TARGET_KEYS[key]
                print(f"[GROUND TRUTH] right = {target_right}")
            elif key in LEFT_TARGET_KEYS:
                target_left = LEFT_TARGET_KEYS[key]
                print(f"[GROUND TRUTH] left = {target_left}")

            frames_since_target_change = target_change_tracker.update(target_right, target_left)

            armed = controller.state == ARMED
            seq = None
            if link is not None:
                packet = link.send(
                    armed=armed,
                    emergency_stop=(controller.state == EMERGENCY_STOP),
                    throttle=throttle, pitch=pitch, roll=roll,
                    right_gesture=right_stable, left_gesture=left_stable,
                )
                seq = packet["sequence"]
                status = link.poll_status()
                pi_connected = status is not None and link.status_age_s() is not None and link.status_age_s() < 1.0
                status_age = link.status_age_s()
                round_trip_s = link.get_last_round_trip_s()
            else:
                pi_connected = False
                status_age = None
                round_trip_s = None

            fps_count += 1
            if time.monotonic() - fps_t0 >= 1.0:
                fps = fps_count / (time.monotonic() - fps_t0)
                fps_count = 0
                fps_t0 = time.monotonic()

            if overlay.SHOW_LANDMARKS:
                if right_landmarks is not None:
                    overlay.draw_hand_skeleton(frame, right_landmarks, (60, 180, 255))
                if left_landmarks is not None:
                    overlay.draw_hand_skeleton(frame, left_landmarks, (120, 240, 120))

            overlay.draw_overlay(
                frame,
                right_hand_present=right_landmarks is not None,
                left_hand_present=left_landmarks is not None,
                right_raw=right_raw, right_stable=right_stable,
                left_raw=left_raw, left_stable=left_stable,
                throttle=throttle, pitch=pitch, roll=roll,
                state=controller.state,
                pi_connected=pi_connected,
                status_age_s=status_age,
                fps=fps,
                right_raw_label=right_hand_raw_label,
                left_raw_label=left_hand_raw_label,
                round_trip_s=round_trip_s,
            )
            cv2.imshow("Hand-Gesture Drone Flight", frame)
            if cv2.getWindowProperty("Hand-Gesture Drone Flight", cv2.WND_PROP_VISIBLE) < 1:
                break

            log_writer.writerow([
                time.time(), right_landmarks is not None, left_landmarks is not None,
                right_raw, right_stable, left_raw, left_stable,
                f"{throttle:.3f}", f"{pitch:.3f}", f"{roll:.3f}", seq,
                controller.state, f"{status_age * 1000:.0f}" if status_age is not None else "",
                target_right, target_left,
                f"{round_trip_s * 1000:.1f}" if round_trip_s is not None else "",
                args.test_label,
                f"{right_margin_deg:.2f}" if right_margin_deg is not None else "",
                f"{left_thumb_margin_deg:.2f}" if left_thumb_margin_deg is not None else "",
                right_hand_raw_label or "", left_hand_raw_label or "",
                frames_since_target_change, f"{fps:.1f}",
            ])

    finally:
        # always clean up, even if something above throws
        camera.release()
        cv2.destroyAllWindows()
        tracker.close()
        if link is not None:
            link.close()
        log_f.close()


if __name__ == "__main__":
    main()
