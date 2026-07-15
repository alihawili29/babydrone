"""
Pico W firmware (MicroPython) — Hand-Gesture Drone Flight
CSIS-418 
Hardware: 4x MCP4725 single-channel DACs on one I2C bus (NOT an MCP4728).
Each physical chip is addressed separately — replace the placeholder
addresses below with what i2c_scan.py actually reports for your boards.
Reads "throttle,leftright,forwardback,yaw\n" over USB serial and writes
each value to its own MCP4725.
500ms watchdog: if no fresh packet arrives in time, throttle drops to 0
(lands the drone) and the other axes go neutral.
Wiring:
    Pico GP4 -> SDA on all 4 boards
    Pico GP5 -> SCL on all 4 boards
    Pico 3V3 -> VIN on all 4 boards
    Pico GND -> GND on all 4 boards (shared with remote ground)
"""
from machine import Pin, I2C
import sys
import select
import time
addr_throttle = 0x60
addr_leftright = 0x61
addr_forwardback = 0x62
addr_yaw = 0x63
NEUTRAL = 2048
WATCHDOG_MS = 500
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000)
def write_channel(address: int, value: int):
"""address: I2C address of the target MCP4725. value: 0-4095."""
    value = max(0, min(4095, value)) #top nibble, power-down bits = 00
    byte0 = (value>>8) & 0x0F
    byte1 = value & 0xFF
    i2c.writeto(address, bytes([byte0,byte1]))

def write_all(throttle, leftright, fwdback, yaw=NEUTRAL):
    write_channel(addr_throttle, throttle)
    write_channel(addr_leftright, leftright)
    write_channel(addr_forwardback, fwdback)
    write_channel(addr_yaw, yaw)
def main():
    write_all(0, NEUTRAL, NEUTRAL, NEUTRAL)
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
            write_all(0, NEUTRAL, NEUTRAL, NEUTRAL)
        time.sleep_ms(5)
if __name__ == "__main__":
    main()
