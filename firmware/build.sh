#!/bin/bash
# Builds Desk Pal's firmware: MicroPython v1.29.0 + the `wake` module (ESP-SR MultiNet7 English),
# plus srmodels.bin for the "model" partition. Output lands in ~/esp/deskpal/out.
#
# Needs: ESP-IDF v5.5.2 at ~/esp/esp-idf (./install.sh esp32s3) and
#        git clone -b v1.29.0 --depth 1 https://github.com/micropython/micropython ~/esp/micropython
# This repo lives under a path with a colon (s:w), which make/cmake can't handle, so the board and
# module are copied to ~/esp/deskpal first.
#
# First flash, or after a partition table change (board in download mode: hold BOOT while powering
# on; this wipes the filesystem, so back up board files first; the watchdog reset leaves download
# mode, an RTS reset doesn't):
#   esptool --chip esp32s3 write-flash 0 ~/esp/deskpal/out/firmware.bin 0x620000 ~/esp/deskpal/out/srmodels.bin
#   esptool --chip esp32s3 --before no-reset --after watchdog-reset erase-region 0x8F0000 0x2000
# App-only updates after that: python3 firmware/ota.py (over USB, no button).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE="$HOME/esp/deskpal"
MPY="$HOME/esp/micropython"
PORT="$MPY/ports/esp32"
ESP_SR_VERSION="2.5.5"

rm -rf "$STAGE"
mkdir -p "$STAGE/out"
cp -R "$HERE/board" "$HERE/wake" "$STAGE/"
# sdkconfig is only generated from the defaults once; start over when the board config changed.
if ! cmp -s "$STAGE/board/sdkconfig.board" "$PORT/build-DESKPAL/sdkconfig.board.used"; then
    rm -f "$PORT/build-DESKPAL/sdkconfig"
fi
cp "$HERE/board/partitions-deskpal.csv" "$PORT/"

# Fixes to MicroPython itself (applied once; see each patch's comments).
for p in "$HERE"/patches/*.patch; do
    git -C "$MPY" apply --reverse --check "$p" 2>/dev/null || git -C "$MPY" apply "$p"
done

# ESP-SR as a managed component of MicroPython's main component (added once).
if ! grep -q "espressif/esp-sr" "$PORT/main/idf_component.yml"; then
    perl -0pi -e "s/^dependencies:\n/dependencies:\n  espressif\/esp-sr: \"$ESP_SR_VERSION\"\n/m" "$PORT/main/idf_component.yml"
fi

source "$HOME/esp/esp-idf/export.sh" > /dev/null
ARGS=(BOARD=DESKPAL BOARD_DIR="$STAGE/board" USER_C_MODULES="$STAGE/wake/micropython.cmake")
make -C "$MPY/mpy-cross"
make -C "$PORT" "${ARGS[@]}" submodules
make -C "$PORT" "${ARGS[@]}" -j8
cp "$STAGE/board/sdkconfig.board" "$PORT/build-DESKPAL/sdkconfig.board.used"

cp "$PORT/build-DESKPAL/firmware.bin" "$PORT/build-DESKPAL/micropython.bin" "$STAGE/out/"
cp "$PORT/build-DESKPAL/srmodels/srmodels.bin" "$STAGE/out/"
ls -l "$STAGE/out"
