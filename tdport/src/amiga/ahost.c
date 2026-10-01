#include "ahost.h"

#include <SDL3/SDL.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../keybind.h"

static SDL_Window *window;
static SDL_Renderer *renderer;
static SDL_Texture *texture;
static SDL_AudioStream *audio;
static SDL_Gamepad *gamepad;

static void (*frame_source)(u32 *);
static u32 frame[AHOST_FRAME_MAX_W * AHOST_FRAME_MAX_H];
static int frame_w = 640, frame_h = 200;

static void (*audio_source)(s16 *, int);
static void (*key_handler)(u8, u16);

#define MAX_SERVERS 8
static struct { int pri; void (*fn)(void); } servers[MAX_SERVERS];
static int nservers;

/* Tick clock: tick n is due at start + n / 60 s. */
static Uint64 clock_start_ns;
static u32 ticks_run;
static Uint64 last_present_ns;

static void process_events(void);

bool ahost_init(int window_scale)
{
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return false;
    }
    if (window_scale < 1) window_scale = 3;
    if (!SDL_CreateWindowAndRenderer("Test Drive (Amiga)", 320 * window_scale, 240 * window_scale,
                                     SDL_WINDOW_RESIZABLE, &window, &renderer)) {
        fprintf(stderr, "window/renderer failed: %s\n", SDL_GetError());
        return false;
    }
    SDL_SetRenderVSync(renderer, 1);

    SDL_AudioSpec spec = { SDL_AUDIO_S16, 2, AUDIO_RATE };
    audio = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, NULL, NULL);
    if (audio) {
        SDL_ResumeAudioStreamDevice(audio);
        static s16 silence[AUDIO_RATE / 20 * 2];               /* 50 ms of lead-in against underruns */
        SDL_PutAudioStreamData(audio, silence, sizeof silence);
    } else {
        fprintf(stderr, "audio unavailable: %s\n", SDL_GetError());
    }

    clock_start_ns = SDL_GetTicksNS();
    ticks_run = 0;
    return true;
}

void ahost_shutdown(void)
{
    if (gamepad) SDL_CloseGamepad(gamepad);
    if (audio) SDL_DestroyAudioStream(audio);
    if (texture) SDL_DestroyTexture(texture);
    if (renderer) SDL_DestroyRenderer(renderer);
    if (window) SDL_DestroyWindow(window);
    gamepad = NULL; audio = NULL; texture = NULL; renderer = NULL; window = NULL;
    SDL_Quit();
}

/* ---------------------------------------------------------------- vertical blank */

void ahost_add_vbl_server(int pri, void (*fn)(void))
{
    if (nservers == MAX_SERVERS) return;
    int i = nservers;
    while (i > 0 && servers[i - 1].pri < pri) { servers[i] = servers[i - 1]; i--; }   /* same priority: FIFO */
    servers[i].pri = pri;
    servers[i].fn = fn;
    nservers++;
}

void ahost_remove_vbl_server(void (*fn)(void))
{
    for (int i = 0; i < nservers; i++)
        if (servers[i].fn == fn) {
            memmove(&servers[i], &servers[i + 1], (size_t)(nservers - i - 1) * sizeof servers[0]);
            nservers--;
            return;
        }
}

u32 ahost_vbl_count(void) { return ticks_run; }

static Uint64 tick_due_ns(u32 n) { return clock_start_ns + (Uint64)n * SDL_NS_PER_SECOND / VBL_HZ; }

static void audio_for_one_tick(void)
{
    enum { FRAMES = AUDIO_RATE / VBL_HZ };
    static s16 buf[FRAMES * 2];
    if (audio_source) audio_source(buf, FRAMES);
    else memset(buf, 0, sizeof buf);
    if (!audio) return;
    /* Drop output if the device is far behind (e.g. after a stall) instead of building latency. */
    if (SDL_GetAudioStreamQueued(audio) > AUDIO_RATE / 4 * 4) return;
    SDL_PutAudioStreamData(audio, buf, sizeof buf);
}

