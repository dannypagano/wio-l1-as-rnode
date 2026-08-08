#!/usr/bin/env python3
"""
Patches a local rnodeconf.py install to work reliably with the Wio Tracker L1 Pro
(and likely any other board using flash-emulated, rather than hardware, EEPROM).
See README.md Part 5 for the full explanation of each bug.

Fixes applied:
  1. Bumps the hardcoded 6ms inter-byte EEPROM write delay to 150ms. The original
     delay assumes fast hardware EEPROM; this board's EEPROM is emulated via
     LittleFS on internal flash, and writes at the faster pace silently lose
     bytes partway through the (128-byte) signature block.
  2. Wraps an unguarded `models[rnode.model][4]` dict lookup (used during
     `rnodeconf -i`) in try/except, so custom/unlisted model codes don't crash
     the tool with an unhandled KeyError.
  3. Replaces three more unguarded lookups (`products[rnode.product]`,
     `models[rnode.model][3]`, `models[rnode.model][5]`) used in the "Device
     info:" printout with safe fallback expressions, for the same reason.

None of these patches touch EEPROM validation logic or checksums -- they only
affect write pacing and cosmetic display code. A device provisioned with the
timing fix produces a fully valid, checksummed, signed EEPROM exactly as
rnodeconf intends.

This patch lives in your local Python environment, not in firmware or in this
repo's own tracked code. It will be undone by reinstalling or upgrading the
`rns` package (`pip install --upgrade rns`), and will need to be reapplied.

Usage:
    python3 patch_rnodeconf.py /path/to/site-packages/RNS/Utilities/rnodeconf.py

Find your path first with:
    python3 -c "import os, RNS; print(os.path.join(os.path.dirname(RNS.__file__), 'Utilities', 'rnodeconf.py'))"
"""

import sys
import shutil


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]

    backup_path = path + ".bak"
    print(f"Backing up {path} -> {backup_path}")
    shutil.copy2(path, backup_path)

    with open(path) as f:
        content = f.read()
    original_content = content

    # --- Fix 1: write-pacing delay ---
    old_sleep = "time.sleep(0.006)"
    new_sleep = "time.sleep(0.15)"
    count = content.count(old_sleep)
    if count == 0:
        print(f"WARNING: '{old_sleep}' not found -- may already be patched, or "
              f"this rnodeconf version differs. Skipping this fix.")
    else:
        content = content.replace(old_sleep, new_sleep)
        print(f"Fix 1: replaced {count} occurrence(s) of {old_sleep!r} with {new_sleep!r}")

    # --- Fix 2: firmware-filename KeyError during -i ---
    old_fw_lookup = (
        "                if rnode.model != ROM.MODEL_FF:\n"
        "                    fw_filename = models[rnode.model][4]"
    )
    new_fw_lookup = (
        "                if rnode.model != ROM.MODEL_FF:\n"
        "                    try:\n"
        "                        fw_filename = models[rnode.model][4]\n"
        "                    except KeyError:\n"
        "                        fw_filename = \"unknown_model_firmware.zip\""
    )
    count = content.count(old_fw_lookup)
    if count == 0:
        print("WARNING: firmware-filename lookup block not found -- may already be "
              "patched, or this rnodeconf version differs. Skipping this fix.")
    elif count > 1:
        print(f"WARNING: firmware-filename lookup block found {count} times "
              f"(expected 1) -- skipping this fix to avoid an unintended change.")
    else:
        content = content.replace(old_fw_lookup, new_fw_lookup)
        print("Fix 2: guarded firmware-filename lookup with try/except")

    # --- Fix 3: three unguarded lookups in the "Device info:" printout ---
    device_info_fixes = [
        (
            "products[rnode.product]",
            '(products[rnode.product] if rnode.product in products else "Unknown product")',
        ),
        (
            "models[rnode.model][3]",
            '(models[rnode.model][3] if rnode.model in models else "Unknown model")',
        ),
        (
            "models[rnode.model][5]",
            '(models[rnode.model][5] if rnode.model in models else "Unknown modem")',
        ),
    ]
    for old, new in device_info_fixes:
        count = content.count(old)
        if count == 0:
            print(f"WARNING: {old!r} not found -- may already be patched, or this "
                  f"rnodeconf version differs. Skipping this fix.")
        elif count > 1:
            print(f"WARNING: {old!r} found {count} times (expected 1) -- skipping "
                  f"this fix to avoid an unintended change to the wrong occurrence.")
        else:
            content = content.replace(old, new)
            print(f"Fix 3: guarded {old!r} with a safe fallback")

    if content == original_content:
        print("\nNo changes were made. Restoring backup is unnecessary (file untouched).")
        sys.exit(0)

    with open(path, "w") as f:
        f.write(content)

    print(f"\nDone. Patched file written to {path}")
    print(f"Original backed up at {backup_path}")


if __name__ == "__main__":
    main()
