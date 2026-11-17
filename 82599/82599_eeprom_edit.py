#!/usr/bin/env python3
"""Edit MAC addresses and LED defaults in an Intel 82599 EEPROM image.

The input is a raw EEPROM binary image beginning at EEPROM word 0. Each
16-bit word is stored little-endian, as in a conventional EEPROM dump.
The source file is never modified; by default a new *_modified.bin file is
created.

Examples:
    python 82599_eeprom_edit.py eeprom.bin \
        --set port0.mac=00:11:22:33:44:55 \
        --set port0.led0.mode=link-activity \
        --set port0.led0.polarity=active-low \
        --set port0.led0.blink=off \
      --set port0.blink-rate=200ms \\
        -o eeprom_new.bin

    python 82599_eeprom_edit.py eeprom.bin \
        --set port1.mac=00:11:22:33:44:66 \
        --set port1.led1.mode=link-10g \
        --set sfp.allow-any=on

Run with --help for supported keys, values, and definitions.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# EEPROM word addresses containing pointers to the per-port LAN Core modules.
PORT_POINTER_WORDS = {0: 0x09, 1: 0x0A}

# The LAN Core section's first word is its length. Following data words:
#   +1..+3: MAC address (two octets per little-endian 16-bit word)
#   +4..+5: LED0..LED3 configuration bytes
MIN_LAN_CORE_DATA_WORDS = 5
MAC_WORD_OFFSETS = (1, 2, 3)
LED_WORD_OFFSET = 4

# LEDCTL MODE[3:0] encodings used by the 82599.
LED_MODES: dict[str, tuple[int, str]] = {
    "link-up": (0x0, "Link established at any speed"),
    "link-10g": (0x1, "10 Gb/s link"),
    "activity": (0x2, "MAC transmit/receive activity (BLINK must be on)"),
    "filtered-activity": (0x3, "Filtered transmit/receive activity (BLINK must be on)"),
    "link-activity": (0x4, "Steady when linked and idle; blinks on activity (BLINK must be off)"),
    "link-1g": (0x5, "1 Gb/s link"),
    "link-100m": (0x6, "100 Mb/s link"),
    "force-on": (0xE, "Force LED on"),
    "force-off": (0xF, "Force LED off"),
}

# Friendly aliases; the canonical values above are shown by --help.
MODE_ALIASES = {
    "link": "link-up",
    "any-link": "link-up",
    "mac-activity": "activity",
    "filter-activity": "filtered-activity",
    "link-100": "link-100m",
    "on": "force-on",
    "off": "force-off",
}

EEPROM_CHECKSUM_WORD = 0x3F
EEPROM_CHECKSUM_SUM = 0xBABA
EEPROM_POINTER_START = 0x03
EEPROM_POINTER_END_EXCLUSIVE = 0x0F  # 0x03..0x0E; 0x0F is the FW pointer.

# 82599 SFP vendor-policy setting. This is global (not per-port).
DEVICE_CAPS_WORD = 0x2C
DEVICE_CAPS_ALLOW_ANY_SFP = 0x0001


class EditError(Exception):
    """A user-correctable EEPROM image or command-line editing error."""


def read_u16(data: bytes | bytearray, word_address: int) -> int:
    """Read one little-endian 16-bit EEPROM word."""
    if word_address < 0:
        raise EditError(f"negative EEPROM word address: {word_address}")
    offset = word_address * 2
    if offset + 2 > len(data):
        raise EditError(
            f"EEPROM word 0x{word_address:04X} is outside the image "
            f"({len(data)} bytes)"
        )
    return data[offset] | (data[offset + 1] << 8)


def write_u16(data: bytearray, word_address: int, value: int) -> None:
    """Write one little-endian 16-bit EEPROM word."""
    if not 0 <= value <= 0xFFFF:
        raise EditError(f"16-bit value out of range: {value}")
    offset = word_address * 2
    if word_address < 0 or offset + 2 > len(data):
        raise EditError(f"cannot write EEPROM word 0x{word_address:04X}: out of range")
    data[offset] = value & 0xFF
    data[offset + 1] = (value >> 8) & 0xFF


def get_lan_core_pointer(data: bytes | bytearray, port: int) -> tuple[int, int]:
    """Return (module pointer, section length), validating required fields."""
    pointer_word = PORT_POINTER_WORDS[port]
    pointer = read_u16(data, pointer_word)
    if pointer in (0x0000, 0xFFFF):
        raise EditError(
            f"port{port}: LAN Core module pointer at EEPROM word "
            f"0x{pointer_word:02X} is null/invalid (0x{pointer:04X})"
        )

    length = read_u16(data, pointer)
    if length in (0x0000, 0xFFFF):
        raise EditError(
            f"port{port}: invalid LAN Core section length 0x{length:04X} "
            f"at word 0x{pointer:04X}"
        )
    if length < MIN_LAN_CORE_DATA_WORDS:
        raise EditError(
            f"port{port}: LAN Core section has {length} data words; "
            f"at least {MIN_LAN_CORE_DATA_WORDS} are needed for MAC and LEDs"
        )
    end_word = pointer + length
    if end_word >= len(data) // 2:
        raise EditError(
            f"port{port}: LAN Core section extends beyond the image "
            f"(pointer=0x{pointer:04X}, length={length})"
        )
    return pointer, length


def parse_mac(value: str) -> bytes:
    """Parse MAC text in colon, hyphen, dotted, or compact notation."""
    compact = re.sub(r"[:.\-]", "", value.strip())
    if not re.fullmatch(r"[0-9a-fA-F]{12}", compact):
        raise EditError(
            f"invalid MAC address {value!r}; use 00:11:22:33:44:55 format"
        )
    mac = bytes.fromhex(compact)
    if mac == b"\x00" * 6:
        raise EditError("all-zero MAC address is not a valid adapter address")
    if mac == b"\xFF" * 6:
        raise EditError("all-FF MAC address is not a valid adapter address")
    if mac[0] & 0x01:
        raise EditError("multicast MAC address is not valid for a NIC station address")
    return mac


def write_mac(data: bytearray, module_pointer: int, mac: bytes) -> None:
    for index, word_offset in enumerate(MAC_WORD_OFFSETS):
        word = mac[index * 2] | (mac[index * 2 + 1] << 8)
        write_u16(data, module_pointer + word_offset, word)


def read_led_config(data: bytes | bytearray, module_pointer: int, led: int) -> int:
    """Read one 8-bit LED configuration byte (0..3)."""
    word = read_u16(data, module_pointer + LED_WORD_OFFSET + led // 2)
    return (word >> (8 * (led % 2))) & 0xFF


def write_led_config(
    data: bytearray, module_pointer: int, led: int, config: int
) -> None:
    """Write one LED byte while preserving the other LED in the same word."""
    word_address = module_pointer + LED_WORD_OFFSET + led // 2
    shift = 8 * (led % 2)
    current_word = read_u16(data, word_address)
    new_word = (current_word & ~(0xFF << shift)) | ((config & 0xFF) << shift)
    write_u16(data, word_address, new_word)


def normalize_value(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def parse_setting(setting: str) -> tuple[str, str]:
    if "=" not in setting:
        raise EditError(f"invalid --set value {setting!r}; expected KEY=VALUE")
    key, value = setting.split("=", 1)
    key = key.strip().lower()
    value = value.strip()
    if not key or not value:
        raise EditError(f"invalid --set value {setting!r}; KEY and VALUE cannot be empty")
    return key, value


def apply_setting(
    data: bytearray,
    setting: str,
    module_pointers: dict[int, int],
) -> str:
    """Apply one KEY=VALUE setting and return a concise change description."""
    key, raw_value = parse_setting(setting)

    # Global SFP vendor restriction. Only bit 0 is changed; all other
    # Device Capabilities bits are preserved.
    if key in ("sfp.allow-any", "device.allow-any-sfp"):
        value = normalize_value(raw_value)
        old_caps = read_u16(data, DEVICE_CAPS_WORD)
        if value in ("on", "enabled", "enable", "yes", "true", "allow"):
            new_caps = old_caps | DEVICE_CAPS_ALLOW_ANY_SFP
            state = "enabled"
        elif value in ("off", "disabled", "disable", "no", "false", "deny"):
            new_caps = old_caps & ~DEVICE_CAPS_ALLOW_ANY_SFP
            state = "disabled"
        else:
            raise EditError(
                f"invalid SFP policy value {raw_value!r}; use on or off"
            )
        write_u16(data, DEVICE_CAPS_WORD, new_caps)
        return (
            f"sfp.allow-any: Device Capabilities word 0x{DEVICE_CAPS_WORD:02X} "
            f"0x{old_caps:04X} -> 0x{new_caps:04X} ({state}, bit 0)"
        )

    mac_match = re.fullmatch(r"port([01])\.mac", key)
    led_match = re.fullmatch(r"port([01])\.led([0-3])\.(mode|polarity|blink)", key)
    rate_match = re.fullmatch(r"port([01])\.blink-rate", key)

    if mac_match:
        port = int(mac_match.group(1))
        mac = parse_mac(raw_value)
        pointer = module_pointers[port]
        old_mac_bytes = bytearray()
        for offset in MAC_WORD_OFFSETS:
            word = read_u16(data, pointer + offset)
            old_mac_bytes.extend((word & 0xFF, (word >> 8) & 0xFF))
        old_mac = ":".join(f"{b:02X}" for b in old_mac_bytes)
        write_mac(data, pointer, mac)
        new_mac = ":".join(f"{b:02X}" for b in mac)
        return f"port{port}.mac: {old_mac} -> {new_mac}"

    if led_match:
        port = int(led_match.group(1))
        led = int(led_match.group(2))
        field = led_match.group(3)
        pointer = module_pointers[port]
        config = read_led_config(data, pointer, led)
        old_config = config
        value = normalize_value(raw_value)

        if field == "mode":
            value = MODE_ALIASES.get(value, value)
            if value not in LED_MODES:
                choices = ", ".join(LED_MODES)
                raise EditError(
                    f"invalid LED mode {raw_value!r}; available values: {choices}"
                )
            mode_value, _ = LED_MODES[value]
            config = (config & ~0x0F) | mode_value
            detail = f"mode={value}"
        elif field == "polarity":
            if value in ("active-low", "normal"):
                config &= ~0x40  # IVRT=0: non-inverted (active-low default).
                detail = "polarity=active-low"
            elif value in ("active-high", "inverted"):
                config |= 0x40  # IVRT=1: invert the LED output polarity.
                detail = "polarity=active-high"
            else:
                raise EditError(
                    f"invalid LED polarity {raw_value!r}; use active-low or active-high"
                )
        else:  # blink
            if value in ("on", "enabled", "enable", "yes", "true"):
                config |= 0x80
                detail = "blink=on"
            elif value in ("off", "disabled", "disable", "no", "false"):
                config &= ~0x80
                detail = "blink=off"
            else:
                raise EditError(f"invalid blink value {raw_value!r}; use on or off")

        write_led_config(data, pointer, led, config)
        return (
            f"port{port}.led{led}.{field}: 0x{old_config:02X} -> "
            f"0x{config:02X} ({detail})"
        )

    if rate_match:
        port = int(rate_match.group(1))
        pointer = module_pointers[port]
        config = read_led_config(data, pointer, 0)  # Global rate is stored in LED0.
        old_config = config
        value = normalize_value(raw_value)
        if value in ("200ms", "slow"):
            config &= ~0x20  # 0 = 200 ms on / 200 ms off.
            detail = "200 ms on / 200 ms off"
        elif value in ("83ms", "fast"):
            config |= 0x20  # 1 = 83 ms on / 83 ms off.
            detail = "83 ms on / 83 ms off"
        else:
            raise EditError(f"invalid blink rate {raw_value!r}; use 200ms or 83ms")
        write_led_config(data, pointer, 0, config)
        return (
            f"port{port}.blink-rate: LED0 0x{old_config:02X} -> "
            f"0x{config:02X} ({detail})"
        )

    raise EditError(
        f"unknown setting key {key!r}; see --help for supported KEY names"
    )


def calculate_checksum(data: bytes | bytearray) -> int:
    """Calculate the 82599 software EEPROM checksum word (0x3F).

    Sum words 0x00..0x3E, plus the data words referenced by pointers 0x03..0x0E.
    Each referenced section's length word is excluded; the next `length` words
    are included. The firmware pointer at 0x0F is intentionally excluded.
    """
    word_count = len(data) // 2
    if word_count <= EEPROM_CHECKSUM_WORD:
        raise EditError(
            f"image is too short for the checksum word at 0x{EEPROM_CHECKSUM_WORD:02X}"
        )

    total = sum(read_u16(data, address) for address in range(EEPROM_CHECKSUM_WORD))

    for pointer_word in range(EEPROM_POINTER_START, EEPROM_POINTER_END_EXCLUSIVE):
        pointer = read_u16(data, pointer_word)
        if pointer in (0x0000, 0xFFFF):
            continue
        if pointer >= word_count:
            raise EditError(
                f"checksum pointer at word 0x{pointer_word:02X} points outside image "
                f"(0x{pointer:04X})"
            )
        length = read_u16(data, pointer)
        if length in (0x0000, 0xFFFF):
            continue
        if pointer + length >= word_count:
            raise EditError(
                f"checksum section at pointer word 0x{pointer_word:02X} is truncated "
                f"(pointer=0x{pointer:04X}, length=0x{length:04X})"
            )
        for address in range(pointer + 1, pointer + length + 1):
            total += read_u16(data, address)

    return (EEPROM_CHECKSUM_SUM - total) & 0xFFFF


def normalize_required_led_blink_bits(
    data: bytearray,
    module_pointers: dict[int, int],
    settings: list[str],
) -> list[str]:
    """Apply mandatory BLINK states for 82599 LED modes and validate overrides.

    Per the 82599 datasheet, MAC_ACTIVITY and FILTER_ACTIVITY require BLINK=1,
    while LINK/ACTIVITY requires BLINK=0. A contradictory explicit --set blink=...
    is treated as an error rather than silently overridden.
    """
    explicit_blink: dict[tuple[int, int], bool] = {}
    touched_leds: set[tuple[int, int]] = set()
    for item in settings:
        key, raw_value = parse_setting(item)
        match = re.fullmatch(r"port([01])\.led([0-3])\.(mode|blink)", key)
        if not match:
            continue
        led_key = (int(match.group(1)), int(match.group(2)))
        touched_leds.add(led_key)
        if match.group(3) != "blink":
            continue
        value = normalize_value(raw_value)
        if value in ("on", "enabled", "enable", "yes", "true"):
            explicit_blink[led_key] = True
        elif value in ("off", "disabled", "disable", "no", "false"):
            explicit_blink[led_key] = False

    automatic_changes: list[str] = []
    for port, led in sorted(touched_leds):
        pointer = module_pointers[port]
        config = read_led_config(data, pointer, led)
        mode = config & 0x0F
        current_blink = bool(config & 0x80)
        required_blink: bool | None = None
        if mode in (0x2, 0x3):
            required_blink = True
        elif mode == 0x4:
            required_blink = False

        if required_blink is None:
            continue

        explicit = explicit_blink.get((port, led))
        if explicit is not None and explicit != required_blink:
            required_text = "on" if required_blink else "off"
            supplied_text = "on" if explicit else "off"
            raise EditError(
                f"port{port}.led{led}: mode {LED_MODES_BY_CODE[mode]} requires "
                f"blink={required_text}, but blink={supplied_text} was requested"
            )

        if current_blink != required_blink:
            if required_blink:
                config |= 0x80
            else:
                config &= ~0x80
            write_led_config(data, pointer, led, config)
            required_text = "on" if required_blink else "off"
            automatic_changes.append(
                f"port{port}.led{led}.blink automatically set to {required_text} "
                f"for mode {LED_MODES_BY_CODE[mode]}"
            )
    return automatic_changes


LED_MODES_BY_CODE = {code: name for name, (code, _description) in LED_MODES.items()}


def format_checksum_status(data: bytes | bytearray) -> str:
    try:
        expected = calculate_checksum(data)
    except EditError as exc:
        return f"not available ({exc})"
    stored = read_u16(data, EEPROM_CHECKSUM_WORD)
    status = "OK" if stored == expected else "MISMATCH"
    return f"{status} (stored=0x{stored:04X}, calculated=0x{expected:04X})"


def build_parser() -> argparse.ArgumentParser:
    mode_help = "; ".join(
        f"{name}={description} (0x{code:X})"
        for name, (code, description) in LED_MODES.items()
    )
    epilog = f"""