static void run_tick(void)
{
    ticks_run++;
    for (int i = 0; i < nservers; i++) servers[i].fn();
    audio_for_one_tick();
}

static void present(void)
{
    if (!frame_source || !texture) return;
    frame_source(frame);
    SDL_UpdateTexture(texture, NULL, frame, frame_w * 4);
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    SDL_FRect dst = { 0, 0, 640, 480 };
    SDL_RenderTexture(renderer, texture, NULL, &dst);
    SDL_RenderPresent(renderer);
    last_present_ns = SDL_GetTicksNS();
}

void ahost_pump(void)
{
    process_events();

    bool worked = false;
    Uint64 now = SDL_GetTicksNS();
    int budget = 30;                                    /* at most 0.5 s of catch-up per call */
    while (tick_due_ns(ticks_run + 1) <= now && budget-- > 0) {
        run_tick();
        worked = true;
    }
    if (budget < 0)                                     /* fell too far behind: resynchronise the clock */
        clock_start_ns = now - (tick_due_ns(ticks_run) - clock_start_ns);

    /* Present at most once per ~8 ms; VSync paces it further. */
    if (frame_source && now - last_present_ns >= 8 * SDL_NS_PER_MS) {
        present();
        worked = true;
    }
    if (!worked) {
        Uint64 next = tick_due_ns(ticks_run + 1);
        now = SDL_GetTicksNS();
        if (next > now) SDL_DelayNS(SDL_min(next - now, SDL_NS_PER_MS));
    }
}

void ahost_wait_tof(void)
{
    u32 start = ticks_run;
    while (ticks_run == start) ahost_pump();
}

void ahost_delay(u32 fiftieths)
{
    Uint64 until = SDL_GetTicksNS() + (Uint64)fiftieths * SDL_NS_PER_SECOND / 50;
    do ahost_pump(); while (SDL_GetTicksNS() < until);
}

u64 ahost_time_ns(void) { return SDL_GetTicksNS(); }

void ahost_wait_until_ns(u64 t)
{
    do ahost_pump(); while (SDL_GetTicksNS() < t);
}

/* ---------------------------------------------------------------- display, audio */

void ahost_set_frame_source(void (*compose)(u32 *), int w, int h)
{
    frame_source = compose;
    frame_w = SDL_clamp(w, 1, AHOST_FRAME_MAX_W);
    frame_h = SDL_clamp(h, 1, AHOST_FRAME_MAX_H);
    /* The picture fills a 4:3 area, as the 200-line NTSC display did on its monitor. */
    SDL_SetRenderLogicalPresentation(renderer, 640, 480, SDL_LOGICAL_PRESENTATION_LETTERBOX);
    if (texture) SDL_DestroyTexture(texture);
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING, frame_w, frame_h);
#if SDL_VERSION_ATLEAST(3, 4, 0)
    if (!SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_PIXELART))
#endif
        SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
}

void ahost_set_audio_source(void (*render)(s16 *, int)) { audio_source = render; }

/* ---------------------------------------------------------------- keyboard, joystick */

void ahost_set_key_handler(void (*handler)(u8, u16)) { key_handler = handler; }

