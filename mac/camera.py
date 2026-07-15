"""Camera capture wrapper — MacBook built-in camera."""

import cv2


class Camera:
    def __init__(self, index=0, width=640, height=480):
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera index {index}")

    def read(self, mirror=True):
        ok, frame = self.cap.read()
        if not ok:
            return None
        if mirror:
            frame = cv2.flip(frame, 1)
        return frame

    def release(self):
        self.cap.release()