SUPPORTED KEY=VALUE SETTINGS
  port0.mac=00:11:22:33:44:55
  port1.mac=00:11:22:33:44:66
      Set the station MAC address for the selected port. Unicast MAC only.

  portN.ledM.mode=VALUE       N=0|1, M=0|1|2|3
      Available modes: {mode_help}
      Aliases: link, mac-activity, filter-activity, link-100, on, off.

  portN.ledM.polarity=active-low|active-high
      active-low: normal/non-inverted output (IVRT=0).
      active-high: inverted output polarity (IVRT=1).

  portN.ledM.blink=on|off
      Enable or disable blinking for that LED. MAC_ACTIVITY/FILTER_ACTIVITY
      require blink=on; LINK/ACTIVITY requires blink=off. The required bit is
      set automatically when needed; a contradictory explicit value is rejected.

  portN.blink-rate=200ms|83ms
      Global blink timing for the port: 200ms (slow) or 83ms (fast).

  sfp.allow-any=on|off
      Global 82599 Device Capabilities setting at EEPROM word 0x2C, bit 0
      (ALLOW_ANY_SFP). When on, the Linux ixgbe driver bypasses its
      normal vendor-OUI rejection for applicable optical SFP modules.
      This does not guarantee electrical, optical, firmware, or driver compatibility.
      Only bit 0 is changed; all other Device Capabilities bits are preserved.
      Alias: device.allow-any-sfp.