/* Amiga raw key code of an SDL scancode (the positions of the A500 US keyboard); 0xFF = none. */
static u8 amiga_raw_key(SDL_Scancode sc)
{
    static const struct { SDL_Scancode sc; u8 code; } map[] = {
        { SDL_SCANCODE_GRAVE, 0x00 }, { SDL_SCANCODE_1, 0x01 }, { SDL_SCANCODE_2, 0x02 }, { SDL_SCANCODE_3, 0x03 },
        { SDL_SCANCODE_4, 0x04 }, { SDL_SCANCODE_5, 0x05 }, { SDL_SCANCODE_6, 0x06 }, { SDL_SCANCODE_7, 0x07 },
        { SDL_SCANCODE_8, 0x08 }, { SDL_SCANCODE_9, 0x09 }, { SDL_SCANCODE_0, 0x0A }, { SDL_SCANCODE_MINUS, 0x0B },
        { SDL_SCANCODE_EQUALS, 0x0C }, { SDL_SCANCODE_BACKSLASH, 0x0D }, { SDL_SCANCODE_KP_0, 0x0F },
        { SDL_SCANCODE_Q, 0x10 }, { SDL_SCANCODE_W, 0x11 }, { SDL_SCANCODE_E, 0x12 }, { SDL_SCANCODE_R, 0x13 },
        { SDL_SCANCODE_T, 0x14 }, { SDL_SCANCODE_Y, 0x15 }, { SDL_SCANCODE_U, 0x16 }, { SDL_SCANCODE_I, 0x17 },
        { SDL_SCANCODE_O, 0x18 }, { SDL_SCANCODE_P, 0x19 }, { SDL_SCANCODE_LEFTBRACKET, 0x1A },
        { SDL_SCANCODE_RIGHTBRACKET, 0x1B }, { SDL_SCANCODE_KP_1, 0x1D }, { SDL_SCANCODE_KP_2, 0x1E },
        { SDL_SCANCODE_KP_3, 0x1F }, { SDL_SCANCODE_A, 0x20 }, { SDL_SCANCODE_S, 0x21 }, { SDL_SCANCODE_D, 0x22 },
        { SDL_SCANCODE_F, 0x23 }, { SDL_SCANCODE_G, 0x24 }, { SDL_SCANCODE_H, 0x25 }, { SDL_SCANCODE_J, 0x26 },
        { SDL_SCANCODE_K, 0x27 }, { SDL_SCANCODE_L, 0x28 }, { SDL_SCANCODE_SEMICOLON, 0x29 },
        { SDL_SCANCODE_APOSTROPHE, 0x2A }, { SDL_SCANCODE_NONUSHASH, 0x2B }, { SDL_SCANCODE_KP_4, 0x2D },
        { SDL_SCANCODE_KP_5, 0x2E }, { SDL_SCANCODE_KP_6, 0x2F }, { SDL_SCANCODE_NONUSBACKSLASH, 0x30 },
        { SDL_SCANCODE_Z, 0x31 }, { SDL_SCANCODE_X, 0x32 }, { SDL_SCANCODE_C, 0x33 }, { SDL_SCANCODE_V, 0x34 },
        { SDL_SCANCODE_B, 0x35 }, { SDL_SCANCODE_N, 0x36 }, { SDL_SCANCODE_M, 0x37 }, { SDL_SCANCODE_COMMA, 0x38 },
        { SDL_SCANCODE_PERIOD, 0x39 }, { SDL_SCANCODE_SLASH, 0x3A }, { SDL_SCANCODE_KP_PERIOD, 0x3C },
        { SDL_SCANCODE_KP_7, 0x3D }, { SDL_SCANCODE_KP_8, 0x3E }, { SDL_SCANCODE_KP_9, 0x3F },
        { SDL_SCANCODE_SPACE, 0x40 }, { SDL_SCANCODE_BACKSPACE, 0x41 }, { SDL_SCANCODE_TAB, 0x42 },
        { SDL_SCANCODE_KP_ENTER, 0x43 }, { SDL_SCANCODE_RETURN, 0x44 }, { SDL_SCANCODE_ESCAPE, 0x45 },
        { SDL_SCANCODE_DELETE, 0x46 }, { SDL_SCANCODE_KP_MINUS, 0x4A }, { SDL_SCANCODE_UP, 0x4C },
        { SDL_SCANCODE_DOWN, 0x4D }, { SDL_SCANCODE_RIGHT, 0x4E }, { SDL_SCANCODE_LEFT, 0x4F },
        { SDL_SCANCODE_F1, 0x50 }, { SDL_SCANCODE_F2, 0x51 }, { SDL_SCANCODE_F3, 0x52 }, { SDL_SCANCODE_F4, 0x53 },
        { SDL_SCANCODE_F5, 0x54 }, { SDL_SCANCODE_F6, 0x55 }, { SDL_SCANCODE_F7, 0x56 }, { SDL_SCANCODE_F8, 0x57 },
        { SDL_SCANCODE_F9, 0x58 }, { SDL_SCANCODE_F10, 0x59 }, { SDL_SCANCODE_KP_LEFTPAREN, 0x5A },
        { SDL_SCANCODE_KP_RIGHTPAREN, 0x5B }, { SDL_SCANCODE_KP_DIVIDE, 0x5C }, { SDL_SCANCODE_KP_MULTIPLY, 0x5D },
        { SDL_SCANCODE_KP_PLUS, 0x5E }, { SDL_SCANCODE_F11, 0x5F } /* Help */,
        { SDL_SCANCODE_LSHIFT, 0x60 }, { SDL_SCANCODE_RSHIFT, 0x61 }, { SDL_SCANCODE_CAPSLOCK, 0x62 },
        { SDL_SCANCODE_LCTRL, 0x63 }, { SDL_SCANCODE_RCTRL, 0x63 }, { SDL_SCANCODE_LALT, 0x64 },
        { SDL_SCANCODE_RALT, 0x65 }, { SDL_SCANCODE_LGUI, 0x66 }, { SDL_SCANCODE_RGUI, 0x67 },
    };
    for (size_t i = 0; i < SDL_arraysize(map); i++)
        if (map[i].sc == sc) return map[i].code;
    return 0xFF;
}

