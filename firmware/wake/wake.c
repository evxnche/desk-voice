// `wake`: always-on phrase spotting for Desk Pal. A FreeRTOS task on core 0 reads the ES7210 mic
// on I2S0, resamples 15625 -> 16000 Hz and runs ESP-SR MultiNet7 (English) over it; any phrase
// given to wake.init() works, no training. Python keeps the codec setup (I2C registers, MCLK PWM,
// see board/audio.py), stops the listener before it plays or uses machine.I2S, and polls
// wake.heard(). The raw mic audio also goes into a 16 s ring buffer, so after the wake phrase the
// question is read straight from it (wake.read) with no gap: "gee gee, what's the weather" in one breath.
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "py/runtime.h"
#include "py/mperrno.h"
#include "py/mphal.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/idf_additions.h"  // xTaskCreatePinnedToCore
#include "driver/i2s_std.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "model_path.h"

#define MIC_RATE    15625   // MCLK is PWM at 4 MHz = 256 x 15625 (MicroPython's I2S has no MCLK out)
#define PIN_BCLK    9
#define PIN_WS      45
#define PIN_DIN     10
#define IN_SAMPLES  500     // 32 ms per read; 125 input samples make 128 at 16 kHz
#define RING        (MIC_RATE * 16)
#define PREROLL     (MIC_RATE * 3)  // MultiNet reports a phrase ~2.5 s after it starts (at the end of
                                    // the utterance), so the question may already be in the past

static esp_mn_iface_t *mn_iface;
static model_iface_data_t *mn;
static int chunk;                   // samples per detect() call (16 kHz)
static i2s_chan_handle_t rx;
static TaskHandle_t task;
static volatile bool running;
static volatile int heard_id = -1;
static volatile float heard_prob;
static volatile int peak;           // loudest sample since the last level() call
static volatile uint32_t chunks, detect_us_max;
static int gain = 8;                // the mic is quiet (~4% of full scale for speech at a desk)
static int16_t *ring;               // raw mic samples (before gain), PSRAM
static volatile uint32_t wpos;      // samples written so far (ring index = wpos % RING)
static uint32_t rpos;               // next sample wake.read() returns
static volatile uint32_t mark;      // where wake.read() starts: PREROLL before the detection
static volatile uint32_t preroll;   // samples between mark and the detection
static volatile int floor_at_mark;  // background level just before the phrase (see noise_floor)

// Mean |sample| of the quietest 1024-sample frame in the 5 s before `end`: the room's background
// level, which Python's end-of-speech detection compares against.
static int noise_floor(uint32_t end) {
    uint32_t start = end > 5 * MIC_RATE ? end - 5 * MIC_RATE : 0;
    int best = INT_MAX;
    for (uint32_t s = start; s + 1024 <= end; s += 1024) {
        int sum = 0;
        for (int i = 0; i < 1024; i++) {
            int v = ring[(s + i) % RING];
            sum += v < 0 ? -v : v;
        }
        best = MIN(best, sum / 1024);
    }
    return best == INT_MAX ? 0 : best;
}

static void detect(int16_t *buf) {
    int64_t t0 = esp_timer_get_time();
    esp_mn_state_t st = mn_iface->detect(mn, buf);
    uint32_t us = (uint32_t)(esp_timer_get_time() - t0);
    if (us > detect_us_max) {
        detect_us_max = us;
    }
    chunks++;
    if (st == ESP_MN_STATE_DETECTED) {
        esp_mn_results_t *r = mn_iface->get_results(mn);
        if (r->num > 0) {
            uint32_t w = wpos;
            preroll = MIN(w, PREROLL);
            mark = w - preroll;
            floor_at_mark = noise_floor(w);
            heard_prob = r->prob[0];
            heard_id = r->command_id[0] - 1;
        }
        mn_iface->clean(mn);
    } else if (st == ESP_MN_STATE_TIMEOUT) {
        mn_iface->clean(mn);        // nothing said in this window: start a fresh one
    }
}

