"""
Pico W firmware (MicroPython) — Hand-Gesture Drone Flight
CSIS-418 | Team Ginyard International Co.

Extends pattssun/iDrone's single-channel version. Reads
"throttle,leftright,forwardback,yaw\n" over USB serial and writes the first
three values to MCP4728 DAC channels A, B, C. Channel D is reserved for a
future yaw axis and is always written as neutral (2048).

500ms watchdog: if no fresh packet arrives in time, all channels snap to
2048 (neutral/hover) so the drone fails safe.

Wiring (same I2C bus as base repo):
    Pico GP4 -> DAC SDA
    Pico GP5 -> DAC SCL
    Pico 3V3 -> DAC VIN
    Pico GND -> DAC GND (and shared with remote ground)
DAC I2C address: 0x60

Hardware note: this build targets a JJRC H36 remote, not the HS210 used in
the base repo. Pad locations are NOT the same — verify with a multimeter
(continuity + voltage swing) before soldering, exactly as described in the
iDrone README's "Find the right pads" step.
    Channel A output -> throttle pad
    Channel B output -> roll (left/right) pad
    Channel C output -> pitch (forward/backward) pad
"""

from machine import Pin, I2C
import sys
import select
import time

I2C_SDA = 4
I2C_SCL = 5
DAC_ADDR = 0x60
NEUTRAL = 2048
WATCHDOG_MS = 500

i2c = I2C(0, sda=Pin(I2C_SDA), scl=Pin(I2C_SCL), freq=400_000)


def write_channel(channel: int, value: int):
    """channel: 0=A, 1=B, 2=C, 3=D. value: 0-4095."""
    value = max(0, min(4095, value))
    # MCP4728 fast-write style single-channel command
    high_byte = (channel << 5) | 0x00 | ((value >> 8) & 0x0F)
    low_byte = value & 0xFF
    i2c.writeto(DAC_ADDR, bytes([0x58 | channel, high_byte, low_byte]))


def write_all(throttle, leftright, fwdback, yaw=NEUTRAL):
    write_channel(0, throttle)
    write_channel(1, leftright)
    write_channel(2, fwdback)
    write_channel(3, yaw)


def main():
    write_all(NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL)
    last_packet_ms = time.ticks_ms()
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    buf = ""

    while True:
        now = time.ticks_ms()

        if poll.poll(0):
            chunk = sys.stdin.read(1)
            if chunk == "\n":
                try:
                    parts = [int(p) for p in buf.strip().split(",")]
                    if len(parts) == 4:
                        throttle, leftright, fwdback, yaw = parts
                        write_all(throttle, leftright, fwdback, yaw)
                        last_packet_ms = now
                except ValueError:
                    pass
                buf = ""
            else:
                buf += chunk

        if time.ticks_diff(now, last_packet_ms) > WATCHDOG_MS:
            write_all(NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL)

        time.sleep_ms(5)


if __name__ == "__main__":
    main()

