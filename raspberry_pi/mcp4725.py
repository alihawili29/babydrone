"""
MCP4725 driver — spec section 14.

Single-channel, 12-bit, I2C voltage-output DAC. Fast-mode write only
(does not touch EEPROM) so control updates don't wear out the chip and
don't change its power-on default.

Fast-mode write command: 2 bytes, no register/channel byte —
    byte0 = (value >> 8) & 0x0F   (top nibble; power-down bits = 00)
    byte1 = value & 0xFF
"""

try:
    import smbus2
    _HAVE_SMBUS = True
except ImportError:
    _HAVE_SMBUS = False


class MCP4725:
    def __init__(self, bus_number: int, address: int):
        if not _HAVE_SMBUS:
            raise RuntimeError(
                "smbus2 is not installed. Install it with 'pip install smbus2', "
                "or run with --mock-dac to test without real I2C hardware."
            )
        self.bus_number = bus_number
        self.address = address
        self.bus = smbus2.SMBus(bus_number)

    def set_value(self, value: int) -> None:
        value = max(0, min(4095, int(value)))
        byte0 = (value >> 8) & 0x0F
        byte1 = value & 0xFF
        try:
            self.bus.write_i2c_block_data(self.address, byte0, [byte1])
        except OSError as e:
            raise IOError(
                f"I2C write failed on bus {self.bus_number} addr 0x{self.address:02X}: {e}"
            ) from e

    def set_normalized(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self.set_value(round(value * 4095))

    def close(self):
        if _HAVE_SMBUS:
            self.bus.close()


class MockMCP4725:
    """Prints instead of touching I2C — spec section 19, --mock-dac."""

    def __init__(self, bus_number: int, address: int, label: str = ""):
        self.bus_number = bus_number
        self.address = address
        self.label = label
        self.last_value = None

    def set_value(self, value: int) -> None:
        value = max(0, min(4095, int(value)))
        self.last_value = value
        print(f"[MOCK DAC] {self.label} bus={self.bus_number} addr=0x{self.address:02X} -> {value}")

    def set_normalized(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self.set_value(round(value * 4095))

    def close(self):
        pass


class PCF8591:
    """
    PCF8591 driver — 8-bit DAC/ADC combo chip, we only use the AOUT side.

    Unlike the MCP4725, the PCF8591 has no dedicated DAC-write command: you
    write a control byte (bit 6 = analog output enable) followed by the
    8-bit value to the chip's single register.
    """

    CONTROL_BYTE = 0x40  # bit 6 enables analog output

    def __init__(self, bus_number: int, address: int):
        if not _HAVE_SMBUS:
            raise RuntimeError(
                "smbus2 is not installed. Install it with 'pip install smbus2', "
                "or run with --mock-dac to test without real I2C hardware."
            )
        self.bus_number = bus_number
        self.address = address
        self.bus = smbus2.SMBus(bus_number)

    def set_value(self, value: int) -> None:
        value = max(0, min(255, int(value)))
        try:
            self.bus.write_byte_data(self.address, self.CONTROL_BYTE, value)
        except OSError as e:
            raise IOError(
                f"I2C write failed on bus {self.bus_number} addr 0x{self.address:02X}: {e}"
            ) from e

    def set_normalized(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self.set_value(round(value * 255))

    def close(self):
        if _HAVE_SMBUS:
            self.bus.close()


class MockPCF8591:
    """Prints instead of touching I2C — spec section 19, --mock-dac."""

    def __init__(self, bus_number: int, address: int, label: str = ""):
        self.bus_number = bus_number
        self.address = address
        self.label = label
        self.last_value = None

    def set_value(self, value: int) -> None:
        value = max(0, min(255, int(value)))
        self.last_value = value
        print(f"[MOCK DAC] {self.label} bus={self.bus_number} addr=0x{self.address:02X} -> {value}")

    def set_normalized(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self.set_value(round(value * 255))

    def close(self):
        pass
