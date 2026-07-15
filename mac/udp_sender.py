"""
UDP sender — spec section 11 (packet format) and 12 (status packet).
Uses Python's built-in socket module only, per spec.
"""

import json
import socket
import time
import uuid


class UdpLink:
    def __init__(self, pi_host, pi_port):
        self.pi_addr = (pi_host, pi_port)
        self.session = uuid.uuid4().hex[:8]
        self.sequence = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self._last_status = None
        self._last_status_time = 0.0

    def send(self, armed, emergency_stop, throttle, pitch, roll,
              right_gesture, left_gesture):
        packet = {
            "version": 1,
            "session": self.session,
            "sequence": self.sequence,
            "mac_time_ms": int(time.monotonic() * 1000),
            "armed": bool(armed),
            "emergency_stop": bool(emergency_stop),
            "throttle": float(throttle),
            "pitch": float(pitch),
            "roll": float(roll),
            "right_gesture": right_gesture,
            "left_gesture": left_gesture,
        }
        self.sequence += 1
        data = json.dumps(packet).encode("utf-8")
        try:
            self.sock.sendto(data, self.pi_addr)
        except OSError:
            pass  # network hiccup; watchdog on the Pi side handles staleness
        return packet

    def poll_status(self):
        """Non-blocking read of the optional Pi status packet.
        Returns the most recent status dict, or None if nothing new
        has arrived (keeps returning the last known status)."""
        try:
            while True:
                data, _addr = self.sock.recvfrom(4096)
                try:
                    self._last_status = json.loads(data.decode("utf-8"))
                    self._last_status_time = time.monotonic()
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
        except BlockingIOError:
            pass
        return self._last_status

    def status_age_s(self):
        if self._last_status is None:
            return None
        return time.monotonic() - self._last_status_time

    def close(self):
        self.sock.close()
