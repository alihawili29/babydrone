"""
Raspberry Pi main program — Hand-Gesture Drone Flight
CSIS-418 | Team Ginyard International Co.

Usage:
    python main.py --config config.json --mock-dac --verbose
    python main.py --config config.json   # real I2C hardware
"""

import argparse
import csv
import json
import os
import time

from calibration import Calibration
from failsafe import Watchdog, ARMED, FAILSAFE, EMERGENCY_STOP
from mcp4725 import MCP4725, MockMCP4725
from output_filter import OutputFilters
from udp_receiver import UdpReceiver, validate_packet


def load_config(path):
    with open(path) as f:
        return json.load(f)


def build_dac(cfg, axis, mock, label):
    bus = cfg["dac"][axis]["bus"]
    addr = int(cfg["dac"][axis]["address"], 16) if isinstance(cfg["dac"][axis]["address"], str) \
        else cfg["dac"][axis]["address"]
    if mock:
        return MockMCP4725(bus, addr, label=label)
    return MCP4725(bus, addr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    parser.add_argument("--calibration", default=os.path.join(os.path.dirname(__file__), "calibration.json"))
    parser.add_argument("--mock-dac", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--listen-ip", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--log-file", default=os.path.join(os.path.dirname(__file__), "..", "logs", "pi_log.csv"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    listen_ip = args.listen_ip or cfg["network"]["listen_ip"]
    listen_port = args.port or cfg["network"]["listen_port"]
    watchdog_ms = cfg["network"]["watchdog_ms"]

    calibration = Calibration(args.calibration)
    if not calibration.is_complete() and args.verbose:
        print("[WARN] calibration.json has null placeholders — DAC codes will be "
              "wrong until multimeter calibration is filled in.")

    receiver = UdpReceiver(listen_ip, listen_port)
    watchdog = Watchdog(timeout_s=watchdog_ms / 1000.0)
    filters = OutputFilters(
        throttle_alpha=cfg["smoothing"]["throttle_alpha"],
        pitch_alpha=cfg["smoothing"]["pitch_alpha"],
        roll_alpha=cfg["smoothing"]["roll_alpha"],
    )

    throttle_dac = build_dac(cfg, "throttle", args.mock_dac, "THROTTLE")
    pitch_dac = build_dac(cfg, "pitch", args.mock_dac, "PITCH")
    roll_dac = build_dac(cfg, "roll", args.mock_dac, "ROLL")

    os.makedirs(os.path.dirname(args.log_file), exist_ok=True)
    log_f = open(args.log_file, "w", newline="")
    log_writer = csv.writer(log_f)
    log_writer.writerow([
        "timestamp", "state", "sequence", "packet_age_ms",
        "throttle_target", "pitch_target", "roll_target",
        "throttle_code", "pitch_code", "roll_code", "i2c_ok",
    ])

    last_sequence = None
    current_session = None
    last_throttle_target = 0.0
    pending_throttle_target = 0.0
    pending_pitch_target = 0.0
    pending_roll_target = 0.0
    last_status_send = 0.0

    print(f"Listening on {listen_ip}:{listen_port} "
          f"({'MOCK DAC' if args.mock_dac else 'REAL I2C'})")

    try:
        while True:
            now = time.monotonic()

            for raw_packet, addr, err in receiver.poll():
                if err is not None:
                    if args.verbose:
                        print(f"[REJECT] {err} from {addr}")
                    continue

                is_armed = watchdog.state == ARMED
                ok, reason, packet = validate_packet(
                    raw_packet, last_sequence=last_sequence,
                    current_session=current_session, is_armed=is_armed,
                )
                if not ok:
                    if args.verbose:
                        print(f"[REJECT] {reason}")
                    continue

                last_sequence = packet["sequence"]
                current_session = packet["session"]
                watchdog.on_valid_packet(now, packet["armed"], packet["emergency_stop"])
                last_throttle_target = packet["throttle"]
                pending_throttle_target = packet["throttle"]
                pending_pitch_target = packet["pitch"]
                pending_roll_target = packet["roll"]

            state, throttle_override = watchdog.tick(now, 1.0 / 20.0, last_throttle_target)

            if state == EMERGENCY_STOP:
                throttle_target, pitch_target, roll_target = 0.0, 0.0, 0.0
            elif state == FAILSAFE:
                throttle_target = throttle_override
                pitch_target, roll_target = 0.0, 0.0
            elif state == ARMED:
                throttle_target = pending_throttle_target
                pitch_target = pending_pitch_target
                roll_target = pending_roll_target
            else:  # DISARMED
                throttle_target, pitch_target, roll_target = 0.0, 0.0, 0.0

            f_throttle, f_pitch, f_roll = filters.update(throttle_target, pitch_target, roll_target)

            i2c_ok = True
            throttle_code = pitch_code = roll_code = None
            if calibration.is_complete():
                try:
                    throttle_code = calibration.throttle_code(f_throttle)
                    pitch_code = calibration.pitch_code(f_pitch)
                    roll_code = calibration.roll_code(f_roll)
                    throttle_dac.set_value(throttle_code)
                    pitch_dac.set_value(pitch_code)
                    roll_dac.set_value(roll_code)
                    watchdog.record_i2c_success()
                except (IOError, ValueError) as e:
                    i2c_ok = False
                    if watchdog.record_i2c_failure():
                        if args.verbose:
                            print(f"[I2C FAIL] entering safe state: {e}")
            elif args.verbose and int(now * 2) % 40 == 0:
                print("[WAIT] calibration incomplete, not driving DACs yet")

            if now - last_status_send >= 0.3:  # ~3Hz, within spec's 2-5Hz
                status = {
                    "version": 1,
                    "sequence_received": last_sequence,
                    "state": state,
                    "packet_age_ms": (now - watchdog.last_valid_time) * 1000
                        if watchdog.last_valid_time else None,
                    "throttle_code": throttle_code,
                    "pitch_code": pitch_code,
                    "roll_code": roll_code,
                    "i2c_ok": i2c_ok,
                    "failsafe": state == FAILSAFE,
                }
                receiver.send_status(status)
                last_status_send = now

            log_writer.writerow([
                time.time(), state, last_sequence,
                f"{(now - watchdog.last_valid_time) * 1000:.0f}" if watchdog.last_valid_time else "",
                f"{throttle_target:.3f}", f"{pitch_target:.3f}", f"{roll_target:.3f}",
                throttle_code, pitch_code, roll_code, i2c_ok,
            ])

            time.sleep(1.0 / 20.0)

    except KeyboardInterrupt:
        pass
    finally:
        throttle_dac.close()
        pitch_dac.close()
        roll_dac.close()
        receiver.close()
        log_f.close()


if __name__ == "__main__":
    main()
