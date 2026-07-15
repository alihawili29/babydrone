"""
UDP receiver — spec sections 11 (validation) and 12 (status packet).

validate_packet() is a pure function (dict in, (ok, reason, clamped_packet)
out) so it can be unit tested without a real socket.
"""

import json
import math
import socket

REQUIRED_FIELDS = {
    "version": int, "session": str, "sequence": int, "mac_time_ms": int,
    "armed": bool, "emergency_stop": bool, "throttle": (int, float),
    "pitch": (int, float), "roll": (int, float),
    "right_gesture": str, "left_gesture": str,
}
SUPPORTED_VERSION = 1


def validate_packet(packet: dict, *, last_sequence=None, current_session=None,
                     is_armed=False):
    """Returns (ok: bool, reason: str, packet: dict|None).
    On success, numeric fields are clamped into range."""
    if not isinstance(packet, dict):
        return False, "not a JSON object", None

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in packet:
            return False, f"missing field: {field}", None
        if not isinstance(packet[field], expected_type):
            return False, f"wrong type for field: {field}", None

    if packet["version"] != SUPPORTED_VERSION:
        return False, f"unsupported version: {packet['version']}", None

    for field in ("throttle", "pitch", "roll"):
        v = packet[field]
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return False, f"NaN/inf value in field: {field}", None

    if not (0.0 <= packet["throttle"] <= 1.0):
        return False, "throttle out of range", None
    if not (-1.0 <= packet["pitch"] <= 1.0):
        return False, "pitch out of range", None
    if not (-1.0 <= packet["roll"] <= 1.0):
        return False, "roll out of range", None

    if last_sequence is not None and packet["sequence"] <= last_sequence:
        return False, "old or duplicate sequence number", None

    if is_armed and current_session is not None and packet["session"] != current_session:
        return False, "unexpected session change while armed", None

    packet = dict(packet)
    packet["throttle"] = max(0.0, min(1.0, packet["throttle"]))
    packet["pitch"] = max(-1.0, min(1.0, packet["pitch"]))
    packet["roll"] = max(-1.0, min(1.0, packet["roll"]))
    return True, "ok", packet


class UdpReceiver:
    def __init__(self, listen_ip, listen_port, allowed_source_ip=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.sock.bind((listen_ip, listen_port))
        self.allowed_source_ip = allowed_source_ip
        self.last_sender_addr = None

    def poll(self):
        """Returns list of (raw_dict_or_None, source_addr, parse_error)
        for all packets currently waiting."""
        results = []
        try:
            while True:
                data, addr = self.sock.recvfrom(4096)
                if self.allowed_source_ip and addr[0] != self.allowed_source_ip:
                    results.append((None, addr, "unauthorized source IP"))
                    continue
                try:
                    packet = json.loads(data.decode("utf-8"))
                    results.append((packet, addr, None))
                    self.last_sender_addr = addr
                except (json.JSONDecodeError, UnicodeDecodeError):
                    results.append((None, addr, "invalid JSON"))
        except BlockingIOError:
            pass
        return results

    def send_status(self, status: dict):
        if self.last_sender_addr is None:
            return
        data = json.dumps(status).encode("utf-8")
        try:
            self.sock.sendto(data, self.last_sender_addr)
        except OSError:
            pass

    def close(self):
        self.sock.close()
