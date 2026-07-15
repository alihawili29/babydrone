# Hand-Gesture Drone Flight (Wi-Fi / Raspberry Pi version)

CSIS-418 | Team Ginyard International Co.

**This replaces the earlier Pico + USB serial + MCP4728 design entirely.**
Everything in your old `babydrone` repo's `pico/` folder no longer applies —
this is Wi-Fi (UDP) instead of USB serial, a Raspberry Pi instead of a Pico,
and three separate MCP4725 DACs instead of one MCP4728.

## Architecture

```
MacBook (camera, MediaPipe, gesture logic)
        |  Wi-Fi UDP, ~20Hz
        v
Raspberry Pi (watchdog, smoothing, calibration mapping)
        |
        v
3x MCP4725 DACs -> H36 remote's throttle, pitch, roll joystick pads
```

Two independent programs — `mac/` and `raspberry_pi/` — talking over UDP.
See `mac/main.py` and `raspberry_pi/main.py` as the entry points.

## Setup — Mac side

```
cd mac
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Download the model file into `models/hand_landmarker.task` (shared with
the Pi folder structure, one level up):
```
https://raw.githubusercontent.com/pattssun/iDrone/main/models/hand_landmarker.task
```

Run camera/gesture testing with no network required:
```
python main.py --dry-run --show-landmarks
```
Controls: `a` = arm, `d` = disarm, `space` = emergency stop, `q` = quit.

## Setup — Raspberry Pi side

```
cd raspberry_pi
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Test the full networking/failsafe/calibration pipeline **without any DAC
hardware connected**:
```
python main.py --mock-dac --verbose
```
This prints what *would* be sent to each DAC instead of touching I2C —
useful for verifying the watchdog, packet validation, and calibration
mapping logic before any soldering happens.

## Before real flight

Both of these must happen before `pitch`/`roll`/`throttle` commands
actually reach the DACs — the code intentionally refuses to drive
uncalibrated hardware:

1. **Fill in `raspberry_pi/calibration.json`** — the `null` values need
   real multimeter readings for each axis's min/centre/max voltage codes.
2. **Confirm the second I2C bus number** in `raspberry_pi/config.json`
   (`dac.roll.bus` is currently a placeholder, `3` — this must be
   verified against your actual Pi's enabled I2C interfaces).

## Running the tests

```
pip install pytest --break-system-packages   # or inside a venv, no flag needed
python3 -m pytest tests/ -v
```

All 42 tests run without a camera, network, or real I2C hardware —
they test the pure logic (gesture classification, calibration math,
packet validation, mock DAC) in isolation.

## What's different from the reference repo (pattssun/iDrone)

| | Reference repo | This project |
|---|---|---|
| Transport | USB serial | Wi-Fi UDP |
| Microcontroller | Raspberry Pi Pico W | Raspberry Pi 4 |
| DAC | 1x MCP4728 (4 channels) | 3x MCP4725 (1 channel each) |
| Axes controlled | Throttle only | Throttle, pitch, roll |
| Hands used | 1 (right) | 2 (right=throttle, left=pitch/roll) |

Hand-angle math, EMA smoothing concept, and the watchdog concept are
reused from the reference repo; the transport/hardware layer is new.