static void listen_task(void *arg) {
    // x[0] is the previous block's last sample, so interpolation runs across block edges.
    int16_t *x = heap_caps_malloc((IN_SAMPLES + 1) * sizeof(int16_t), MALLOC_CAP_INTERNAL);
    int32_t *frames = heap_caps_malloc(IN_SAMPLES * 2 * sizeof(int32_t), MALLOC_CAP_INTERNAL);
    int16_t *out = heap_caps_malloc(chunk * sizeof(int16_t), MALLOC_CAP_INTERNAL);
    int outn = 0;
    uint32_t t = 0;                 // next output position, in 1/128ths of an input sample from x[0]
    x[0] = 0;
    while (running) {
        size_t got = 0;
        if (i2s_channel_read(rx, frames, IN_SAMPLES * 2 * sizeof(int32_t), &got, 100) != ESP_OK || got == 0) {
            continue;
        }
        // Stereo 32-bit slots; the ES7210's 16-bit sample is the top half of the left slot (MIC1).
        int n = got / (2 * sizeof(int32_t));
        for (int i = 0; i < n; i++) {
            x[i + 1] = frames[2 * i] >> 16;
        }
        for (int i = 1; i <= n; i++) {
            ring[(wpos + i - 1) % RING] = x[i];
        }
        wpos += n;
        int p = 0;
        for (int i = 1; i <= n; i++) {
            int v = x[i] * gain;
            v = v > 32767 ? 32767 : v < -32768 ? -32768 : v;
            x[i] = v;
            p = MAX(p, v < 0 ? -v : v);
        }
        if (p > peak) {
            peak = p;
        }
        // 16000 / 15625 = 128 / 125: step 125/128 of an input sample per output sample.
        while ((int)(t >> 7) < n) {
            int i = t >> 7, f = t & 127;
            out[outn++] = x[i] + (((x[i + 1] - x[i]) * f) >> 7);
            t += 125;
            if (outn == chunk) {
                detect(out);
                outn = 0;
            }
        }
        t -= n << 7;
        x[0] = x[n];
    }
    i2s_channel_disable(rx);
    i2s_del_channel(rx);
    rx = NULL;
    heap_caps_free(x);
    heap_caps_free(frames);
    heap_caps_free(out);
    task = NULL;
    vTaskDelete(NULL);
}

static void check(esp_err_t err, const char *what) {
    if (err != ESP_OK) {
        mp_raise_msg_varg(&mp_type_OSError, MP_ERROR_TEXT("%s: %s"), what, esp_err_to_name(err));
    }
}

static bool debug;

// With wake.debug(True), ESP-IDF/ESP-SR log lines go to the REPL instead of the console UART (not
// on USB), each given time to reach the Mac before whatever comes next can crash the board.
static int log_to_repl(const char *fmt, va_list ap) {
    char buf[200];
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    mp_hal_stdout_tx_strn(buf, MIN(n, (int)sizeof(buf) - 1));
    vTaskDelay(pdMS_TO_TICKS(30));
    return n;
}

static void step(const char *what) {
    if (debug) {
        mp_printf(&mp_plat_print, "wake: %s\n", what);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

static mp_obj_t wake_debug(mp_obj_t on) {
    debug = mp_obj_is_true(on);
    esp_log_set_vprintf(debug ? log_to_repl : vprintf);
    esp_log_level_set("*", debug ? ESP_LOG_INFO : ESP_LOG_ERROR);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(wake_debug_obj, wake_debug);

static mp_obj_t wake_stop(void) {
    running = false;
    for (int i = 0; task != NULL && i < 100; i++) {   // the task exits within one 32 ms read
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(wake_stop_obj, wake_stop);

// wake.init(phrases, timeout_ms=6000): load MultiNet from the "model" partition (once) and listen
// for these phrases; heard() returns the index of the phrase. Returns the phrases it rejected.
static mp_obj_t wake_init(size_t n_args, const mp_obj_t *args) {
    wake_stop();
    if (mn == NULL) {
        step("loading models");
        srmodel_list_t *models = esp_srmodel_init("model");
        if (models == NULL) {
            mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("no speech model partition"));
        }
        char *name = esp_srmodel_filter(models, ESP_MN_PREFIX, ESP_MN_ENGLISH);
        if (name == NULL) {
            mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("no English MultiNet model"));
        }
        step(name);
        mn_iface = esp_mn_handle_from_name(name);
        step("create");
        mn = mn_iface->create(name, n_args > 1 ? mp_obj_get_int(args[1]) : 6000);
        if (mn == NULL) {
            mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("MultiNet create failed"));
        }
        chunk = mn_iface->get_samp_chunksize(mn);
        step("commands alloc");
        check(esp_mn_commands_alloc(mn_iface, mn), "commands alloc");
        ring = heap_caps_malloc(RING * sizeof(int16_t), MALLOC_CAP_SPIRAM);
        if (ring == NULL) {
            mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("wake ring buffer"));
        }
    }
    step("commands add");
    esp_mn_commands_clear();
    size_t len;
    mp_obj_t *items;
    mp_obj_get_array(args[0], &len, &items);
    for (size_t i = 0; i < len; i++) {
        // MultiNet's command ids start at 1: it indexes a table by id - 1 (id 0 crashes it).
        check(esp_mn_commands_add(i + 1, mp_obj_str_get_str(items[i])), "add phrase");
    }
    step("commands update");
    esp_mn_error_t *err = esp_mn_commands_update();
    mp_obj_t rejected = mp_obj_new_list(0, NULL);
    for (int i = 0; err != NULL && i < err->num; i++) {
        mp_obj_list_append(rejected, mp_obj_new_str_from_cstr(err->phrases[i]->string));
    }
    mn_iface->clean(mn);
    heard_id = -1;
    step("ready");
    return rejected;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(wake_init_obj, 1, 2, wake_init);

// wake.start(gain=8): open the mic and start listening. Returns True if it started, False if it
// was already running. The caller must then (re)initialise the ES7210, which needs BCLK running.
static mp_obj_t wake_start(size_t n_args, const mp_obj_t *args) {
    if (mn == NULL) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("call wake.init() first"));
    }
    if (task != NULL) {
        return mp_const_false;
    }
    if (n_args > 0) {
        gain = mp_obj_get_int(args[0]);
    }
    heard_id = -1;                  // a phrase heard before the last stop() is stale now
    // Same bus format MicroPython's I2S(0, mode=RX, bits=16, rate=15625) uses underneath: it always
    // clocks 32-bit stereo frames for RX and keeps the top 16 bits of the left slot for MONO.
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    cc.dma_desc_num = 8;            // ~256 ms of slack if detect() runs long
    cc.dma_frame_num = IN_SAMPLES;
    cc.auto_clear = true;
    check(i2s_new_channel(&cc, NULL, &rx), "i2s channel");
    i2s_std_config_t sc = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(MIC_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_BCLK,
            .ws = PIN_WS,
            .dout = I2S_GPIO_UNUSED,
            .din = PIN_DIN,
        },
    };
    sc.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
    esp_err_t err = i2s_channel_init_std_mode(rx, &sc);
    if (err == ESP_OK) {
        err = i2s_channel_enable(rx);
    }
    if (err != ESP_OK) {
        i2s_del_channel(rx);
        rx = NULL;
        check(err, "i2s start");
    }
    running = true;
    if (xTaskCreatePinnedToCore(listen_task, "wake", 12 * 1024, NULL, 5, &task, 0) != pdPASS) {
        running = false;
        i2s_channel_disable(rx);
        i2s_del_channel(rx);
        rx = NULL;
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("wake task"));
    }
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(wake_start_obj, 0, 1, wake_start);

