"""
MediaPipe Hand Landmarker wrapper.

Runs in LIVE_STREAM mode per spec section 4. Since LIVE_STREAM is
callback-based and may drop frames, the main loop should always read
get_latest() rather than expecting one result per camera frame.

Also implements basic handedness continuity (spec section 5): if
MediaPipe's handedness label briefly swaps or a hand drops out for a
frame or two, we keep the previous role assignment based on wrist
position proximity rather than instantly reassigning control roles.
"""

import math
import time

import mediapipe as mp

VisionRunningMode = mp.tasks.vision.RunningMode


class HandTracker:
    def __init__(self, model_path, num_hands=2,
                 min_hand_detection_confidence=0.6,
                 min_hand_presence_confidence=0.6,
                 min_tracking_confidence=0.6,
                 continuity_timeout_s=0.3,
                 continuity_max_dist=0.15):
        self._latest = None
        self._latest_ts = 0
        self.continuity_timeout_s = continuity_timeout_s
        self.continuity_max_dist = continuity_max_dist
        # role -> (wrist_x, wrist_y, last_seen_time)
        self._role_history = {"Left": None, "Right": None}

        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=VisionRunningMode.LIVE_STREAM,
            num_hands=num_hands,
            min_hand_detection_confidence=min_hand_detection_confidence,
            min_hand_presence_confidence=min_hand_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
            result_callback=self._on_result,
        )
        self.landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self._frame_idx = 0

    def _on_result(self, result, output_image, timestamp_ms):
        self._latest = result
        self._latest_ts = timestamp_ms

    def detect_async(self, mp_image):
        ts_ms = int(time.time() * 1000)
        self.landmarker.detect_async(mp_image, ts_ms)
        self._frame_idx += 1

    def get_latest_hands(self):
        """Returns list of (role, landmarks) where role is 'Left' or
        'Right', using continuity to smooth over brief handedness flips."""
        result = self._latest
        if result is None or not result.hand_landmarks:
            return []

        now = time.time()
        raw_hands = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            label = handedness[0].category_name  # MediaPipe's raw guess
            wrist = landmarks[0]
            raw_hands.append((label, (wrist.x, wrist.y), landmarks))

        assigned = []
        used_roles = set()

        # First pass: try to match each detected hand to its previous role
        # by wrist proximity, so a brief label flip doesn't switch roles.
        for label, wrist_pos, landmarks in raw_hands:
            best_role = None
            best_dist = None
            for role in ("Left", "Right"):
                if role in used_roles:
                    continue
                hist = self._role_history[role]
                if hist is None:
                    continue
                hx, hy, last_seen = hist
                if now - last_seen > self.continuity_timeout_s:
                    continue
                dist = math.hypot(wrist_pos[0] - hx, wrist_pos[1] - hy)
                if dist <= self.continuity_max_dist and (best_dist is None or dist < best_dist):
                    best_role, best_dist = role, dist

            role = best_role if best_role else label
            if role not in ("Left", "Right"):
                role = label  # fall back to raw label if something odd
            used_roles.add(role)
            self._role_history[role] = (wrist_pos[0], wrist_pos[1], now)
            assigned.append((role, landmarks))

        return assigned

    def close(self):
        self.landmarker.close()
