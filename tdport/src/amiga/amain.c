/* Test Drive (1987), Amiga release — SDL3 port, entry point.
 *
 * usage: tdport-amiga [--game-dir DIR] [--scale N] [--original-bugs] [--keys NAME=CODE,...] [--check]
 *   --game-dir       the Amiga disk image (.adf), a folder holding it, or a folder with the files of the disk
 *                    (td, Cars/, Pics/, ...); default: "Game Amiga" next to the working directory
 *   --scale          initial window scale (default 3)
 *   --original-bugs  keep the original's bugs instead of the port's fixes (port/amiga/README.md)
 *   --keys           key bindings while driving, "name=code,..." for the actions not on their default keys (the
 *                    launcher's Game settings > Key Bindings; ../keybind.c)
 *   --check          load and verify td, unpack every Pckd file of the disk, print a summary and exit (no window)
 */
#define SDL_MAIN_HANDLED
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "adisk.h"
#include "ahost.h"
#include "amem.h"
#include "aport.h"
#include "asymbols.h"
#include "../keybind.h"
#include "platform/platform.h"

bool g_original_bugs;

int td_main(void);   /* game/main.c: port of main() at 0x10018 */

static u16 crc16_arc(APTR p, u32 n)
{
    u16 crc = 0;
    for (u32 i = 0; i < n; i++) {
        crc ^= rd8(p + i);
        for (int k = 0; k < 8; k++) crc = (crc & 1) ? (u16)((crc >> 1) ^ 0xA001) : (u16)(crc >> 1);
    }
    return crc;
}

/* --check: the hunk layout, then every Pckd file unpacked by the port's loader and checked against its CRC. */
static int files, bad;

static void check_file(const char *name, void *ctx)
{
    (void)ctx;
    u32 size = 0;
    u8 *raw = adisk_read(name, &size);
    bool pckd = raw && size >= 16 && memcmp(raw, "Pckd", 4) == 0;
    unsigned method = pckd ? (unsigned)(raw[12] << 8 | raw[13]) : 0;
    u16 want = pckd ? (u16)(raw[14] << 8 | raw[15]) : 0;
    free(raw);
    if (!pckd) return;
    files++;
    APTR out = load_file(name);
    u32 len = D32(D_g_loadedSize);
    u16 got = out ? crc16_arc(out, len) : 0;
    bool ok = out && got == want;
    if (!ok) bad++;
    printf("%-28s method %u  %6u bytes  crc %04X %s\n", name, method, len, got,
           ok ? "ok" : g_original_bugs ? "differs (--original-bugs drops the last byte)" : "MISMATCH");
    free_mem(out);
}

static int check(void)
{
    printf("disk: %s\n", adisk_source());
    for (int i = 0; i < amem_hunk_count(); i++) {
        u32 base, size;
        const char *kind;
        bool overlay;
        amem_hunk_info(i, &base, &size, &kind, &overlay);
        printf("hunk %d %-4s%s %05X-%05X\n", i, kind, overlay ? " overlay" : "        ", base, base + size);
    }
    adisk_list(check_file, NULL);
    printf("td ok: %d hunks, image %05X-%05X; %d Pckd files, %d %s\n", amem_hunk_count(), IMAGE_BASE, amem_image_end,
           files, bad, g_original_bugs ? "differ" : "bad");
    return bad && !g_original_bugs ? 1 : 0;
}

int main(int argc, char **argv)
{
    const char *dir = "Game Amiga";
    int scale = 3;
    bool check_only = false;
    kb_init(KB_AMIGA);
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--game-dir") && i + 1 < argc) dir = argv[++i];
        else if (!strcmp(argv[i], "--scale") && i + 1 < argc) scale = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--original-bugs")) g_original_bugs = true;
        else if (!strcmp(argv[i], "--check")) check_only = true;
        else if (!strcmp(argv[i], "--keys") && i + 1 < argc) {
            if (!kb_parse(argv[++i])) {
                fprintf(stderr, "bad --keys list: %s\n", argv[i]);
                return 2;
            }
        }
        else {
            fprintf(stderr, "usage: %s [--game-dir DIR] [--scale N] [--original-bugs] [--keys NAME=CODE,...] [--check]\n",
                    argv[0]);
            return 2;
        }
    }

    char err[512] = "";
    u32 len = 0;
    u8 *td = NULL;
    bool ok = adisk_open(dir, err, sizeof err);
    if (ok && !(td = adisk_read("td", &len))) {
        snprintf(err, sizeof err, "%s has no td (the game's program).", adisk_source());
        ok = false;
    }
    ok = ok && amem_load_exe(td, len, err, sizeof err);
    free(td);
    if (!ok) {
        fprintf(stderr, "%s\n", err);
        if (!check_only) SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Test Drive", err, NULL);
        return 1;
    }
    if (check_only) return check();

    if (!ahost_init(scale)) return 1;
    int rc = td_main();
    ahost_shutdown();
    return rc;
}
