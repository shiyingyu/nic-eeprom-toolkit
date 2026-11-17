# NIC EEPROM Toolkit

[简体中文](README_zh-CN.md)

A collection of command-line tools for inspecting and modifying EEPROM binary images used by Ethernet network interface controllers (NICs).

The repository is intended to grow beyond a single controller family. Each supported chip will have its own EEPROM layout and device-specific decoding/editing logic. **The current implementation supports the Intel 82599.**

> **Scope:** These tools operate on EEPROM image files only. They do not access a NIC, read a physical EEPROM, or program/flash a device.

## Features

### Intel 82599 EEPROM dump

`82599_eeprom_dump.py` reads a raw EEPROM binary image and reports commonly used configuration values:

- Port 0 and Port 1 LAN Core module pointers.
- MAC address for each port.
- LED0–LED3 mode, polarity and blink flag.
- Global LED blink timing.
- SDP control information when present in the LAN Core section.
- Intel 82599 software EEPROM checksum status.

The dump utility is read-only and never changes the input file.

### Intel 82599 EEPROM editor

`82599_eeprom_edit.py` modifies selected values through repeatable, human-readable `--set KEY=VALUE` arguments:

- Port MAC addresses.
- LED0–LED3 operating modes.
- LED output polarity.
- Per-LED blink enable/disable.
- Per-port global blink timing.

The editor follows the LAN Core module pointers in the EEPROM image instead of assuming fixed absolute locations for the port data. It updates only the requested fields, preserves the other LED byte when changing an LED configuration, and recalculates the 82599 software checksum.

The source image is never overwritten. By default, a new file named `<input>_modified.bin` is created. An existing output file is protected unless `--force` is supplied.

### X520-DA2 preset (Windows)

`82599_x520_apply.bat` is a Windows batch preset for the LED wiring used on an Intel X520-DA2 design:

| Port | EEPROM LED | Board signal | Function | Polarity |
|---|---:|---|---|---|
| SFP0 | LED0 | `SFP0_LED0_LINK_UP` (AD14) | `link-up` | `active-low` |
| SFP0 | LED2 | `SFP0_LED2_LINK/ACT` (AB14) | `link-activity` | `active-low` |
| SFP1 | LED0 | `SFP1_LED0_LINK_UP` (AD13) | `link-up` | `active-low` |
| SFP1 | LED2 | `SFP1_LED2_LINK/ACT` (AB13) | `link-activity` | `active-low` |

The preset also sets the two port MAC addresses and enables `sfp.allow-any=on` (Device Capabilities word `0x2C`, bit 0). In the Linux `ixgbe` driver this bypasses the applicable optical SFP vendor-OUI rejection; it does not guarantee that every third-party module will work. **Replace the example MAC addresses in the batch file with unique addresses assigned to your adapter before using it.**

## Requirements

- Python 3.10 or later.
- No third-party Python packages are required.
- The `.bat` preset is intended for Windows.

## Input image format

The current 82599 tools expect a raw EEPROM binary image with these properties:

- The image starts at EEPROM word address `0x0000`.
- Each EEPROM word is 16 bits and stored little-endian.
- The file contains the EEPROM image itself, not an additional file header or container format.

A vendor utility or a suitable hardware programmer may be used to obtain the binary image. The method for reading or programming physical hardware is outside the scope of this repository.

## Usage

### 1. Inspect an EEPROM image

Print both ports:

```bash
python 82599_eeprom_dump.py eeprom.bin
```

Print only Port 0 or Port 1:

```bash
python 82599_eeprom_dump.py eeprom.bin --port 0
python 82599_eeprom_dump.py eeprom.bin --port 1
```

Show command-line help:

```bash
python 82599_eeprom_dump.py --help
```

### 2. Modify an EEPROM image

The editor requires at least one `--set` argument. Repeat `--set` for each field to change:

```bash
python 82599_eeprom_edit.py eeprom.bin \
  --set port0.mac=02:00:00:00:00:10 \
  --set port1.mac=02:00:00:00:00:11 \
  --set port0.led0.mode=link-up \
  --set port0.led0.polarity=active-low \
  --set port0.led2.mode=link-activity \
  --set port0.led2.polarity=active-low \
  --set port1.led0.mode=link-up \
  --set port1.led0.polarity=active-low \
  --set port1.led2.mode=link-activity \
  --set port1.led2.polarity=active-low \
  -o eeprom_modified.bin
```

If `-o` is omitted, the editor creates `<input>_modified.bin` next to the input file. To overwrite an existing output file, explicitly add `--force`. The input file is never overwritten, even when `--force` is used.

Show all supported keys, values, definitions and examples:

```bash
python 82599_eeprom_edit.py --help
```

### 3. Run the X520-DA2 preset on Windows

Place the batch file and `82599_eeprom_edit.py` in the same directory. Edit `MAC_SFP0` and `MAC_SFP1` near the top of the batch file, then run:

```bat
82599_x520_apply.bat X520-DA2.bin
```

Optionally specify the output path:

```bat
82599_x520_apply.bat X520-DA2.bin X520-DA2_custom.bin
```

The preset writes a new binary image; it does not program the physical NIC.

## Supported 82599 editor settings

`N` is the port number (`0` or `1`). `M` is the LED index (`0` through `3`).

