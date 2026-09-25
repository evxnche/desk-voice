# Desk Pal: MicroPython's ESP32_GENERIC_S3 / SPIRAM_OCT settings, plus a 16 MB partition table with
# room for the ESP-SR speech model (sdkconfig.board).
set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    boards/sdkconfig.spiram_quad
    boards/sdkconfig.flash_qio_80m
    boards/sdkconfig.csi
    boards/sdkconfig.240mhz
    boards/sdkconfig.spiram_oct
    ${MICROPY_BOARD_DIR}/sdkconfig.board
)

list(APPEND MICROPY_DEF_BOARD
    MICROPY_HW_BOARD_NAME="Desk Pal (ESP32-S3 + ESP-SR)"
)
