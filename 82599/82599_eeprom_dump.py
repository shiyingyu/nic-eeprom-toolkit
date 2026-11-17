#!/usr/bin/env python3
"""Decode common Intel 82599 EEPROM settings from a raw binary dump.

Usage:
    python 82599_eeprom_dump.py eeprom.bin
    python 82599_eeprom_dump.py eeprom.bin --port 0

The input is expected to be a raw EEPROM image starting at word address 0,
with 16-bit words stored little-endian (the usual format of an EEPROM dump).
This script is read-only: it never modifies the input file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


# EEPROM word addresses containing pointers to the LAN Core modules.
PORT_POINTER_WORDS = {0: 0x09, 1: 0x0A}

# 82599 SFP-related NVM fields.
# Word 0x2B points to the PHY initialization sequence index table.
# Word 0x2C is the Device Capabilities word; bit 0 allows any SFP vendor.
PHY_INIT_LIST_POINTER_WORD = 0x2B
DEVICE_CAPS_WORD = 0x2C
DEVICE_CAPS_ALLOW_ANY_SFP = 0x0001

SFP_TYPE_NAMES = {
    0x0000: "Passive DAC (generic)",
    0x0001: "10GBASE-SR (generic)",
    0x0002: "10GBASE-LR (generic)",
    0x0003: "Passive DAC, Port 0 (82599-specific)",
    0x0004: "Passive DAC, Port 1 (82599-specific)",
    0x0005: "10GBASE-SR/LR optics, Port 0 (82599-specific)",
    0x0006: "10GBASE-SR/LR optics, Port 1 (82599-specific)",
    0x0007: "Active-limiting DAC, Port 0 (82599-specific)",
    0x0008: "Active-limiting DAC, Port 1 (82599-specific)",
    0x0009: "1GBASE-T SFP, Port 0 (82599-specific)",
    0x000A: "1GBASE-T SFP, Port 1 (82599-specific)",
    0x000B: "1GBASE-SX SFP, Port 0 (82599-specific)",
    0x000C: "1GBASE-SX SFP, Port 1 (82599-specific)",
}

# 82599 LED mode values (LEDCTL.MODE[3:0]).
LED_MODES = {
    0x0: "LINK_UP       (link established at any speed)",
    0x1: "LINK_10G      (10 Gb/s link)",
    0x2: "MAC_ACTIVITY  (TX/RX activity)",
    0x3: "FILTER_ACTIVITY (filtered TX/RX activity)",
    0x4: "LINK/ACTIVITY (steady link, activity indication)",
    0x5: "LINK_1G       (1 Gb/s link)",
    0x6: "LINK_100      (100 Mb/s link)",
    0xE: "LED_ON        (forced on)",
    0xF: "LED_OFF       (forced off)",
}


def read_u16_le(data: bytes, word_address: int) -> int:
    """Read one 16-bit EEPROM word at an absolute word address."""
    byte_offset = word_address * 2
    if word_address < 0 or byte_offset + 2 > len(data):
        raise IndexError(
            f"word address 0x{word_address:04X} is outside the image "
            f"({len(data)} bytes)"
        )
    return data[byte_offset] | (data[byte_offset + 1] << 8)


def format_mac(words: list[int]) -> str:
    """Convert three EEPROM words to a MAC address, low byte first."""
    octets: list[int] = []
    for word in words:
        octets.extend((word & 0xFF, (word >> 8) & 0xFF))
    return ":".join(f"{octet:02X}" for octet in octets)


def describe_mac(mac: str) -> Optional[str]:
    raw = bytes.fromhex(mac.replace(":", ""))
    if raw == b"\x00" * 6:
        return "WARNING: all-zero MAC address"
    if raw == b"\xFF" * 6:
        return "WARNING: all-FF MAC address (unprogrammed/invalid)"
    if raw[0] & 0x01:
        return "WARNING: multicast MAC address (usually not expected as a NIC address)"
    return None


def decode_led(led_index: int, config: int) -> list[str]:
    """Decode one LED's 8-bit EEPROM control field."""
    mode = config & 0x0F
    inverted = bool(config & 0x40)
    blink = bool(config & 0x80)
    mode_text = LED_MODES.get(mode, f"Reserved/unknown mode 0x{mode:X}")

    lines = [
        f"  LED{led_index}: raw=0x{config:02X}",
        f"    Mode       : {mode_text}",
        f"    Polarity   : {'active high' if inverted else 'active low'}",
        f"    Blink flag : {'enabled' if blink else 'disabled'}",
    ]

    # Bit 5 is GLOBAL_BLINK_MODE in the LEDCTL register. It appears in the
    # LED0 byte (bits 5:0) and controls the blink rate used by the LEDs.
    if led_index == 0:
        blink_period = "83 ms on / 83 ms off" if (config & 0x20) else "200 ms on / 200 ms off"
        lines.append(f"    Global blink: {blink_period}")

    # Bits 5:4 are reserved in LED1..LED3's corresponding LEDCTL fields.
    reserved = config & (0x30 if led_index else 0x10)
    if reserved:
        lines.append(f"    Reserved bits set: 0x{reserved:02X}")

    return lines