| Key | Accepted values | Description |
|---|---|---|
| `portN.mac` | Unicast MAC address, e.g. `02:00:00:00:00:10` | Station MAC address for the selected port. All-zero, all-`FF`, and multicast addresses are rejected. |
| `portN.ledM.mode` | See LED mode table below | Select the LED operating mode. |
| `portN.ledM.polarity` | `active-low`, `active-high` | Select the polarity encoding. In this tool, `active-low` maps to `IVRT=0` and `active-high` maps to `IVRT=1`. |
| `portN.ledM.blink` | `on`, `off` | Enable or disable the LED blink bit, subject to the mode requirements below. |
| `portN.blink-rate` | `200ms`, `83ms` | Set the port's global blink timing. |
| `sfp.allow-any` | `on`, `off` | Set the 82599 global `ALLOW_ANY_SFP` device-capability bit (EEPROM word `0x2C`, bit 0). |

### SFP vendor policy and PHY initialization table

The dump utility also reports two separate SFP-related NVM structures:

- EEPROM word `0x2C` is the Device Capabilities word. Bit 0 is `ALLOW_ANY_SFP`. The editor exposes it as `sfp.allow-any=on|off`; only this bit is changed, and the other bits are preserved.
- EEPROM word `0x2B` points to the PHY initialization type table. The dump utility follows this pointer and lists the SFP module-class IDs and their PHY initialization data pointers.

These fields serve different purposes. The PHY initialization table maps module classes (for example, passive DAC and 10GBASE-SR/LR) to initialization sequences; it is **not** a list of approved vendors or exact part numbers. `ALLOW_ANY_SFP` controls the vendor-OUI restriction used by the Linux `ixgbe` driver. When set, that driver bypasses its normal OUI-based rejection for applicable optical SFP modules. It does **not** disable all module checks: the driver still reads the module identifier and compliance information, applies module-type rules, and selects a PHY initialization sequence. The flag therefore does not guarantee that every third-party module is electrically, optically, firmware, or driver compatible. Intel's published X520 support table also distinguishes tested/officially supported modules from modules that may be accepted by a particular driver configuration. See the Linux [`ixgbe` implementation](https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/intel/ixgbe/ixgbe_phy.c) and Intel's [X520 SFP+ support information](https://www.intel.com/content/www/us/en/support/articles/000005688/ethernet-products.html) for these separate aspects.

Example:

```bash
python 82599_eeprom_edit.py eeprom.bin --set sfp.allow-any=on -o eeprom_any_sfp.bin
```

The current X520-DA2 sample image has `Device Capabilities = 0xFFFF`, so `ALLOW_ANY_SFP` is already set. The value `6A 0D` at file byte offset `0x56` is the little-endian representation of the pointer `0x0D6A` in EEPROM word `0x2B`; it is not the SFP allow-any flag.

### LED modes

| Value | Meaning | BLINK requirement |
|---|---|---|
| `link-up` | Link established at any supported speed | No special requirement |
| `link-10g` | 10 Gb/s link | No special requirement |
| `activity` | MAC transmit/receive activity | Must be on |
| `filtered-activity` | Filtered transmit/receive activity | Must be on |
| `link-activity` | Steady when linked and idle; blinks on activity | Must be off |
| `link-1g` | 1 Gb/s link | No special requirement |
| `link-100m` | 100 Mb/s link | No special requirement |
| `force-on` | Force LED on | No special requirement |
| `force-off` | Force LED off | No special requirement |

The editor automatically applies the required BLINK state when a mode requiring it is selected. If an explicitly supplied `blink` value conflicts with the selected mode, the editor rejects the request rather than silently overriding it.

Accepted friendly aliases include `link`, `mac-activity`, `filter-activity`, `link-100`, `on`, and `off`. The canonical values are shown in `--help`.

## Validation status

The 82599 workflow has been exercised with an Intel X520-DA2 EEPROM image: the image was inspected, modified, read back with this project's dump utility, and the modified image was independently checked with the [Intel82599eeprom](https://github.com/archaron/Intel82599eeprom) project.

This validation is useful evidence for the tested image and fields; it should not be interpreted as a guarantee for every 82599 board, EEPROM image variant, or hardware revision. Always validate a modified image against the target adapter and its documentation before programming it.

## Safety notes

1. **Keep an untouched backup** of the original EEPROM image.
2. Confirm that the input is a raw image in the expected format before editing it.
3. Use MAC addresses that are valid and uniquely assigned for the adapter. The addresses shown in examples are placeholders.
4. A correct software checksum does not by itself prove that the complete image is valid for a particular adapter or that the adapter will boot correctly.
5. The editor recalculates the 82599 software checksum word. It does not program hardware, verify a physical EEPROM write, or validate every hardware-specific field/signature.
6. Use an appropriate vendor tool or hardware programmer for physical EEPROM operations. Understand the recovery procedure before changing a production adapter's EEPROM.

## Project structure

Current files:

```text
nic-eeprom-toolkit/
├── README.md
├── README_zh-CN.md
├── 82599_eeprom_dump.py
├── 82599_eeprom_edit.py
└── 82599_x520_apply.bat
```

As support for additional controllers is added, their EEPROM layouts and chip-specific logic should remain clearly separated from the 82599 implementation.

## Roadmap

- Add support for additional Ethernet NIC and controller families.
- Separate shared binary helpers from chip-specific EEPROM layouts and field definitions where that becomes useful.
- Add automated tests and sanitized sample EEPROM fixtures for supported devices.
- Add more board-specific presets when their wiring and expected EEPROM settings are documented.

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for the complete license text.

The MIT License permits use, copying, modification, distribution, sublicensing, and commercial use, provided that the copyright and permission notice are included with copies or substantial portions of the software. The software is provided "as is", without warranty of any kind, as described in the license.
