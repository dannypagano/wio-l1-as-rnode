# Wio Tracker L1 Pro — RNode Firmware CE Board Support (Working Draft)

This document records, step by step, how to reproduce a working `RNode_Firmware_CE` build
for the Seeed Studio Wio Tracker L1 Pro (nRF52840 + Wio-SX1262 + L76K GPS), starting from
an unmodified clone of [`liberatedsystems/RNode_Firmware_CE`](https://github.com/liberatedsystems/RNode_Firmware_CE).

**Repo layout:**
```
README.md              -- this file
src/Boards.h            -- full file, drop-in replacement for RNode_Firmware_CE's Boards.h
src/Utilities.h         -- full file, drop-in replacement for RNode_Firmware_CE's Utilities.h
src/RNode_Firmware_CE.ino -- full file, drop-in replacement for RNode_Firmware_CE's .ino
src/Makefile.additions  -- snippet to append to RNode_Firmware_CE's Makefile
toolchain/setup.sh      -- reproduces the hybrid board definition described in Part 3
```

To use: clone `RNode_Firmware_CE` separately, copy the three files from `src/` over the
matching files in that clone, append `src/Makefile.additions` to its `Makefile`, then run
`toolchain/setup.sh` once before compiling.

**Status:** the board boots and executes application code (confirmed via LED test). Radio
(SX1262) initialization and `rnodeconf` provisioning have not yet been verified. Several
pin-mapping and peripheral assumptions below are derived from schematic inspection and
cross-referencing similar boards, not from official documentation — see the "Open
questions / unverified assumptions" section at the end.

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
- Display: OLED, physically present on this board (1.3", likely SH1106 controller per
  Zephyr's official board docs — see open questions)
- Flash: external QSPI (not used by RNode firmware on this build; EEPROM emulation uses
  internal flash instead)
- Factory bootloader: **not** the "native" bootloader Zephyr's documentation describes.
  This specific unit's bootloader was reflashed by Seeed support with a **Seeed XIAO
  nRF52840** bootloader (`Board-ID: nRF52840-SeeedXiao-v1`, `SoftDevice: S140 7.3.0`).
  This detail turned out to be load-bearing for the whole toolchain setup below.

---

## Part 1 — Pin mapping reference

Derived from Seeed's official schematic PDF (`Wio_Tracker_L1_Pro_SCH_PDF.pdf`) and
cross-confirmed against Zephyr's official `wio_tracker_l1` board devicetree
(https://docs.zephyrproject.org/latest/boards/seeed/wio_tracker_l1/doc/index.html), which
matched the schematic net names exactly.

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

**Radio switch config:** Zephyr's docs state the RF switch is "driven by DIO2 plus a
separate LNA-enable line on P1.08" — i.e. `DIO2_AS_RF_SWITCH = true`, and P1.08 is
`pin_rxen`, not `pin_txen`. This corrected an earlier wrong assumption (see commit
history / conversation log if kept).

**TCXO:** confirmed via an unrelated Meshtastic debug log for the same Wio-SX1262 module
showing `SX126X_DIO3_TCXO_VOLTAGE` configured at 1.8V. So `HAS_TCXO = true`,
`pin_tcxo_enable = -1` (handled internally by the module, no host GPIO).

**Arduino pin numbering convention:** confirmed by inspecting
`g_ADigitalPinMap` in Adafruit's `pca10056` variant — Arduino pin N maps directly to raw
nRF52 pin N (i.e. `P1.xx` = `32 + xx`). **This is only true for board variants using raw
passthrough numbering** — see Part 3, this was a major source of confusion.

---

## Part 2 — Firmware source changes

Three files needed changes. All BOARD_MODEL/PRODUCT/MODEL codes were chosen to avoid
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
        true   // DIO2_AS_RF_SWITCH -- confirmed via Zephyr board docs
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
        40, // pin_rxen (P1.08, LNA/RX-enable per Zephyr docs)
        -1  // pin_tcxo_enable (internal to module)
    }};

#define I2C_SDA 6 // OLED_I2C_SDA
#define I2C_SCL 5 // OLED_I2C_SCL
const int pin_btn_usr1 = 8;  // Menu_Key
const int pin_led_rx = 33;   // Mesh_LED, P1.01
const int pin_led_tx = 33;   // Mesh_LED, P1.01 (shared, single LED on board)
```

### 2.2 — `Utilities.h`

Three additions were needed here — none of these are obvious from `Boards.h` alone; each
was found by hitting a compile error or a silent runtime failure.

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

The global `interface_spi[1]` SPI object needs board-specific construction on nRF52 (the
Adafruit-derived `SPIClass` has no default/zero-argument constructor — each nRF52840
SPIM hardware peripheral instance must be nominated explicitly, since SPIM and TWIM
share underlying hardware per instance number). Added as a new arm in the existing
`#if MCU_VARIANT == MCU_NRF52` / `#if BOARD_MODEL == ...` chain near the top of the file
(after the `BOARD_HELTEC_T114` arm):

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

`NRF_SPIM3` was chosen because SPIM0 and SPIM1 are already claimed by this board's two
I2C buses (OLED on TWIM0, Grove connector on TWIM1) — SPIM/TWIM share hardware per
instance number on the nRF52840, so those two instances were ruled out. Not independently
confirmed against a datasheet; if the radio never initializes, `NRF_SPIM2` is the next
thing to try.

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

## Part 3 — Toolchain setup (the hard part)

This is the part that isn't visible in the source diffs above, and cost the most time.
The short version: **no single stock Arduino board package works correctly for this
board**, because two independent requirements point at two different, incompatible
packages.

### The problem, in order of discovery

1. **Started with `adafruit:nrf52:pca10056`** (Nordic's own nRF52840 DK target) as the
   closest available generic nRF52840 core. Got the firmware compiling, but the flashed
   device never booted — no serial port, no LED, total silence, even with a maximally
   stripped debug build (`pinMode`/`digitalWrite`/`delay` as the literal first lines of
   `setup()`).

2. **Root cause: SoftDevice version mismatch.** This board's bootloader (as read from its
   `INFO_UF2.TXT`) requires `SoftDevice: S140 7.3.0`. The Adafruit core installed
   (`adafruit:nrf52@1.7.0`) only ships an `nrf52840_s140_v6.ld` linker script for the
   nRF52840 — no v7 linker script exists for that chip in that core release (only for
   nRF52833 boards). Compiling against the wrong SoftDevice ABI/vector table causes a
   hard fault before `setup()` — before even global constructors finish, in this case.

3. **Switched to `Seeeduino:nrf52:xiaonRF52840`** (Seeed's own nRF52 Arduino core,
   installed via board manager URL
   `https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json`). This
   package does ship `nrf52840_s140_v7.ld` and matching bootloader/SoftDevice files,
   confirmed by the linker placing the app at `0x27000` instead of `0x26000` (a ~4KB
   shift consistent with S140 v7 reserving slightly more flash than v6). Compiled clean.
   Flashed. Still no boot.

4. **Root cause #2: pin mapping.** The `Seeed_XIAO_nRF52840` variant this FQBN uses does
   **not** use raw pin passthrough. Its `g_ADigitalPinMap` is a short, curated,
   reordered table mapping ~30 indices to Seeed's actual XIAO dev-board silkscreen
   labels (D0–D10, onboard LEDs, IMU, mic, QSPI flash) — completely unrelated to our
   custom board's wiring. Every pin constant in `Boards.h`/`Utilities.h`/`.ino`, which
   assumed raw passthrough, was silently wrong under this variant.

5. **Fix: hybrid board definition.** Neither package alone has both (a) the correct
   S140 v7 linker/SoftDevice and (b) raw pin-passthrough numbering. Built a custom board
   entry inside the Seeeduino package that reuses Adafruit's `pca10056` variant files
   (for correct raw-passthrough pins) but keeps Seeeduino's linker/bootloader/SoftDevice
   settings (for the correct S140 version). This finally produced a booting device.

### Reproduction steps

**1. Install both board packages:**

```bash
# Adafruit core (source of the raw pin-passthrough variant files)
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json

# Seeeduino core (source of the correct S140 v7 linker/SoftDevice)
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

(Adjust version numbers/paths to whatever `arduino-cli core list` reports — these were
current as of this writing but will drift.)

**3. Append a new board entry to the Seeeduino package's `boards.txt`:**

```bash
cat >> /path/to/packages/Seeeduino/hardware/nrf52/1.1.13/boards.txt << 'EOF'

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
EOF
```

Note `build.board=Seeed_XIAO_nRF52840` — this is **not** cosmetic. At least one bundled
library (`Wire_nRF52.cpp`) has a hardcoded `#if defined(ARDUINO_<board>)` check with an
`#error "Unsupported board"` fallback. Setting `build.board` to a name that library
already recognizes was the path of least resistance; a truly custom board name would
require patching every library with a similar check (there may be more we haven't hit
yet — this was only confirmed for `Wire_nRF52.cpp`).

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
factory-installed (working) Meshtastic firmware that was on the device before we started
(the first 4 bytes, `0x2886`, match Seeed's registered USB Vendor ID — this appears to be
a deliberate VID-derived scheme, not arbitrary):

```bash
python3 /path/to/packages/Seeeduino/hardware/nrf52/1.1.13/tools/uf2conv/uf2conv.py \
  -c -f 0x28860044 \
  -o build/Seeeduino.nrf52.wioTrackerL1/RNode_Firmware_CE.ino.uf2 \
  build/Seeeduino.nrf52.wioTrackerL1/RNode_Firmware_CE.ino.hex
```

Sanity check: this should report `start address: 0x27000`. If it reports `0x26000`
you're accidentally still linked against v6 — check `build.ldscript` in the board entry.

**7. Flash it.** Enter bootloader mode by **holding** (not double-tapping) the reset
button — this specific bootloader responds to press-and-hold, not the double-tap gesture
described in Zephyr's generic documentation. Then:

```bash
cp build/Seeeduino.nrf52.wioTrackerL1/RNode_Firmware_CE.ino.uf2 /Volumes/XIAO-BOOT/
```

Use `cp` from a terminal, not Finder/Explorer drag-and-drop — Finder has thrown spurious
"Error code -36" failures against this bootloader's FAT volume on macOS.

---

## Open questions / unverified assumptions

Listed roughly in order of how likely each is to bite next:

- **`NRF_SPIM3` for the radio SPI** — chosen by elimination (SPIM0/1 are claimed by the
  two I2C buses) but not confirmed against a datasheet or working radio test. If the
  radio never initializes despite everything else working, try `NRF_SPIM2`.
- **LED polarity** (`HIGH` = on) — confirmed correct empirically (the LED does light).
- **OLED controller: SSD1306 vs SH1106.** The firmware links `Adafruit_SSD1306`, but
  Zephyr's official hardware description for this exact board states the panel is an
  **SH1106** controller — a different, incompatible init/command sequence despite
  identical form factor and I2C protocol layer. Not yet tested; if the board boots fully
  but the display stays dark while everything else works, this is the first place to
  look.
- **`HAS_CONSOLE false`** — set to match every other nRF52 board in this codebase, on
  the assumption that the bootstrap-console feature needs more flash than these boards
  comfortably spare. Not independently verified for this board's actual QSPI flash
  capacity (2MB per the schematic, which is more generous than most nRF52 boards here —
  worth reconsidering once the radio path is confirmed working).
- **GPS (L76K) is entirely unimplemented.** The schematic shows GPS UART/reset/wakeup
  pins, and `BOARD_HELTEC_T114`'s `MODEL_CB` variant shows precedent for `HAS_GPS` in
  this codebase, but this hasn't been attempted here.
- **Radio has not been tested at all** — everything above only confirms the MCU boots
  and runs application code. SX1262 `preInit()`, `rnodeconf` provisioning, and actual
  TX/RX are all still open.
- **This toolchain setup is fragile and non-reproducible via standard tooling.** The
  hybrid board definition lives entirely in hand-edited files inside the installed
  Arduino package directory, not in version control, and will be wiped out by any core
  reinstall/update. If this ever needs to go upstream, the real fix is getting a proper
  nRF52840 + S140 v7 + raw-pin-passthrough variant into a public board index — either by
  raising it with Seeed, or building a genuinely custom Arduino core package that ships
  its own variant/boards.txt/linker files rather than depending on splicing two existing
  packages together by hand.
