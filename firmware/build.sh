#!/bin/bash
# Builds Desk Pal's firmware: MicroPython v1.29.0 + the `wake` module (ESP-SR MultiNet7 English),
# plus srmodels.bin for the "model" partition. Output lands in ~/esp/deskpal/out.
#
# Needs: ESP-IDF v5.5.2 at ~/esp/esp-idf (./install.sh esp32s3) and
#        git clone -b v1.29.0 --depth 1 https://github.com/micropython/micropython ~/esp/micropython
# This repo lives under a path with a colon (s:w), which make/cmake can't handle, so the board and
# module are copied to ~/esp/deskpal first.
#
# Flash (board in download mode; this wipes the filesystem, so back up board files first):
#   esptool --chip esp32s3 write-flash 0 ~/esp/deskpal/out/firmware.bin 0x400000 ~/esp/deskpal/out/srmodels.bin
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

cp "$PORT/build-DESKPAL/firmware.bin" "$STAGE/out/"
cp "$PORT/build-DESKPAL/srmodels/srmodels.bin" "$STAGE/out/"
ls -l "$STAGE/out"