// wake.heard(): (phrase index, probability, background level, pre-roll bytes) once per detection,
// else None. Also points wake.read() at the audio from 3 s before the detection (the pre-roll).
static mp_obj_t wake_heard(void) {
    int id = heard_id;
    if (id < 0) {
        return mp_const_none;
    }
    heard_id = -1;
    rpos = mark;
    mp_obj_t t[4] = {mp_obj_new_int(id), mp_obj_new_float(heard_prob), mp_obj_new_int(floor_at_mark),
                     mp_obj_new_int(preroll * sizeof(int16_t))};
    return mp_obj_new_tuple(4, t);
}
static MP_DEFINE_CONST_FUN_OBJ_0(wake_heard_obj, wake_heard);

// wake.read(buf): copy the raw 15625 Hz mono 16-bit audio captured since the last read (starting
// with the pre-roll) into buf; returns the byte count, 0 if nothing new yet. Never blocks.
static mp_obj_t wake_read(mp_obj_t buf_in) {
    mp_buffer_info_t b;
    mp_get_buffer_raise(buf_in, &b, MP_BUFFER_WRITE);
    uint32_t w = wpos;
    if (w - rpos > RING) {
        rpos = w - RING;            // fell more than 16 s behind: the oldest audio is gone
    }
    uint32_t n = MIN(w - rpos, b.len / sizeof(int16_t));
    int16_t *dst = b.buf;
    for (uint32_t i = 0; i < n; i++) {
        dst[i] = ring[(rpos + i) % RING];
    }
    rpos += n;
    return mp_obj_new_int(n * sizeof(int16_t));
}
static MP_DEFINE_CONST_FUN_OBJ_1(wake_read_obj, wake_read);

// wake.level(): loudest sample since the last call, as a percentage of full scale (after gain).
static mp_obj_t wake_level(void) {
    int p = peak;
    peak = 0;
    return mp_obj_new_int(p * 100 / 32768);
}
static MP_DEFINE_CONST_FUN_OBJ_0(wake_level_obj, wake_level);

// wake.info(): (listening?, samples per chunk, chunks processed, slowest detect() in us).
static mp_obj_t wake_info(void) {
    mp_obj_t t[4] = {mp_obj_new_bool(task != NULL), mp_obj_new_int(chunk),
                     mp_obj_new_int_from_uint(chunks), mp_obj_new_int_from_uint(detect_us_max)};
    return mp_obj_new_tuple(4, t);
}
static MP_DEFINE_CONST_FUN_OBJ_0(wake_info_obj, wake_info);

static const mp_rom_map_elem_t wake_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_wake) },
    { MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&wake_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_start), MP_ROM_PTR(&wake_start_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop), MP_ROM_PTR(&wake_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_heard), MP_ROM_PTR(&wake_heard_obj) },
    { MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&wake_read_obj) },
    { MP_ROM_QSTR(MP_QSTR_level), MP_ROM_PTR(&wake_level_obj) },
    { MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&wake_info_obj) },
    { MP_ROM_QSTR(MP_QSTR_debug), MP_ROM_PTR(&wake_debug_obj) },
};
static MP_DEFINE_CONST_DICT(wake_globals, wake_globals_table);

const mp_obj_module_t wake_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&wake_globals,
};

MP_REGISTER_MODULE(MP_QSTR_wake, wake_module);