def decode_port(data: bytes, port: int) -> list[str]:
    pointer_word = PORT_POINTER_WORDS[port]
    pointer = read_u16_le(data, pointer_word)
    lines = [f"\nPORT {port}", f"  Module pointer : EEPROM word 0x{pointer_word:02X} = 0x{pointer:04X}"]

    if pointer in (0x0000, 0xFFFF):
        lines.append("  Module         : absent (invalid/null pointer)")
        return lines

    try:
        length = read_u16_le(data, pointer)
    except IndexError as exc:
        lines.append(f"  Module         : cannot read section length ({exc})")
        return lines

    if length in (0x0000, 0xFFFF):
        lines.append(f"  Module         : invalid section length 0x{length:04X}")
        return lines

    # The length field counts the words AFTER the length word. The LAN Core
    # section needs at least offsets 1..5 for MAC and LED data.
    end_word = pointer + length
    if end_word * 2 + 1 >= len(data):
        lines.append(
            f"  Module         : truncated/out of range "
            f"(length={length} words, ends at word 0x{end_word:04X})"
        )
        return lines
    if length < 5:
        lines.append(f"  Module         : too short ({length} data words; need at least 5)")
        return lines

    lines.append(f"  Section length : {length} data words (section starts at word 0x{pointer:04X})")

    mac_words = [read_u16_le(data, pointer + offset) for offset in (1, 2, 3)]
    mac = format_mac(mac_words)
    lines.append(f"  MAC address    : {mac}")
    warning = describe_mac(mac)
    if warning:
        lines.append(f"                   {warning}")

    led_word_0 = read_u16_le(data, pointer + 4)
    led_word_1 = read_u16_le(data, pointer + 5)
    led_configs = [
        led_word_0 & 0xFF,
        (led_word_0 >> 8) & 0xFF,
        led_word_1 & 0xFF,
        (led_word_1 >> 8) & 0xFF,
    ]

    lines.append("  LED configuration:")
    for index, config in enumerate(led_configs):
        lines.extend(decode_led(index, config))

    if length >= 6:
        sdp = read_u16_le(data, pointer + 6)
        native = (sdp >> 15) & 0x1
        direction = (sdp >> 8) & 0x0F
        output_value = sdp & 0x0F
        lines.append(f"  SDP control     : 0x{sdp:04X}")
        lines.append(f"    SDP1 native   : {'native function' if native else 'general-purpose I/O'}")
        lines.append(f"    SDP[3:0] dir  : {direction:04b} (1=output, 0=input)")
        lines.append(f"    SDP[3:0] value: {output_value:04b}")

    return lines


def decode_sfp_support(data: bytes) -> list[str]:
    """Decode the 82599 SFP vendor-policy bit and PHY-init type index table.

    Word 0x2B contains a pointer whose target is a one-word preamble; the
    type/pointer pairs begin at pointer + 1 and end with type 0xFFFF.
    This table describes PHY initialization sequences by module class. It is
    not a vendor/OUI whitelist.
    """
    lines = ["\nSFP / PHY initialization configuration"]
    word_count = len(data) // 2
    if word_count <= DEVICE_CAPS_WORD:
        lines.append("  Device capabilities: unavailable (image too short)")
        return lines

    caps = read_u16_le(data, DEVICE_CAPS_WORD)
    allow_any = bool(caps & DEVICE_CAPS_ALLOW_ANY_SFP)
    lines.append(
        f"  Device capabilities : word 0x{DEVICE_CAPS_WORD:02X} = 0x{caps:04X}"
    )
    lines.append(
        f"  Allow any SFP vendor: {'enabled' if allow_any else 'disabled'} "
        "(ALLOW_ANY_SFP, bit 0)"
    )

    if word_count <= PHY_INIT_LIST_POINTER_WORD:
        lines.append("  PHY init list       : unavailable (image too short)")
        return lines

    list_pointer = read_u16_le(data, PHY_INIT_LIST_POINTER_WORD)
    lines.append(
        f"  PHY init list pointer: word 0x{PHY_INIT_LIST_POINTER_WORD:02X} "
        f"= 0x{list_pointer:04X}"
    )
    if list_pointer in (0x0000, 0xFFFF):
        lines.append("  PHY init type list   : absent (null/invalid pointer)")
        return lines
    if list_pointer + 1 >= word_count:
        lines.append("  PHY init type list   : pointer is outside the image")
        return lines

    preamble = read_u16_le(data, list_pointer)
    lines.append(
        f"  List preamble        : word 0x{list_pointer:04X} = 0x{preamble:04X}"
    )
    lines.append("  PHY init entries:")

    address = list_pointer + 1
    found_terminator = False
    entry_count = 0
    while address + 1 < word_count:
        type_id = read_u16_le(data, address)
        if type_id == 0xFFFF:
            found_terminator = True
            break
        data_pointer = read_u16_le(data, address + 1)
        description = SFP_TYPE_NAMES.get(type_id, "Unknown / vendor-defined type")
        pointer_status = ""
        if data_pointer in (0x0000, 0xFFFF) or data_pointer >= word_count:
            pointer_status = " [invalid data pointer]"
        else:
            crc_or_header = read_u16_le(data, data_pointer)
            pointer_status = f" [block word 0x{data_pointer:04X}, first=0x{crc_or_header:04X}]"
        lines.append(
            f"    ID 0x{type_id:04X}: {description}; "
            f"data pointer=0x{data_pointer:04X}{pointer_status}"
        )
        entry_count += 1
        address += 2
        # Protect against malformed images and nonsensical tables.
        if entry_count > 128:
            lines.append("    Error: more than 128 entries; stopping table scan")
            break

    if not found_terminator:
        lines.append("    Warning: 0xFFFF end marker not found before end of image")
    if entry_count == 0:
        lines.append("    (no entries)")
    lines.append(
        "  Note: this is a module-class-to-PHY-init-sequence table, "
        "not a list of approved manufacturers or exact SFP part numbers."
    )
    return lines