static u16 qualifier(SDL_Keymod m, u8 code)
{
    u16 q = 0;
    if (m & SDL_KMOD_LSHIFT) q |= IEQUALIFIER_LSHIFT;
    if (m & SDL_KMOD_RSHIFT) q |= IEQUALIFIER_RSHIFT;
    if (m & SDL_KMOD_CAPS)   q |= IEQUALIFIER_CAPSLOCK;
    if (m & SDL_KMOD_CTRL)   q |= IEQUALIFIER_CONTROL;
    if (m & SDL_KMOD_LALT)   q |= IEQUALIFIER_LALT;
    if (m & SDL_KMOD_RALT)   q |= IEQUALIFIER_RALT;
    if (m & SDL_KMOD_LGUI)   q |= IEQUALIFIER_LCOMMAND;
    if (m & SDL_KMOD_RGUI)   q |= IEQUALIFIER_RCOMMAND;
    /* The keypad keys: 0x0F, 0x1D-0x1F, 0x2D-0x2F, 0x3C-0x3F, 0x43, 0x4A, 0x5A-0x5E. */
    if (code == 0x0F || (code >= 0x1D && code <= 0x1F) || (code >= 0x2D && code <= 0x2F) ||
        (code >= 0x3C && code <= 0x3F) || code == 0x43 || code == 0x4A || (code >= 0x5A && code <= 0x5E))
        q |= IEQUALIFIER_NUMERICPAD;
    return q;
}

/* The raw key of each hot key's default key (keybind.h; 0 = a driving key or not an Amiga action). */
static const u8 BINDING_KEYS[KB_COUNT] = {
    [KB_PAUSE] = 0x19, [KB_GEARBOX] = 0x22, [KB_GATE] = 0x18, [KB_MUSIC] = 0x37, [KB_SOUND] = 0x21,
};

