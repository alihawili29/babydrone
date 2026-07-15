"""
Mac main program — Hand-Gesture Drone Flight (Wi-Fi / Raspberry Pi version)
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
)
from command_controller import CommandController, ARMED, EMERGENCY_STOP
from udp_sender import UdpLink
from overlay import draw_overlay


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
    parser.add_argument("--direction-strength", type=float, default=None)
    parser.add_argument("--debounce-ms", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    pi_host = args.pi_host or cfg["network"]["pi_host"]
    port = args.port or cfg["network"]["port"]
    throttle_rate = args.throttle_rate or cfg["control"]["throttle_rate"]
    direction_strength = args.direction_strength or cfg["control"]["direction_strength"]
    debounce_ms = args.debounce_ms or cfg["control"]["debounce_ms"]
    angle_threshold = cfg["control"]["angle_threshold_deg"]

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
        direction_strength=direction_strength,
        right_missing_descent_rate=cfg["control"]["right_missing_descent_rate"],
    )
    link = None if args.dry_run else UdpLink(pi_host, port)

    right_debouncer = GestureDebouncer(RIGHT_MISSING, debounce_ms=debounce_ms)
    left_debouncer = GestureDebouncer(LEFT_MISSING, debounce_ms=debounce_ms)

    os.makedirs(os.path.dirname(args.log_file), exist_ok=True)
    log_f = open(args.log_file, "w", newline="")
    log_writer = csv.writer(log_f)
    log_writer.writerow([
        "timestamp", "right_detected", "left_detected", "right_raw", "right_stable",
        "left_raw", "left_stable", "throttle", "pitch", "roll", "sequence",
        "armed_state", "pi_status_age_ms",
    ])

    fps_t0 = time.monotonic()
    fps_count = 0
    fps = 0.0

    print("Controls: a=arm  d=disarm  space=emergency stop  q=quit")

    try:
        while True:
            frame = camera.read(mirror=args.mirror)
            if frame is None:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            tracker.detect_async(mp_image)
            hands = tracker.get_latest_hands()

            right_landmarks = next((lm for role, lm in hands if role == "Right"), None)
            left_landmarks = next((lm for role, lm in hands if role == "Left"), None)

            right_raw = classify_right_hand(right_landmarks, angle_threshold) if right_landmarks else RIGHT_MISSING
            left_raw = classify_left_hand(left_landmarks, angle_threshold) if left_landmarks else LEFT_MISSING

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
            else:
                pi_connected = False
                status_age = None

            fps_count += 1
            if time.monotonic() - fps_t0 >= 1.0:
                fps = fps_count / (time.monotonic() - fps_t0)
                fps_count = 0
                fps_t0 = time.monotonic()

            draw_overlay(
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
            )
            cv2.imshow("Hand-Gesture Drone Flight", frame)

            log_writer.writerow([
                time.time(), right_landmarks is not None, left_landmarks is not None,
                right_raw, right_stable, left_raw, left_stable,
                f"{throttle:.3f}", f"{pitch:.3f}", f"{roll:.3f}", seq,
                controller.state, f"{status_age * 1000:.0f}" if status_age is not None else "",
            ])

    finally:
        camera.release()
        cv2.destroyAllWindows()
        tracker.close()
        if link is not None:
            link.close()
        log_f.close()


if __name__ == "__main__":
    main()