def calculate_checksum(data: bytes) -> tuple[Optional[int], Optional[str]]:
    """Calculate the 82599 software EEPROM checksum, if the dump is complete.

    The base checksum covers words 0x00..0x3E. Section data referenced by
    pointer words 0x03..0x0E is also included; each section's length word is
    excluded, while the following `length` data words are included.
    """
    word_count = len(data) // 2
    if word_count <= 0x3F:
        return None, "image is shorter than 0x40 EEPROM words"

    total = sum(read_u16_le(data, i) for i in range(0x3F))

    for pointer_word in range(0x03, 0x0F):
        pointer = read_u16_le(data, pointer_word)
        if pointer in (0x0000, 0xFFFF):
            continue

        try:
            length = read_u16_le(data, pointer)
        except IndexError:
            return None, f"pointer at word 0x{pointer_word:02X} points outside the image"

        if length in (0x0000, 0xFFFF):
            continue

        if pointer + length >= word_count:
            return None, (
                f"section referenced by word 0x{pointer_word:02X} is truncated "
                f"(pointer=0x{pointer:04X}, length=0x{length:04X})"
            )

        for word_address in range(pointer + 1, pointer + length + 1):
            total += read_u16_le(data, word_address)

    expected = (0xBABA - total) & 0xFFFF
    return expected, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode common Intel 82599 EEPROM settings (MAC, LEDs, SDP)."
    )
    parser.add_argument("binfile", type=Path, help="raw EEPROM binary image")
    parser.add_argument(
        "--port",
        choices=("0", "1", "all"),
        default="all",
        help="which LAN port to decode (default: all)",
    )
    args = parser.parse_args()

    try:
        data = args.binfile.read_bytes()
    except OSError as exc:
        print(f"Error: cannot read {args.binfile}: {exc}", file=sys.stderr)
        return 2

    if len(data) % 2:
        print(
            f"Error: file size is {len(data)} bytes; EEPROM word data must have an even size.",
            file=sys.stderr,
        )
        return 2
    if len(data) < (0x0B * 2):
        print(
            f"Error: file is too short ({len(data)} bytes); at least 22 bytes are needed "
            "to read the 82599 port-module pointers.",
            file=sys.stderr,
        )
        return 2

    print("Intel 82599 EEPROM configuration")
    print(f"File           : {args.binfile}")
    print(f"Image size     : {len(data)} bytes ({len(data) // 2} words)")

    expected_checksum, checksum_error = calculate_checksum(data)
    if checksum_error:
        print(f"Software checksum: not checked ({checksum_error})")
    else:
        stored_checksum = read_u16_le(data, 0x3F)
        status = "OK" if stored_checksum == expected_checksum else "MISMATCH"
        print(
            f"Software checksum: {status} "
            f"(stored=0x{stored_checksum:04X}, expected=0x{expected_checksum:04X})"
        )

    for line in decode_sfp_support(data):
        print(line)

    ports = (0, 1) if args.port == "all" else (int(args.port),)
    for port in ports:
        try:
            for line in decode_port(data, port):
                print(line)
        except IndexError as exc:
            print(f"\nPORT {port}\n  Error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