EXAMPLES
  # Set port 0 MAC and LED0/LED1 behavior
  python 82599_eeprom_edit.py eeprom.bin -o new.bin \\
      --set port0.mac=00:11:22:33:44:55 \\
      --set port0.led0.mode=link-activity \\
      --set port0.led0.blink=off \\
      --set port0.led1.mode=link-10g \\
      --set port0.blink-rate=200ms \\
      --set sfp.allow-any=on

  # Change only port 1's MAC
  python 82599_eeprom_edit.py eeprom.bin --set port1.mac=00:11:22:33:44:66

NOTES
  * The input must be a raw EEPROM dump starting at word address 0, with
    16-bit words stored little-endian.
  * The original input file is never modified. If -o is omitted, the output
    name is INPUT_modified.bin.
  * The software checksum word at 0x3F is recalculated automatically.
  * --force permits overwriting an existing output file, but never the input.
"""

    parser = argparse.ArgumentParser(
        description=(
            "Modify MAC addresses and LED defaults in an Intel 82599 EEPROM image. "
            "Use --set KEY=VALUE (repeatable) to select settings."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("binfile", type=Path, help="input raw EEPROM binary image")
    parser.add_argument(
        "-o", "--output", type=Path,
        help="output binary path (default: INPUT_modified.bin)",
    )
    parser.add_argument(
        "--set", dest="settings", action="append", metavar="KEY=VALUE", required=True,
        help="setting to change; can be specified multiple times (see examples below)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite an existing output file (input file is never overwritten)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path: Path = args.binfile
    output_path: Path = args.output or input_path.with_name(
        f"{input_path.stem}_modified{input_path.suffix or '.bin'}"
    )

    try:
        if not input_path.is_file():
            raise EditError(f"input file does not exist or is not a regular file: {input_path}")
        if input_path.resolve() == output_path.resolve():
            raise EditError("output path must differ from input path; the original is protected")
        if output_path.exists() and not args.force:
            raise EditError(
                f"output file already exists: {output_path} (use --force to overwrite it)"
            )

        original = input_path.read_bytes()
        if len(original) % 2:
            raise EditError(
                f"input size is {len(original)} bytes; EEPROM word data must have an even size"
            )
        if len(original) < 0x40 * 2:
            raise EditError(
                f"input is only {len(original)} bytes; at least 128 bytes are required "
                "for the 82599 checksum word"
            )

        # Reject duplicate assignments instead of silently choosing one.
        parsed_settings = [parse_setting(s) for s in args.settings]
        seen: set[str] = set()
        for key, _ in parsed_settings:
            if key in seen:
                raise EditError(f"setting {key!r} was specified more than once")
            seen.add(key)

        # Only resolve LAN Core modules for ports actually referenced by settings.
        ports_needed: set[int] = set()
        for key, _ in parsed_settings:
            if key in ("sfp.allow-any", "device.allow-any-sfp"):
                continue
            match = re.match(r"port([01])\.", key)
            if not match:
                raise EditError(f"invalid setting key {key!r}; see --help")
            ports_needed.add(int(match.group(1)))

        module_pointers: dict[int, int] = {}
        for port in sorted(ports_needed):
            pointer, length = get_lan_core_pointer(original, port)
            module_pointers[port] = pointer
            print(
                f"port{port}: LAN Core module at word 0x{pointer:04X}, "
                f"{length} data words"
            )

        before_checksum = format_checksum_status(original)
        modified = bytearray(original)
        print(f"Input checksum : {before_checksum}")
        print("\nChanges:")
        for setting in args.settings:
            print(f"  {apply_setting(modified, setting, module_pointers)}")

        automatic_led_changes = normalize_required_led_blink_bits(
            modified, module_pointers, args.settings
        )
        for change in automatic_led_changes:
            print(f"  {change}")

        new_checksum = calculate_checksum(modified)
        old_checksum_word = read_u16(modified, EEPROM_CHECKSUM_WORD)
        write_u16(modified, EEPROM_CHECKSUM_WORD, new_checksum)
        after_checksum = format_checksum_status(modified)
        print(
            f"\nChecksum word 0x{EEPROM_CHECKSUM_WORD:02X}: "
            f"0x{old_checksum_word:04X} -> 0x{new_checksum:04X}"
        )
        print(f"Output checksum: {after_checksum}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Use exclusive creation unless --force was explicitly requested.
        if args.force:
            output_path.write_bytes(modified)
        else:
            with output_path.open("xb") as file:
                file.write(modified)
        print(f"\nSaved: {output_path} ({len(modified)} bytes)")
        print("The original input file was not modified.")
        return 0

    except (OSError, EditError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