static void process_events(void)
{
    SDL_Event ev;
    while (SDL_PollEvent(&ev)) {
        switch (ev.type) {
        case SDL_EVENT_QUIT:
            ahost_shutdown();
            exit(0);
        case SDL_EVENT_KEY_DOWN:
        case SDL_EVENT_KEY_UP: {
            /* Alt+Enter toggles full screen; every other key goes to input.device as a raw key. */
            if (ev.key.key == SDLK_RETURN && (ev.key.mod & SDL_KMOD_ALT)) {
                if (ev.type == SDL_EVENT_KEY_DOWN && !ev.key.repeat)
                    SDL_SetWindowFullscreen(window, !(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN));
                break;
            }
            u8 code = amiga_raw_key(ev.key.scancode);
            if (code == 0xFF || !key_handler) break;
            u16 q = qualifier(ev.key.mod, code);
            if (kb_active() && ev.type == SDL_EVENT_KEY_DOWN) {   /* PORT: key bindings while driving */
                bool drop;
                int a = kb_lookup((u16)(kb_key(ev.key.scancode) | kb_mods(ev.key.mod)), &drop);
                if (a >= 0) {
                    /* the game's own key for a hot key; a driving key is read as the joystick */
                    if (BINDING_KEYS[a]) key_handler(BINDING_KEYS[a], ev.key.repeat ? IEQUALIFIER_REPEAT : 0);
                    break;
                }
                if (drop) break;
            }
            if (ev.key.repeat) q |= IEQUALIFIER_REPEAT;
            key_handler(ev.type == SDL_EVENT_KEY_UP ? (u8)(code | 0x80) : code, q);
            break;
        }
        case SDL_EVENT_GAMEPAD_ADDED:
            if (!gamepad) gamepad = SDL_OpenGamepad(ev.gdevice.which);
            break;
        case SDL_EVENT_GAMEPAD_REMOVED:
            if (gamepad && SDL_GetGamepadID(gamepad) == ev.gdevice.which) {
                SDL_CloseGamepad(gamepad);
                gamepad = NULL;
            }
            break;
        default:
            break;
        }
    }
}

void ahost_joystick(bool *up, bool *down, bool *left, bool *right, bool *fire)
{
    process_events();
    const bool *ks = SDL_GetKeyboardState(NULL);
    /* The arrows and Space are the keys of their actions (keybind.h); the keypad and Right Ctrl keep their job. */
    bool u = kb_held(KB_ACCELERATE) || ks[SDL_SCANCODE_KP_8] || ks[SDL_SCANCODE_KP_7] || ks[SDL_SCANCODE_KP_9];
    bool d = kb_held(KB_BRAKE) || ks[SDL_SCANCODE_KP_2] || ks[SDL_SCANCODE_KP_1] || ks[SDL_SCANCODE_KP_3];
    bool l = kb_held(KB_STEER_LEFT) || ks[SDL_SCANCODE_KP_4] || ks[SDL_SCANCODE_KP_7] || ks[SDL_SCANCODE_KP_1];
    bool r = kb_held(KB_STEER_RIGHT) || ks[SDL_SCANCODE_KP_6] || ks[SDL_SCANCODE_KP_9] || ks[SDL_SCANCODE_KP_3];
    bool f = kb_held(KB_FIRE) || ks[SDL_SCANCODE_RCTRL] || ks[SDL_SCANCODE_KP_0];
    if (gamepad) {
        const s16 dead = 12000;
        s16 ax = SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_LEFTX);
        s16 ay = SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_LEFTY);
        u |= ay < -dead || SDL_GetGamepadButton(gamepad, SDL_GAMEPAD_BUTTON_DPAD_UP);
        d |= ay > dead || SDL_GetGamepadButton(gamepad, SDL_GAMEPAD_BUTTON_DPAD_DOWN);
        l |= ax < -dead || SDL_GetGamepadButton(gamepad, SDL_GAMEPAD_BUTTON_DPAD_LEFT);
        r |= ax > dead || SDL_GetGamepadButton(gamepad, SDL_GAMEPAD_BUTTON_DPAD_RIGHT);
        f |= SDL_GetGamepadButton(gamepad, SDL_GAMEPAD_BUTTON_SOUTH) || SDL_GetGamepadButton(gamepad, SDL_GAMEPAD_BUTTON_EAST);
    }
    /* A digital joystick cannot report both opposite directions. */
    if (u && d) u = d = false;
    if (l && r) l = r = false;
    *up = u; *down = d; *left = l; *right = r; *fire = f;
}

/* ---------------------------------------------------------------- errors */

_Noreturn void ahost_fatal(const char *fmt, ...)
{
    char msg[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    fprintf(stderr, "fatal: %s\n", msg);
    SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Test Drive", msg, window);
    if (window) ahost_shutdown();
    exit(3);
}
