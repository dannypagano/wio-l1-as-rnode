# Wio Tracker L1 Pro — RNode Firmware CE Board Support

This document records, step by step, how to reproduce a working `RNode_Firmware_CE` build
for the Seeed Studio Wio Tracker L1 Pro (nRF52840 + Wio-SX1262 + L76K GPS), starting from
an unmodified clone of [`liberatedsystems/RNode_Firmware_CE`](https://github.com/liberatedsystems/RNode_Firmware_CE).

**Status: fully confirmed working, including the OLED display.** The device boots, is
provisioned and validated with `rnodeconf`, has been used successfully as a live
`RNodeInterface` (real -104 dBm noise-floor reading through Sideband, confirming the
radio genuinely receives rather than just reporting a fake "on" state), and the OLED
display now correctly initializes and updates. Real over-the-air TX/RX *between two
nodes* has not yet been separately confirmed; GPS is unimplemented. See Part 10.

**Two further bugs were found and fixed after initial radio bring-up** (Parts 6 and 7):
a firmware bug that silently dropped TX power for any unlisted board model, and a
bootloader/firmware mismatch that permanently blocked the radio from turning on at all
under RNS (as opposed to `rnodeconf`, which uses different, less strict validation and
didn't catch it). Part 7's fix in particular is a real security tradeoff (disables a
firmware integrity check), not just a bug fix -- read it before assuming it's the right
permanent answer.

**A later session (Part 9) fixed the OLED display**, which turned out to be three small,
independent bugs stacked on top of each other: a wrong I2C address, a wrong
`Wire.begin()` call (nRF52's `TwoWire` doesn't accept ESP32-style `begin(sda, scl)`), and
a missing `MONO_OLED` case in the main loop's display-refresh condition (the screen
initialized once, drew the boot splash, and then simply never redrew again).
Diagnosing this produced a real trap worth remembering for future debugging: an early
attempt to read boot output over serial appeared to show the firmware hanging, when the
"hang" was actually just unprintable KISS protocol framing bytes rendering as blank
boxes in a terminal and getting silently dropped on copy-paste -- resolved only by
logging raw hex instead of decoded text.

**Upstream plan:** several fixes from this session are genuinely board-agnostic bugs
(not just Wio Tracker L1 Pro accommodations) and are worth proposing upstream once
reviewed and hand-verified per `CONTRIBUTING.md`'s no-LLM-authorship rule -- see Part 11
for a prioritized list of what's likely worth submitting versus what's still an open
question.

**Repo layout:**
```
README.md                    -- this file
src/Boards.h                 -- full file, drop-in replacement for RNode_Firmware_CE's Boards.h
src/Utilities.h              -- full file, drop-in replacement for RNode_Firmware_CE's Utilities.h
src/RNode_Firmware_CE.ino    -- full file, drop-in replacement for RNode_Firmware_CE's .ino
src/Display.h                -- full file, drop-in replacement for RNode_Firmware_CE's Display.h
src/Radio.cpp.patch          -- snippet only (not a full file) -- see Part 6
src/Makefile.additions       -- snippet to append to RNode_Firmware_CE's Makefile
toolchain/setup.sh           -- reproduces the hybrid Arduino board definition (Part 3)
toolchain/wio_tracker.cfg    -- OpenOCD config for SWD debugging via a Raspberry Pi (Part 4)
toolchain/patch_rnodeconf.py -- patches a local rnodeconf install for this board (Part 5)
toolchain/kiss-debug-scripts/raw_initradio_test.py -- raw KISS protocol test tool (Part 7)
toolchain/kiss-debug-scripts/serial_hexlog.py -- raw hex serial logger, avoids the
                                                   text-encoding trap described in Part 9
```

To use: clone `RNode_Firmware_CE` separately, copy the three files from `src/` over the
matching files in that clone, append `src/Makefile.additions` to its `Makefile`, then run
`toolchain/setup.sh` once before compiling.

**Not upstream-ready.** `Documentation/CONTRIBUTING.md` in the RNode_Firmware_CE repo
explicitly prohibits LLM-authored contributions. This document and the accompanying code
changes were produced with AI assistance and should be treated as a personal reference /
scratch draft, not something to submit as a PR as-is. Anyone wanting to upstream this
should hand-write and personally verify their own version of these changes.

---

## Hardware summary

- MCU: Nordic nRF52840
- Radio: Semtech SX1262 (Seeed "Wio-SX1262" module)
- GPS: Quectel L76K (UART, not used by RNode firmware — no GPS support added)
- Display: OLED, physically present on this board (1.3", SH1106 controller (confirmed
  correct per Zephyr's official board docs, and now working -- see Part 9)
- Flash: external QSPI (not used by RNode firmware on this build — EEPROM emulation uses
  LittleFS on **internal** flash instead, see Part 4)
- Bootloader: this specific unit's bootloader was reflashed at some point by Seeed support
  with a **Seeed XIAO nRF52840** bootloader (originally reporting `Board-ID:
  nRF52840-SeeedXiao-v1`, `SoftDevice: S140 7.3.0` via `INFO_UF2.TXT`). That claimed
  SoftDevice version turned out to be **inaccurate or the actual binary didn't match** —
  see Part 4 for the full investigation and fix. The device has since been reflashed with
  a byte-verified, known-good bootloader+SoftDevice image via SWD.
- SWD test header: 1x5, 2.0mm pitch, silkscreened (left to right) `GND SWC SWD RST 3V3`.

---

## Part 1 — Pin mapping reference

Derived from Seeed's official schematic PDF (`Wio_Tracker_L1_Pro_SCH_PDF.pdf`) and
cross-confirmed against Zephyr's official `wio_tracker_l1` board devicetree
(https://docs.zephyrproject.org/latest/boards/seeed/wio_tracker_l1/doc/index.html), which
matched the schematic net names exactly. **All values below are now confirmed correct by
a fully working, provisioned device** — this is no longer inferred from documentation
alone.

| Function | nRF52 pin | Arduino pin # (raw passthrough) |
|---|---|---|
| LoRa SCK | P0.30 | 30 |
| LoRa MISO | P0.03 | 3 |
| LoRa MOSI | P0.28 | 28 |
| LoRa CS (NSS) | P1.14 | 46 |
| LoRa DIO1 (IRQ) | P0.07 | 7 |
| LoRa BUSY | P1.10 | 42 |
| LoRa RESET | P1.07 | 39 |
| LoRa RX-enable (LNA) | P1.08 | 40 |
| OLED I2C SDA | P0.06 | 6 |
| OLED I2C SCL | P0.05 | 5 |
| User button (Menu) | P0.08 | 8 |
| User LED ("Mesh_LED") | P1.01 | 33 |

**Radio switch config:** `DIO2_AS_RF_SWITCH = true`; P1.08 is `pin_rxen` (LNA/RX-enable),
not `pin_txen`. Confirmed via Zephyr's board docs and now confirmed working — `rnodeconf
-i` correctly reports modem chip SX1262 and frequency range 820-1020 MHz.

**TCXO:** `HAS_TCXO = true`, `pin_tcxo_enable = -1` (handled internally by the Wio-SX1262
module).

**SPI peripheral:** `NRF_SPIM3` is used for the radio's SPI interface (see Part 2.3).
SPIM0/SPIM1 are already claimed by this board's two I2C buses (OLED on TWIM0, Grove
connector on TWIM1) — SPIM/TWIM share underlying hardware per instance number on the
nRF52840. `NRF_SPIM3` is now confirmed working; `NRF_SPIM2` was never tried since SPIM3
worked on the first fully-correct attempt.

**Arduino pin numbering convention:** confirmed by inspecting `g_ADigitalPinMap` in
Adafruit's `pca10056` variant — Arduino pin N maps directly to raw nRF52 pin N (i.e.
`P1.xx` = `32 + xx`). **This is only true for board variants using raw passthrough
numbering.** The stock `Seeeduino:nrf52:xiaonRF52840` variant does **not** use this
scheme — its `g_ADigitalPinMap` is a short, curated table mapping ~30 indices to Seeed's
own XIAO dev-board silkscreen labels, unrelated to this board's actual wiring. This is why
the hybrid board definition in Part 3 exists.

---

## Part 2 — Firmware source changes

Four files needed changes. All BOARD_MODEL/PRODUCT/MODEL codes were chosen to avoid
collisions with existing values (checked against every `#define` in `Boards.h`).

```
#define PRODUCT_WIO_TRACKER_L1 0x19
#define BOARD_WIO_TRACKER_L1   0x53
#define MODEL_1A                0x1A
```

### 2.1 — `Boards.h`

Two additions:

**A. Top-of-file product/board/model defines**, placed near the other nRF52 boards
(after the `PRODUCT_TECHO` block):

```cpp
#define PRODUCT_WIO_TRACKER_L1 0x19 // Wio Tracker L1 Pro - sold by Seeed Studio
#define BOARD_WIO_TRACKER_L1 0x53
#define MODEL_1A 0x1A // Wio Tracker L1 Pro, 863-928 MHz (SX1262)
```

**B. Board implementation block**, inside the `#elif MCU_VARIANT == MCU_NRF52` chain,
placed after the `BOARD_HELTEC_T114` block and before the closing `#else #error`:

```cpp
#elif BOARD_MODEL == BOARD_WIO_TRACKER_L1
#define HAS_EEPROM false
#define HAS_DISPLAY true
#define DISPLAY OLED
#define HAS_BLUETOOTH false
#define HAS_BLE true
#define HAS_CONSOLE false
#define HAS_PMU false
#define HAS_NP false
#define HAS_SD false
#define HAS_INPUT true
#define CONFIG_UART_BUFFER_SIZE 6144
#define CONFIG_QUEUE_0_SIZE 6144
#define CONFIG_QUEUE_MAX_LENGTH 200
#define EEPROM_SIZE 296
#define EEPROM_OFFSET EEPROM_SIZE - EEPROM_RESERVED
#define BLE_MANUFACTURER "Seeed Studio"
#define BLE_MODEL "Wio Tracker L1 Pro"
#define INTERFACE_COUNT 1

const uint8_t interfaces[INTERFACE_COUNT] = {SX1262};
const bool interface_cfg[INTERFACE_COUNT][3] = {
    // SX1262
    {
        false, // DEFAULT_SPI -- nRF52+SX1262 boards in this file all use false
        true,  // HAS_TCXO -- confirmed via Wio-SX1262 DIO3 TCXO ref (1.8V)
        true   // DIO2_AS_RF_SWITCH -- confirmed via Zephyr board docs, and now
               //                      confirmed working on real hardware
    },
};
const int8_t interface_pins[INTERFACE_COUNT][10] = {
    // SX1262
    {
        46, // pin_ss   (LoRa_CS,   P1.14)
        30, // pin_sclk (LoRa_SCK,  P0.30)
        28, // pin_mosi (LoRa_MOSI, P0.28)
        3,  // pin_miso (LoRa_MISO, P0.03)
        42, // pin_busy (LoRa_BUSY, P1.10)
        7,  // pin_dio  (LoRa_DIO1, P0.07)
        39, // pin_reset(LoRa_RST,  P1.07)
        -1, // pin_txen
        40, // pin_rxen (P1.08, RX-enable/LNA-enable per Zephyr docs)
        -1  // pin_tcxo_enable (internal to module)
    }};

#define I2C_SDA 6 // OLED_I2C_SDA
#define I2C_SCL 5 // OLED_I2C_SCL
const int pin_btn_usr1 = 8;  // Menu_Key
const int pin_led_rx = 33;   // Mesh_LED, P1.01
const int pin_led_tx = 33;   // Mesh_LED, P1.01 (shared, single LED on board)
```

### 2.2 — `Utilities.h`

Three additions — none of these are obvious from `Boards.h` alone; each was found by
hitting a compile error or a silent runtime failure.

**A. LED on/off functions.** Every board gets its own explicit
`led_rx_on/off`/`led_tx_on/off`/`led_id_on/off` block in a separate `#if MCU_VARIANT ==
MCU_NRF52` chain (not derived automatically from `pin_led_rx`/`pin_led_tx`). This chain
has **no fallback `#else`**, so an unlisted board silently compiles to nothing —
producing "function not declared" errors at the call sites elsewhere in the codebase.
Added as a new arm right before the chain's closing `#endif #endif` (after the
`BOARD_TECHO` arm):

```cpp
	#elif BOARD_MODEL == BOARD_WIO_TRACKER_L1
		void led_rx_on()  { digitalWrite(pin_led_rx, HIGH); }
		void led_rx_off() {	digitalWrite(pin_led_rx, LOW); }
		void led_tx_on()  { digitalWrite(pin_led_tx, HIGH); }
		void led_tx_off() { digitalWrite(pin_led_tx, LOW); }
		void led_id_on()  { }
		void led_id_off() { }
	#endif
#endif
```

Confirmed working — the top LED (silkscreened with a lightning-bolt icon, near the power
switch) lights correctly.

**B. `eeprom_product_valid()`** — the nRF52 platform check is a hardcoded list of valid
`PRODUCT_*` codes. Without adding ours, the firmware would compile and flash fine but
treat itself as having an invalid product code once provisioned (silent runtime failure,
not a compile error):

```cpp
	#elif PLATFORM == PLATFORM_NRF52
	if (rval == PRODUCT_RAK4631 || rval == PRODUCT_HELTEC_T114 || rval == PRODUCT_OPENCOM_XL || rval == PRODUCT_TECHO || rval == PRODUCT_WIO_TRACKER_L1 || rval == PRODUCT_HMBRW) {
```

**C. `eeprom_model_valid()`** — same pattern, a per-board `#elif` chain of valid
`MODEL_*` values, falling through to `if (false)` for anything unlisted. Added as a new
arm (after `BOARD_OPENCOM_XL`):

```cpp
    #elif BOARD_MODEL == BOARD_OPENCOM_XL
    if (model == MODEL_21) {
    #elif BOARD_MODEL == BOARD_WIO_TRACKER_L1
    if (model == MODEL_1A) {
```

### 2.3 — `RNode_Firmware_CE.ino`

Two separate changes were needed here.

**A. Custom SPI object construction.** The global `interface_spi[1]` SPI object needs
board-specific construction on nRF52 (the Adafruit-derived `SPIClass` has no
default/zero-argument constructor — each nRF52840 SPIM hardware peripheral instance must
be nominated explicitly). Added as a new arm in the existing `#if MCU_VARIANT ==
MCU_NRF52` / `#if BOARD_MODEL == ...` chain near the top of the file (after the
`BOARD_HELTEC_T114` arm):

```cpp
  #elif BOARD_MODEL == BOARD_WIO_TRACKER_L1
  #define INTERFACE_SPI
  SPIClass interface_spi[1] = {
      // SX1262
      SPIClass(
          NRF_SPIM3,
          interface_pins[0][3],
          interface_pins[0][1],
          interface_pins[0][2])};
```

**B. Skip the `while (!Serial)` boot wait.** Every nRF52 board already in this codebase
— RAK4631, Heltec T114, T-Echo, openCom XL — is explicitly excluded from a
`while (!Serial);` wait right after `Serial.begin()` in `setup()`. This is because on
nRF52's native USB CDC (TinyUSB), `Serial`'s boolean state reflects the host asserting
the DTR control line, which is notoriously unreliable across different serial
tools/libraries (including `pyserial`, which `rnodeconf` uses). Without this exclusion,
`rnodeconf` could open the port successfully but get **no response at all** ("Serial port
opened, but RNode did not respond") because the firmware was stuck forever at this wait,
never reaching the KISS command loop. Add `BOARD_WIO_TRACKER_L1` to the existing
exclusion list:

```cpp
  #if BOARD_MODEL != BOARD_RAK4631 && BOARD_MODEL != BOARD_HELTEC_T114 && BOARD_MODEL != BOARD_TECHO && BOARD_MODEL != BOARD_T3S3 && BOARD_MODEL != BOARD_TBEAM_S_V1 && BOARD_MODEL != BOARD_OPENCOM_XL && BOARD_MODEL != BOARD_WIO_TRACKER_L1
    while (!Serial);
  #endif
```

### 2.4 — `Makefile`

Two new targets, modeled on the existing `firmware-techo` / `upload-techo` pattern:

```makefile
firmware-wio_tracker_l1:
	arduino-cli compile --log --fqbn Seeeduino:nrf52:wioTrackerL1 -e --build-property "compiler.cpp.extra_flags=\"-DBOARD_MODEL=0x53\""

upload-wio_tracker_l1:
	arduino-cli upload -p /dev/ttyACM0 --fqbn Seeeduino:nrf52:wioTrackerL1
	@sleep 6
	rnodeconf /dev/ttyACM0 --firmware-hash $$(./partition_hashes from_device /dev/ttyACM0)
```

Note the FQBN — this is **not** a stock board target. See Part 3.

---

## Part 3 — Arduino toolchain setup

No single stock Arduino board package works correctly for this board, because two
independent requirements point at two different, incompatible packages: correct
SoftDevice-matched linker/bootloader files, and correct raw pin-passthrough numbering.

### The problem, in order of discovery

1. Started with `adafruit:nrf52:pca10056` (Nordic's own nRF52840 DK target). Compiled
   fine, correct raw pin-passthrough numbering — but the flashed device never booted.
2. Root cause: this board's bootloader requires SoftDevice `S140 7.3.0`, but the Adafruit
   core installed only ships an `nrf52840_s140_v6.ld` linker script for the nRF52840 — no
   v7 script exists for that chip in that core release.
3. Switched to `Seeeduino:nrf52:xiaonRF52840` (Seeed's own core, installed via
   `https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json`). This
   package does ship `nrf52840_s140_v7.ld`, confirmed by the linker placing the app at
   `0x27000` instead of `0x26000`. Compiled clean — but still didn't boot.
4. Root cause: the `Seeed_XIAO_nRF52840` variant this FQBN uses does **not** use raw pin
   passthrough (see Part 1's numbering note).
5. **Fix: hybrid board definition.** Built a custom board entry inside the Seeeduino
   package that reuses Adafruit's `pca10056` variant files (for correct raw-passthrough
   pins) but keeps Seeeduino's linker/bootloader/SoftDevice settings (for the correct
   S140 version). This got the device booting and executing application code — but a
   *third*, deeper problem (Part 4) was still hiding underneath before the radio actually
   worked.

### Reproduction steps

**1. Install both board packages:**

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli config add board_manager.additional_urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
arduino-cli core update-index
arduino-cli core install adafruit:nrf52
arduino-cli core install Seeeduino:nrf52
```

**2. Copy the raw pin-passthrough variant into the Seeeduino package:**

```bash
mkdir -p "$(arduino-cli config dump | grep data_dir | awk '{print $2}')/packages/Seeeduino/hardware/nrf52/1.1.13/variants/pca10056_raw"

cp /path/to/packages/adafruit/hardware/nrf52/1.7.0/variants/pca10056/variant.cpp \
   /path/to/packages/Seeeduino/hardware/nrf52/1.1.13/variants/pca10056_raw/variant.cpp
cp /path/to/packages/adafruit/hardware/nrf52/1.7.0/variants/pca10056/variant.h \
   /path/to/packages/Seeeduino/hardware/nrf52/1.1.13/variants/pca10056_raw/variant.h
```

**3. Append a new board entry to the Seeeduino package's `boards.txt`:**

```
wioTrackerL1.name=Wio Tracker L1 Pro (raw pins, S140 v7)

wioTrackerL1.vid.0=0x2886
wioTrackerL1.pid.0=0x8044

wioTrackerL1.upload.tool=nrfutil
wioTrackerL1.upload.protocol=nrfutil
wioTrackerL1.upload.use_1200bps_touch=true
wioTrackerL1.upload.wait_for_upload_port=true
wioTrackerL1.upload.maximum_size=811008
wioTrackerL1.upload.maximum_data_size=237568

wioTrackerL1.build.mcu=cortex-m4
wioTrackerL1.build.f_cpu=64000000
wioTrackerL1.build.board=Seeed_XIAO_nRF52840
wioTrackerL1.build.core=nRF5
wioTrackerL1.build.variant=pca10056_raw
wioTrackerL1.build.usb_manufacturer="Seeed"
wioTrackerL1.build.usb_product="Wio Tracker L1 Pro"
wioTrackerL1.build.extra_flags=-DNRF52840_XXAA {build.flags.usb}
wioTrackerL1.build.ldscript=nrf52840_s140_v7.ld
wioTrackerL1.build.vid=0x2886
wioTrackerL1.build.pid=0x8044
wioTrackerL1.build.sd_name=s140
wioTrackerL1.build.sd_version=7.3.0
wioTrackerL1.build.sd_fwid=0x0123

wioTrackerL1.bootloader.tool=bootburn
```

Note `build.board=Seeed_XIAO_nRF52840` — this is **not** cosmetic. At least one bundled
library (`Wire_nRF52.cpp`) has a hardcoded `#if defined(ARDUINO_<board>)` check with an
`#error "Unsupported board"` fallback. Setting `build.board` to a name that library
already recognizes was the path of least resistance.

**4. Install the one missing library dependency:**

```bash
arduino-cli lib install Crypto
```

(This is the "Crypto" library by Rhys Weatherley / rweather, providing `Ed25519.h` for
firmware signing. Everything else RNode needs ships with the Seeeduino core itself.)

**5. Compile:**

```bash
arduino-cli compile --log --fqbn Seeeduino:nrf52:wioTrackerL1 -e \
  --build-property "compiler.cpp.extra_flags=\"-DBOARD_MODEL=0x53\""
```

**6. Convert the resulting `.hex` to `.uf2`**, using this board's actual bootloader
family ID — **not** the generic `NRF52` entry in `uf2conv.py`'s built-in table. The
correct value, `0x28860044`, was extracted by parsing the UF2 header of the
factory-installed (working) Meshtastic firmware that was originally on the device (the
first 4 bytes, `0x2886`, match Seeed's registered USB Vendor ID — this is a deliberate
VID-derived scheme, not arbitrary):

```bash
python3 /path/to/packages/Seeeduino/hardware/nrf52/1.1.13/tools/uf2conv/uf2conv.py \
  -c -f 0x28860044 \
  -o build/Seeeduino.nrf52.wioTrackerL1/RNode_Firmware_CE.ino.uf2 \
  build/Seeeduino.nrf52.wioTrackerL1/RNode_Firmware_CE.ino.hex
```

Sanity check: this should report `start address: 0x27000`.

**7. Flash it.** Enter bootloader mode by **holding** (not double-tapping) the reset
button — this specific bootloader responds to press-and-hold, not the double-tap gesture
described in generic documentation. Then:

```bash
cp build/Seeeduino.nrf52.wioTrackerL1/RNode_Firmware_CE.ino.uf2 /Volumes/XIAO-BOOT/
```

Use `cp` from a terminal, not Finder/Explorer drag-and-drop — Finder has thrown spurious
"Error code -36" failures against this bootloader's FAT volume on macOS.

---

## Part 4 — The SoftDevice/bootloader root cause (SWD debugging)

Even with the toolchain fixed (Part 3), the board would boot and execute early code, but
`eeprom_begin()` — specifically the very first genuine SoftDevice flash-write operation
the firmware performs — would hang forever with no serial output and no error. This
turned out to require actual hardware debugging to solve; LED-based bisection alone
wasn't enough to find it. This section is included in full because the debugging
technique (SWD via a Raspberry Pi's GPIO header, no dedicated probe hardware) is broadly
reusable for anyone hitting similarly opaque nRF52 SoftDevice issues.

### Setting up SWD via a Raspberry Pi

No dedicated SWD probe is needed — a Raspberry Pi's GPIO header can bit-bang the SWD
protocol directly via OpenOCD.

**Wiring** (board silkscreen, left to right: `GND SWC SWD RST 3V3` — **do not connect
3V3**, the board is already powered via USB and back-feeding the rail from the Pi risks a
supply conflict):

| Board pin | Signal | Pi connection |
|---|---|---|
| 1 | GND | Pi GND |
| 2 | SWC (SWCLK) | Any free GPIO (avoid GPIO 0/1) |
| 3 | SWD (SWDIO) | Any free GPIO (avoid GPIO 0/1) |
| 4 | RST | Not connected (OpenOCD resets via the debug port itself) |
| 5 | 3V3 | **Not connected** |

The board's SWD header is 1x5, 2.0mm pitch — narrower than standard 2.54mm headers.
Either solder solid-core wire directly into the three needed holes, or use a 2.0mm-pitch
header/pogo pins if available.

**Install OpenOCD on the Pi:**
```bash
sudo apt install openocd
```

**Config** (`toolchain/wio_tracker.cfg` in this repo — using BCM GPIO 25/24 as an
example, adjust to match your wiring):
```
adapter driver linuxgpiod

transport select swd

adapter gpio swclk -chip 0 25
adapter gpio swdio -chip 0 24

adapter speed 1000

source [find target/nrf52.cfg]
```

**Connect:**
```bash
sudo openocd -f wio_tracker.cfg
```

A successful connection reports detecting the Cortex-M4 core and "Examination succeed."
In a second terminal, use `nc localhost 4444` to reach OpenOCD's Tcl console (`telnet`
may not be installed by default on Raspberry Pi OS; `nc` works identically for this).

### Diagnosing the hang

With the hang reproduced (board flashed with firmware that calls into `eeprom_begin()`):
```
halt
reg pc
```

This returned a fixed, repeatable address every time, which `arm-none-eabi-addr2line`
(bundled with the Arduino core's toolchain) resolved to `HardFault_Handler`:
```bash
/path/to/packages/Seeeduino/tools/arm-none-eabi-gcc/9-2019q4/bin/arm-none-eabi-addr2line \
  -e build/.../fs_test.ino.elf -f -C 0xPC_VALUE
```

Reading the exception stack frame (pushed automatically by the hardware at fault time,
laid out as `R0 R1 R2 R3 R12 LR PC xPSR` starting at the stack pointer) gave the *actual*
faulting PC and the calling function's return address:
```
reg sp
mdw 0x<SP>+0x18 1    # stacked PC  (offset 24 bytes)
mdw 0x<SP>+0x14 1    # stacked LR  (offset 20 bytes)
```

And the CPU fault status registers, which classify *why* it faulted:
```
mdw 0xE000ED28 1    # CFSR - Configurable Fault Status Register
mdw 0xE000ED2C 1    # HFSR - HardFault Status Register
```

Result: `CFSR` bit 8 set (`IBUSERR` — instruction bus error), `HFSR` bit 30 set
(`FORCED` — a lower-priority fault escalated to HardFault). The stacked PC was a
nonsensical address outside any valid flash/RAM region. The stacked LR resolved (via
`addr2line`) to an address *inside the closed-source SoftDevice binary itself* — meaning
the crash wasn't in our code, but inside the SoftDevice's own internal logic while
handling our flash-erase request.

### Ruling out RAM sizing and variant/linker mismatches

Several plausible causes were tested and eliminated with direct evidence before finding
the real one:
- **RAM reservation size** — deliberately increased the linker's RAM origin by 40KB as a
  test. Rebuilt, reflashed, re-checked via OpenOCD: **identical PC and LR** as before,
  down to the exact address. Ruled out.
- **Hardcoded flash addresses in the copied `variant.cpp`** — grepped for `0x26000`,
  `VTOR`, vector table references: none found.
- **Core-level branching on the `_VARIANT_PCA10056_` macro** — grepped the entire
  Seeeduino core: no references at all, confirmed inert.

### The actual root cause

With the variant/linker layer ruled out, the remaining explanation was that the
SoftDevice binary itself — whatever Seeed's support team had actually flashed onto this
specific chip during an earlier recovery — didn't genuinely match what `INFO_UF2.TXT`
claimed (`S140 7.3.0`). **Fix: reflash a byte-verified, known-good combined
bootloader+SoftDevice image directly over SWD**, bypassing any uncertainty about what was
actually in flash:

```bash
# Mass-erase first
sudo openocd -f wio_tracker.cfg -c "init" -c "reset halt" -c "nrf5 mass_erase" -c "shutdown"

# Flash the combined image (ships with the Seeeduino core itself)
sudo openocd -f wio_tracker.cfg -c "program /path/to/Seeed_XIAO_nRF52840_bootloader-0.6.2_s140_7.3.0.hex verify reset exit"
```

That file lives at:
```
<Seeeduino core dir>/bootloader/Seeed_XIAO_nRF52840/Seeed_XIAO_nRF52840_bootloader-0.6.2_s140_7.3.0.hex
```

After this reflash, the identical `fs_test` build that previously hard-faulted every
single time ran cleanly — confirmed via OpenOCD showing `Handler PendSV` (normal
FreeRTOS scheduler activity, with the PC advancing between successive halts) rather than
`Handler HardFault` stuck at a fixed address, and both `CFSR`/`HFSR` reading `0x00000000`
(no fault flags set at all).

**Important operational note:** after flashing an application `.hex` directly over SWD
(bypassing the normal UF2 flow), the bootloader's own "valid application present" flag
does **not** get updated, so it won't boot into that application — it'll just sit in
DFU/bootloader mode. **Always flash the actual application firmware via the normal UF2
drag-and-drop flow** (Part 3, step 7), even after using SWD to fix the bootloader/
SoftDevice itself. SWD is for bootloader/SoftDevice-level work and low-level debugging;
UF2 is for application firmware.

**Safety note on this whole procedure:** this is very hard to actually brick. SWD access
is a hardware debug port independent of flash contents — as long as OpenOCD can connect
(which is easy to verify with a plain `reset halt`/`reg pc` before attempting anything
destructive), a bad write can always be corrected with another mass-erase and reflash.
The only realistic way to lose SWD access entirely is if something sets nRF52's
APPROTECT (Access Port Protection) bit in UICR, which none of the commands here do.

---

## Part 5 — Provisioning with `rnodeconf`

Once the firmware boots and the radio initializes, the device still needs to be
provisioned (product/model/hardware-revision/serial/timestamp written to EEPROM, along
with a checksum and cryptographic signature) before `rnodeconf` will consider it a valid
RNode.

### Do not use `rnodeconf --autoinstall` or the guided device-type menu

Both of these assume you're setting up one of `rnodeconf`'s known, hardcoded board types
and will offer to **flash a generic stock firmware image** for whatever board you select
— which would silently overwrite this custom build with completely wrong firmware for
different hardware. Avoid any prompt that asks "what kind of device is this?" and offers
a numbered list of board options.

### Provisioning with explicit product/model codes

`rnodeconf` does support bootstrapping EEPROM with arbitrary custom codes via CLI flags —
this isn't gated behind its internal board tables the way the guided flow is. The one
formatting gotcha: hex values must be passed **without** a `0x` prefix (bare two-digit
hex, e.g. `19` not `0x19`):

```bash
rnodeconf /dev/cu.usbmodemXXXX -r --platform 70 --product 19 --model 1a --hwrev 1
```

(`-r`/`--rom` bootstraps EEPROM only, no firmware flash; `70` = `PLATFORM_NRF52`, `19` =
`PRODUCT_WIO_TRACKER_L1`, `1a` = `MODEL_1A`)

If a previous provisioning attempt already wrote a valid-checksummed EEPROM (even with
wrong values, e.g. from a different tool defaulting to generic codes), `rnodeconf` will
refuse to overwrite it. Wipe first:
```bash
rnodeconf /dev/cu.usbmodemXXXX --eeprom-wipe
```

### A write-timing bug specific to this board, and the fix

The bootstrap process would consistently fail partway through — not randomly, but at
almost exactly the same byte offset every time — with "EEPROM was written, but
validation failed." Dumping the EEPROM directly (`rnodeconf --eeprom-dump`) and comparing
against the expected field layout (`product, model, hwrev, serial[4], made[4],
checksum[16], signature[128], lock_byte` — total 155 bytes before the lock byte) showed
the write consistently stopped partway through the 128-byte signature block, never
reaching the final lock byte.

**Root cause:** `rnodeconf.py`'s EEPROM bootstrap routine writes each byte individually
via KISS commands with a hardcoded `time.sleep(0.006)` (6ms) between writes. This board's
EEPROM is emulated via LittleFS on **internal flash** (`HAS_EEPROM false`, not a real
EEPROM peripheral), and each individual byte write goes through real flash erase/program
operations — genuinely slower than 6ms allows for. The fixed writes-per-second pacing
this delay assumes doesn't hold for this board's storage backend, and later writes in the
sequence get lost once some backlog finally overflows.

**Fix:** locally patch the installed `rnodeconf.py` to use a longer delay. `0.006` →
`0.05` got partway further (fewer missing bytes, confirming the theory); `0.006` → `0.15`
completed the full write cleanly (confirmed via checksum-correct + signature-validated on
the next read):

```bash
sed -i '' 's/time\.sleep(0\.006)/time.sleep(0.15)/g' \
  /path/to/site-packages/RNS/Utilities/rnodeconf.py
```

(`toolchain/patch_rnodeconf.py` in this repo automates this and the two display-crash
fixes below — point it at your local `rnodeconf.py` path.)

This patch lives in your local Python environment, not this repo's own code — **it will
be lost if the `rns` package is reinstalled or updated**, and will need reapplying.

### Two unrelated display-crash bugs in `rnodeconf -i`

Separately, `rnodeconf -i` (device info display) crashes with an unhandled `KeyError` for
any product/model code not in its local, hardcoded `products`/`models` Python
dictionaries — which of course don't know about custom codes like ours. This doesn't
indicate anything wrong with the device (checksum/signature validation, which happens
*before* this display code runs, already succeeded by the time these crashes occur) —
it's purely a cosmetic bug in the info-printing code. Two separate unguarded dictionary
lookups needed guarding:

1. `models[rnode.model][4]` (used to look up a firmware filename during device-info
   reads) — wrap in `try/except KeyError`.
2. `products[rnode.product]`, `models[rnode.model][3]`, and `models[rnode.model][5]` (used
   in the formatted "Device info:" printout) — replace with `x if key in dict else
   "Unknown ..."` fallback expressions.

Both patches are included in `toolchain/patch_rnodeconf.py`.

### Confirmed working end state

After applying all three patches and provisioning cleanly:
```
rnodeconf /dev/cu.usbmodemXXXX -i
```
reports: firmware version 1.75, EEPROM checksum correct, device signature validated
(against the local signing key used to provision it), product/model bytes matching
`19:1a:53` exactly, device mode "Normal (host-controlled)". The earlier radio test
(`rnodeconf ... --freq ... --bw ... --sf ... -T`) had already independently confirmed the
device correctly echoes back frequency/bandwidth/spreading-factor/coding-rate and
switches to TNC mode without error.

---

## Part 6 — TX power bug: a silent, model-gated no-op

After initial radio bring-up, every radio parameter reported back correctly through
`rnodeconf` except TX power, which always came back as `0 dBm` regardless of what was
requested (`--txp 14` reported "TX power is 0 dBm"). This affected every test, using
either `rnodeconf` directly or a real RNS config through Sideband (which surfaced it as
a hard startup failure: `"TX power mismatch"`).

**Root cause:** the KISS `CMD_TXPOWER` handler in `RNode_Firmware_CE.ino` doesn't call a
method on the radio object directly (unlike frequency, bandwidth, SF, and CR, which all
do: `selected_radio->setFrequency(freq)` etc.). It calls a separate free-standing wrapper
function instead:

```cpp
if (op_mode == MODE_HOST) setTXPower(selected_radio, txp);
```

That wrapper, in `Utilities.h`, is an exhaustive `if (model == MODEL_XX) radio->setTxPower(...)`
chain covering every model code in the entire codebase individually, **with no `else`/
default fallback at all**. Confirmed by reading through to the function's literal closing
brace. Since `MODEL_1A` (our board) was never added to this list, every `if` fails to
match, the function falls through having done nothing, and the radio's internal `_txp`
value stays at its constructor default of `0` forever -- regardless of what's requested.

The maintainer's own comment at the top of this function acknowledges it's a known rough
edge: *"Todo, revamp this function. The current parameters for setTxPower are suboptimal,
as some chips have power amplifiers which means that the max dBm is not always the same."*
Every new board added to this codebase has to remember to add itself here, or TX power
silently does nothing -- a sharp, easy-to-miss edge for anyone porting a new board.

**Fix:** add our model, matching every other SX1262-based model's parameter
(`PA_OUTPUT_PA_BOOST_PIN` -- `PA_OUTPUT_RFO_PIN` is only used by SX1276/SX1278 models):

```cpp
if (model == MODEL_1A) radio->setTxPower(txp, PA_OUTPUT_PA_BOOST_PIN);
```

This is a genuine, board-agnostic bug -- worth prioritizing for upstream contribution
separately from anything else in this repo, since it would affect any new SX1262/SX1280
board added to this codebase, not just this one.

### A related, unconfirmed fix found along the way: TCXO configuration

While investigating the TX power issue, a separate board-list gap was found in
`Radio.cpp`'s TCXO configuration function -- `BOARD_WIO_TRACKER_L1` was missing from the
list of boards that get a real TCXO voltage/timeout buffer sent to the chip, falling
through to an all-zero buffer (no TCXO configuration at all) instead. Since `HAS_TCXO =
true` is set for this board in `Boards.h`, this was a real gap. See `src/Radio.cpp.patch`
for the fix (`MODE_TCXO_1_8V_6X`, matching the Wio-SX1262 module's confirmed 1.8V
reference).

**Caveat:** unlike the TX power fix, this one's actual effect was never independently
isolated and reconfirmed in a controlled way -- it was applied around the same time as
other changes, and by the time the radio was confirmed fully working, several fixes were
in place together. It's very likely still worth keeping (an unconfigured TCXO reference
is a real correctness issue for frequency accuracy on its own), but don't cite it as a
confirmed fix for any *specific* symptom without re-testing it in isolation.

---

## Part 7 — The radio wouldn't turn on under RNS (but `rnodeconf` didn't catch it)

Even after the TX power fix, Sideband/RNS still failed with `"Radio state mismatch"` --
a different, more fundamental check than the individual-parameter validation TX power
had been tripping. `rnodeconf`'s own TNC-mode tests, by contrast, appeared to succeed.

### Why `rnodeconf` didn't catch this

`rnodeconf.py` and RNS's `RNodeInterface.py` are two entirely separate implementations of
the serial protocol -- `rnodeconf` doesn't reuse `RNodeInterface` at all, and applies
different (weaker) success criteria. This was a genuine trap during debugging: several
rounds of testing via `rnodeconf` looked successful and seemed to rule out a real
firmware-level problem, when the actual issue only showed up under `RNodeInterface`'s
stricter validation (`RNodeInterface.validateRadioState()` explicitly requires a real,
confirmed `r_state` echo from the device matching what was requested -- see
`RNS/Interfaces/RNodeInterface.py`).

### Isolating the real cause with raw KISS commands

Rather than keep guessing from two different tools' differing behavior, a small raw
KISS-protocol test script (`toolchain/kiss-debug-scripts/raw_initradio_test.py`) was
used to replicate RNS's exact `initRadio()` command sequence directly over the serial
port and observe raw byte-level responses. This ruled out, in order:

1. **Mode gating** (`op_mode == MODE_HOST`) -- ruled out because frequency/bandwidth/SF/
   CR all correctly applied and echoed back despite sharing the identical gating pattern
   with TX power; if mode gating were blocking commands, all of them should have failed
   identically.
2. **Radio lock** (`CMD_RADIO_LOCK` queried directly) -- confirmed unlocked (`0x00`) both
   before and after requesting radio state ON, with all parameters correctly set.
3. **Firmware-level command dispatch bugs** -- ruled out once the test script's own
   initial KISS-escaping bug was fixed (an early version didn't escape a `0xC0` byte that
   happened to appear inside the frequency value, corrupting that one command -- a good
   reminder that hand-rolled protocol tests need to implement escaping correctly too, not
   just the firmware).

With those ruled out, the remaining candidate in `startRadio()`'s gating logic was
`hw_ready`, which traced to `device_init()` in `Device.h`:

```cpp
bool device_init() {
  #if VALIDATE_FIRMWARE
  if (bt_ready) {
    ...
    return device_init_done && fw_signature_validated;
  } else {
    return false;
  }
```

`VALIDATE_FIRMWARE` defaults to `true` (`Boards.h`) and was never overridden for this
board. `fw_signature_validated` requires a live-computed hash of the running firmware to
match a host-provided target hash (`dev_firmware_hash_target`, set via `rnodeconf
--firmware-hash` / the web flasher's "Set Firmware Hash" button) -- a step that had been
documented as necessary earlier in this process but never actually performed.

### The actual root cause: a hardcoded, wrong flash address

Attempting to set the firmware hash (`./partition_hashes from_device <port>`) returned
`e3b0c442...b855` -- which is exactly `SHA256("")`, the hash of zero bytes. The firmware
computes this hash over a region of flash defined by two constants in `Device.h`:

```cpp
#define APPLICATION_START 0x26000
#define IMG_SIZE_START 0xFF008
```

`APPLICATION_START` is hardcoded and unconditional, no per-board override. `0x26000` is
the *old* S140 v6 application start address -- exactly what Part 3 of this document
already established is wrong for this board (our real start is `0x27000`, per the linker
script fix). Every *other* nRF52 board in this codebase uses S140 v6 and genuinely does
start at `0x26000`, which is why this was never wrong until now -- this board is the
first in the codebase using S140 v7's differently-sized reserved region.

Reading the actual flash contents at `IMG_SIZE_START` directly via SWD/OpenOCD confirmed
this precisely:
```
mdw 0xFF008 4
0x000ff008: 00000000 00000000 00000000 00000000
```
Genuinely all zeros -- not `0xFF` (which is what erased-but-unwritten NOR flash normally
reads as), meaning this isn't just "unpopulated," but specifically not what this firmware
code expects to find there. `retrieve_application_size()` reads this location expecting a
bootloader-populated application-size field (a common pattern for Adafruit-style nRF52
bootloaders), and gets `0`, which is why the hash comes out as `SHA256("")` -- the hash
loop runs zero iterations. This most likely reflects a genuine layout or field difference
between Seeed's downstream bootloader build (`v0.6.2`) and whatever bootloader-settings-
page convention this firmware code was originally written against, though this wasn't
independently confirmed beyond ruling out the simpler "wrong start address only" theory.

### The fix applied here, and the tradeoff it represents

Rather than reverse-engineer the exact correct bootloader-settings-page layout (real,
open-ended work with no guaranteed answer), `VALIDATE_FIRMWARE` was disabled for this
board specifically:

```cpp
#define VALIDATE_FIRMWARE false
```

**This is a genuine security tradeoff, not a cosmetic fix.** `VALIDATE_FIRMWARE`/
`fw_signature_validated` exists to verify the running firmware hasn't been tampered with
since it was flashed. Disabling it means this device can no longer detect that on its
own. For a device that's built, flashed, and used entirely by one person, this is a
defensible tradeoff -- but it should be flagged prominently, not carried forward quietly,
in any future review or upstream discussion. The two real paths forward, in order of
effort:
1. **(applied here)** Disable `VALIDATE_FIRMWARE` for this board -- fast, unblocks
   everything, but gives up firmware integrity verification.
2. **(not attempted)** Determine the actual bootloader-settings-page layout Seeed's
   `v0.6.2` bootloader uses and provide correct board-specific values for
   `APPLICATION_START`/`IMG_SIZE_START` -- the "real" fix, but open-ended.

With this fix applied, `hw_ready` becomes reachable, and the radio turns on and reports
real state correctly -- confirmed via the raw KISS test script (`RADIO_STATE=ON` now
returns `01`) and via a live RNS/Sideband session (see Part 8).

---

## Part 8 — Using the device as a real Reticulum interface

Once provisioned (Part 5) and with the TX power and radio-enable fixes applied (Parts 6
and 7), the device works as a standard `RNodeInterface` in a normal Reticulum config.

Example `~/.reticulum/config` interface block:
```
[[RNode LoRa Interface]]
  type = RNodeInterface
  enabled = Yes
  port = /dev/cu.usbmodemXXXX
  frequency = 915000000
  bandwidth = 125000
  txpower = 7
  spreadingfactor = 8
  codingrate = 7
```

Nothing in this config is Wio-Tracker-specific -- any config within the board's confirmed
capabilities (820-1020 MHz, up to 22 dBm) should work identically to any other RNode once
the firmware-side fixes above are in place.

**Do not use `rnodeconf --autoinstall` or its guided device-type menu** when working with
this device -- both assume a known, listed board and will offer to flash a generic stock
firmware image for whatever board is selected, silently overwriting this custom build.

**Confirmed working**, via Sideband's Reticulum Status view:
```
RNodeInterface[RNode LoRa Interface]
    Status    : Up
    Mode      : Full
    Rate      : 2.23 kbps
    Noise Fl. : -104 dBm, no interference
    Traffic   : tx 219 B      0 bps
                rx 0 B        0 bps
```
The noise-floor reading in particular is a genuine live RF measurement from the SX1262's
receiver, not just a reported "on" status -- confirming the radio is actually listening,
not merely claiming to be. Real two-node TX/RX has not yet been separately tested (see
Part 10).

---

## Part 9 — Fixing the OLED display

With `HAS_DISPLAY false` (disabled since Part 4, when a live-hanging I2C transaction was
one of several suspects during the SoftDevice investigation), the display was re-enabled
and switched from `Adafruit_SSD1306` to `Adafruit_SH1106G` (from the `Adafruit_SH110X`
library), matching the SH1106 controller Zephyr's official board docs describe for this
panel. `Display.h` already had a working `MONO_OLED` code path (used by T-Beam Supreme),
so most of the change was extending T-Beam Supreme's existing conditions with `||
BOARD_MODEL == BOARD_WIO_TRACKER_L1` at each relevant call site (object declaration,
`set_contrast()` overload, the `begin()` call) plus a new pin-override block. Three
separate, independent bugs surfaced once this was actually tested on hardware.

### Bug 1 — wrong I2C address

The display never initialized (`display_init()` returned `false`). A minimal I2C bus
scanner, added temporarily in `setup()` right after `Serial.begin()`, found the panel
responding at `0x3D`, not the more common `0x3C` used as the initial guess:

```cpp
Serial.println("Starting I2C scan...");
Wire.setPins(6, 5); // SDA, SCL
Wire.begin();
for (uint8_t addr = 1; addr < 127; addr++) {
  Wire.beginTransmission(addr);
  if (Wire.endTransmission() == 0) {
    Serial.print("Found device at address 0x");
    Serial.println(addr, HEX);
  }
}
```

Fix: `DISP_ADDR` for `BOARD_WIO_TRACKER_L1` in `Display.h`'s pin-override block set to
`0x3D`.

### Bug 2 — nRF52's `TwoWire` doesn't support ESP32-style `Wire.begin(sda, scl)`

With the address fixed, the display initialized but the *build itself* started failing:
`error: no matching function for call to 'TwoWire::begin(int, int)'`. The `Wire.begin(SDA_OLED,
SCL_OLED)` call combined into T-Beam Supreme's existing condition works on T-Beam Supreme
specifically because it's an **ESP32** board -- ESP32's Arduino core `TwoWire::begin()`
accepts pin arguments directly, as a platform convenience. nRF52's `TwoWire` (this
core's `libraries/Wire/Wire.h`) has no such overload; pins are set via a separate method
first:

```cpp
class TwoWire : public Stream {
  public:
    void begin();
    void begin(uint8_t);   // address, for slave mode -- not what we want
    void setPins(uint8_t pinSDA, uint8_t pinSCL);
    ...
```

Fix: split `BOARD_WIO_TRACKER_L1` out of the combined condition with `BOARD_TBEAM_S_V1`
in `display_init()`, using the correct nRF52-specific two-call sequence:

```cpp
    #elif BOARD_MODEL == BOARD_WIO_TRACKER_L1
      Wire.setPins(SDA_OLED, SCL_OLED);
      Wire.begin();
```

No existing nRF52 board in this codebase drives an I2C OLED display, so there was no
working precedent for this specific platform/peripheral combination to copy from --
worth remembering when porting a new nRF52 board with an I2C display in the future.

### Bug 3 — the KISS-framing red herring, and how it was resolved

With both of the above fixed, the display showed the boot splash ("device starting")
but never advanced, for what appeared to be a very long time (tens of seconds). A first
attempt to read boot output over serial (`python3 -m serial.tools.miniterm`) kept
crashing with `OSError: [Errno 6] Device not configured` -- caused by resets on this
board dropping and re-enumerating the USB CDC connection, the same as a physical
unplug. A small reconnecting logger script fixed the connection-drop problem, but
consistently showed only a single, garbled character (`"U"`) before falling silent.

This looked exactly like a hang, and an extensive OpenOCD-based investigation followed
(SVD register captures, `PendSV`/`EXC_RETURN` decoding, `addr2line` tracing through
`tud_cdc_n_write_flush` in TinyUSB) before two things were discovered that invalidated
most of it:

1. **The `.uf2` conversion step had been silently skipped** for several iterations --
   `arduino-cli compile` followed directly by `cp ...uf2 /Volumes/XIAO-BOOT/`, with no
   `uf2conv.py` call in between, meaning a stale binary was being tested (or flashing was
   silently failing) while genuinely new source changes went untested. Several rounds of
   OpenOCD register captures were taken against this stale/uncertain state.
2. **Once a verified-fresh build was actually flashed and traced, the MCU was
   completely healthy** -- repeated `halt`/`resume`/`halt` cycles showed the program
   counter moving normally through different functions each time, not stuck anywhere.

That redirected attention to the actual `"U"` output itself. A raw hex logger (logging
`bytes.hex()` instead of decoded text) revealed the real content: `c0 55 f8 c0` --
`FEND, 0x55, 0xF8, FEND` in KISS framing, a complete and valid `kiss_indicate_reset()`
frame. `0xC0` (`FEND`) and `0xF8` are non-printable bytes that a terminal renders as
blank boxes and that plain-text copy-paste silently drops; `0x55` happens to be the
ASCII byte for `'U'`. **There was no hang at all** -- this was valid protocol output the
entire time, misread as corruption because it was being viewed through a text-decoding
tool instead of a raw byte view.

**Lesson for future debugging on this firmware:** always log raw hex when reading serial
output from a KISS/binary protocol device, never decoded text -- printable-looking
fragments surrounded by silence are a strong signal of exactly this trap, not evidence of
a hang. `toolchain/kiss-debug-scripts/serial_hexlog.py` in this repo implements this.

### The actual remaining bug

With the "hang" ruled out and `rnodeconf -i` confirming the device was fully valid
(checksum correct, signature validated, `Device mode: Normal (host-controlled)`) even
while the screen stayed frozen, the real cause turned out to be much simpler and
entirely unrelated to any of the above: `loop()`'s periodic display-refresh condition
had never been updated for `MONO_OLED` boards at all:

```cpp
  #if HAS_DISPLAY
    #if DISPLAY == OLED || DISPLAY == TFT || DISPLAY == ADAFRUIT_TFT
    if (disp_ready) update_display();
```

This condition predates any `MONO_OLED` board using periodic (non-e-ink) refresh --
T-Beam Supreme, the only prior `MONO_OLED` board, was never checked against this
specific line. Without `MONO_OLED` included, `update_display()` runs exactly once (the
one-time call in `setup()`, which draws the boot splash) and then never again --
producing a display that looks frozen indefinitely, regardless of what `hw_ready`/
`device_init_done` become afterward. This has nothing to do with hangs, USB, or KISS
framing; it's simply a screen nobody ever tells to redraw again.

Fix:
```cpp
    #if DISPLAY == OLED || DISPLAY == TFT || DISPLAY == ADAFRUIT_TFT || DISPLAY == MONO_OLED
    if (disp_ready) update_display();
```

With all three fixes in place, the display correctly shows live status and updates
continuously, matching every other supported board.

---

## Part 10 — Open questions / unverified assumptions

- **OLED display: fixed, see Part 9.** No longer an open question -- kept here only as
  a pointer since earlier parts of this document (Part 4 in particular) still describe it
  as disabled/hanging, which was true at the time but is now resolved.
- **`NRF_SPIM3` for the radio SPI** — chosen by elimination (SPIM0/1 claimed by the two
  I2C buses), and now confirmed working via a fully functional radio. `NRF_SPIM2` was
  never needed.
- **`HAS_CONSOLE false`** — set to match every other nRF52 board in this codebase.
  Not independently reconsidered given the board's relatively generous 2MB QSPI flash
  (unused by RNode firmware currently) — worth revisiting once other work is further
  along, low priority.
- **GPS (L76K) is entirely unimplemented.** The schematic shows GPS UART/reset/wakeup
  pins, and `BOARD_HELTEC_T114`'s `MODEL_CB` variant shows precedent for `HAS_GPS` in
  this codebase, but this hasn't been attempted here.
- **Real two-node over-the-air TX/RX has not been separately confirmed.** The radio is
  confirmed live and receiving (real -104 dBm noise-floor reading via a working RNS
  interface, Part 8), and TX power is confirmed correctly applied (Part 6), but an actual
  transmission received by a second node (or checked against an SDR) would be the next
  real confirmation that TX is fully functional end to end, not just correctly configured.
- **Device signature trust** — the device is provisioned and self-signed with a locally
  generated key (via the web flasher's initial provisioning attempt, later fully
  completed via `rnodeconf`'s own bootstrap). `rnodeconf` on *other* machines will show
  the "device signature validation failed" warning unless that signing key (or a trusted
  public key derived from it) is present. This is expected/correct behavior for a
  self-provisioned homebrew device, not a defect — see `rnodeconf --help`'s `-P`/
  `--trust-key` flags if resolving this for cross-machine trust is ever wanted.
- **This toolchain setup is fragile and non-reproducible via standard tooling.** The
  hybrid Arduino board definition (Part 3) and the `rnodeconf` patches (Part 5) both live
  in hand-edited files outside this repo — inside the installed Arduino package directory
  and the installed `rns` Python package, respectively — and will be wiped out by a core
  reinstall/update or a `pip install --upgrade rns`. The `toolchain/setup.sh` and
  `toolchain/patch_rnodeconf.py` scripts in this repo exist specifically to make
  reapplying both fast when that happens. If this ever needs to go upstream, the real
  fixes are: getting a proper nRF52840 + S140 v7 + raw-pin-passthrough variant into a
  public Arduino board index, and getting the `rnodeconf` write-timing/display bugs fixed
  in the actual Reticulum project (the timing issue in particular seems like it could
  affect any board using flash-emulated EEPROM, not just this one).
- **The exact cause of `IMG_SIZE_START` reading zero (Part 7) was never fully confirmed**
  beyond ruling out the simpler "just a wrong start address" explanation. Whether this is
  a genuine bootloader-settings-page layout difference in Seeed's `v0.6.2` build, a
  different field at that offset entirely, or something else, wasn't determined. Anyone
  picking this up should treat "disable `VALIDATE_FIRMWARE`" as the known-working but
  non-ideal fix, not as evidence the deeper question has been answered.

---

## Part 11 — Prioritized list for upstream contribution

Everything below is grouped by how likely it is to be a genuine, board-agnostic
improvement to `RNode_Firmware_CE` itself, versus something specific to bringing up a new,
non-standard board -- worth keeping this distinction clear in any future review or PR
discussion, per `CONTRIBUTING.md`'s requirement that all contributions be hand-written and
independently verified, not just lifted from this document.

**High confidence, board-agnostic bug fixes -- likely worth a PR on their own, independent
of whether Wio Tracker L1 Pro support itself ever goes upstream:**
- The `setTXPower()` model-table gap (Part 6). A real bug affecting any future board
  added without remembering to add itself to that specific list; the maintainer's own
  TODO comment acknowledges the function needs revamping. Smallest, cleanest, most
  self-contained fix in this whole session.
- The `while (!Serial)` boot-wait exclusion (Part 2.3B) is a one-line addition to an
  existing pattern already applied to every other nRF52 board -- low-risk, easy to
  verify, though it only matters for a board that isn't already on that list.

**Real board-support contribution, but needs a design decision from a maintainer, not just
a bug fix -- the `VALIDATE_FIRMWARE`/`APPLICATION_START` question (Part 7):**
- Whether the "right" fix is board-specific `APPLICATION_START`/`IMG_SIZE_START` values
  (if the actual bootloader-settings-page layout can be determined), or an explicit,
  documented opt-out mechanism for boards with non-standard bootloaders, is a real open
  design question -- not something to resolve unilaterally in a PR without discussion.

**Genuinely specific to this board (or to the toolchain gap around it), not upstream
material for the firmware repo itself:**
- The pin mapping, SPI/TCXO/DIO2 configuration (Parts 1-2).
- The entire hybrid Arduino board definition (Part 3) -- the real fix here belongs in a
  public Arduino board index (Seeed's own, ideally), not in `RNode_Firmware_CE` itself.
- The SoftDevice/bootloader mismatch and its SWD-based diagnosis (Part 4) -- specific to
  whatever this individual unit's history was; worth writing up as a general debugging
  technique/reference (this README already does that) more than as firmware code.
- The `rnodeconf` write-timing and display-crash bugs (Part 5) -- genuine bugs, but in
  the separate Reticulum/`rnodeconf` project, not `RNode_Firmware_CE`.

**Not yet attempted, needed before Wio Tracker L1 Pro support could reasonably be
considered complete enough for a board-support PR:**
- GPS support.
- Confirmed two-node TX/RX.

(OLED display support is now complete -- see Part 9 -- and no longer belongs in this list.)
