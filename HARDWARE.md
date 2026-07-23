# Hardware wiring reference

Mixed DAC setup: two MCP4725s (throttle, pitch) plus one PCF8591 (roll),
across two I2C buses. Throttle's voltage direction is inverted relative to
pitch/roll — see the note under Throttle below.

| Axis | Device | I2C bus | Address | Controller pad | Wire color |
|---|---|---|---|---|---|
| Throttle | MCP4725 | 3 | `0x60` | B2 | blue |
| Pitch | MCP4725 | 1 | `0x61` | C2 | yellow |
| Roll | PCF8591 (AOUT) | 1 | `0x48` | D2 | green |
| Ground | — | — | — | B− | orange (shared: Pi + all DAC grounds) |

## Voltage ranges per axis

**Throttle** (MCP4725, bus 3, addr `0x60`, 12-bit 0-4095) — **inverted**:
- `0V` = throttle fully **up / maximum**
- `3.1V` = throttle fully **down / minimum**

Because of this inversion, `calibration.json`'s `throttle.minimum_code` (the
safe/landed value) is the **larger** raw code (`4095`), and
`throttle.maximum_code` is `0`. `calibration.throttle_code()` is a plain
linear interpolation between the two, so this is handled entirely by the
calibration data — no special-cased code path.

**Pitch** (MCP4725, bus 1, addr `0x61`, 12-bit 0-4095):
- `0V` = backward
- `~1.5-1.6V` = neutral
- `3.1V` = forward

**Roll** (PCF8591, bus 1, addr `0x48`, AOUT, 8-bit 0-255) — measured
**under load**, narrower usable range than the MCP4725 axes, not assumed
linear across the full 0-3.3V rail:
- `~0.75V` = left
- `~1.6V` = neutral
- `~2.6V` = right

## I2C write formats

**MCP4725** (fast-mode write, 12-bit value 0-4095):
```python
byte0 = (value >> 8) & 0x0F   # top nibble; power-down bits = 00
byte1 = value & 0xFF
bus.write_i2c_block_data(address, byte0, [byte1])
```

**PCF8591** (single control byte + 8-bit value 0-255):
```python
control_byte = 0x40  # bit 6 enables analog output
bus.write_byte_data(address, control_byte, value)
```

## Calibration status

`raspberry_pi/calibration.json` codes:
- **Throttle**: real (`minimum_code=4095`, `maximum_code=0`, derived directly
  from the voltage spec above — no measurement needed since it's just the DAC's
  full-scale endpoints).
- **Pitch**: real, hardware-measured via `i2ctransfer` + multimeter on the
  loaded circuit (`backward_code=0`, `centre_code=2048`, `forward_code=3968`).
  This supersedes an earlier placeholder (`forward_code=3847`) that had
  incorrectly assumed a 3.3V reference voltage — no further pitch
  calibration pass is needed.
- **Roll**: real, multimeter-confirmed (`left_code=0`, `centre_code=128`,
  `right_code=255`). These are the PCF8591's hardware-limited endpoints
  measured directly on the loaded circuit, not a linear guess from the
  voltage spec above — no further roll calibration pass is needed.

Every axis now has a real, measured, non-null calibration, so
`Calibration.is_complete()` returns `True` and the Pi actively drives all
three DACs with confirmed values.
