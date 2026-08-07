#!/usr/bin/env bash
# Sets up the hybrid Arduino board definition needed to build RNode_Firmware_CE
# for the Seeed Wio Tracker L1 Pro. See ../README.md Part 3 for the full
# explanation of why this is necessary (short version: no single stock board
# package has both the correct S140 7.3.0 SoftDevice/linker AND raw
# pin-passthrough numbering that this board's actual wiring needs).
#
# Idempotent-ish: safe to re-run, but will overwrite the pca10056_raw variant
# files and append a duplicate boards.txt entry if run twice without cleanup.
# Check boards.txt manually if re-running after a core update.

set -euo pipefail

ARDUINO_DATA_DIR="$(arduino-cli config dump | grep 'data:' -A1 | grep -oE '/[^ ]+/Arduino15' || true)"
if [ -z "$ARDUINO_DATA_DIR" ]; then
  echo "Could not auto-detect Arduino15 data directory. Set ARDUINO_DATA_DIR manually and re-run."
  exit 1
fi
echo "Using Arduino data dir: $ARDUINO_DATA_DIR"

echo "--- Adding board manager URLs ---"
arduino-cli config add board_manager.additional_urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli config add board_manager.additional_urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
arduino-cli core update-index

echo "--- Installing both cores ---"
arduino-cli core install adafruit:nrf52
arduino-cli core install Seeeduino:nrf52

ADAFRUIT_VER=$(arduino-cli core list | awk '/^adafruit:nrf52/{print $2}')
SEEED_VER=$(arduino-cli core list | awk '/^Seeeduino:nrf52/{print $2}')
echo "adafruit:nrf52 version: $ADAFRUIT_VER"
echo "Seeeduino:nrf52 version: $SEEED_VER"

ADAFRUIT_DIR="$ARDUINO_DATA_DIR/packages/adafruit/hardware/nrf52/$ADAFRUIT_VER"
SEEED_DIR="$ARDUINO_DATA_DIR/packages/Seeeduino/hardware/nrf52/$SEEED_VER"

echo "--- Copying raw pin-passthrough variant from Adafruit core into Seeeduino core ---"
mkdir -p "$SEEED_DIR/variants/pca10056_raw"
cp "$ADAFRUIT_DIR/variants/pca10056/variant.cpp" "$SEEED_DIR/variants/pca10056_raw/variant.cpp"
cp "$ADAFRUIT_DIR/variants/pca10056/variant.h" "$SEEED_DIR/variants/pca10056_raw/variant.h"

echo "--- Appending wioTrackerL1 board entry to Seeeduino boards.txt ---"
if grep -q "^wioTrackerL1\." "$SEEED_DIR/boards.txt"; then
  echo "wioTrackerL1 entry already present in boards.txt -- skipping append."
else
  cat >> "$SEEED_DIR/boards.txt" << 'EOF'

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
fi

echo "--- Installing the one missing library dependency ---"
arduino-cli lib install Crypto

echo "--- Verifying the board is now recognized ---"
arduino-cli board listall | grep -i "wio tracker" || {
  echo "WARNING: wioTrackerL1 board not found in listall output. Something went wrong."
  exit 1
}

echo ""
echo "Setup complete. You should now be able to run:"
echo "  arduino-cli compile --log --fqbn Seeeduino:nrf52:wioTrackerL1 -e --build-property \"compiler.cpp.extra_flags=\\\"-DBOARD_MODEL=0x53\\\"\""
echo "from inside your RNode_Firmware_CE clone (with src/Boards.h, src/Utilities.h,"
echo "src/RNode_Firmware_CE.ino copied over the originals)."
