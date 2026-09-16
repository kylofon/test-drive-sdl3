/* Test Drive (1987) SDL3 port — entry point.
 *
 * usage: tdport [--game-dir DIR] [--scale N] [--frame-rate FPS] [--bios-keys] [--check]
 *   --frame-rate emulated original drawing speed while driving (default 8; 0 = as fast as possible)
 *   --bios-keys driving keys act only through key repeat, exactly like the original (default: held keys)
 *   --game-dir  folder with the original game files (default: "Game" next to the working directory)
 *   --scale     initial window scale (default 3)
 *   --check     load and verify TDEGA.EXE, print a summary and exit (no window)
 */
#define SDL_MAIN_HANDLED
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"
#include "mem.h"

int game_main(void);   /* game/flow.c: port of main() at image 0x0010 */

int main(int argc, char **argv)
{
    const char *dir = "Game";
    int scale = 3;
    bool check = false;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--game-dir") && i + 1 < argc) dir = argv[++i];
        else if (!strcmp(argv[i], "--scale") && i + 1 < argc) scale = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--check")) check = true;
        else if (!strcmp(argv[i], "--bios-keys")) host_set_held_keys(false);
        else if (!strcmp(argv[i], "--frame-rate") && i + 1 < argc) host_set_frame_rate(atoi(argv[++i]));
        else {
            fprintf(stderr, "usage: %s [--game-dir DIR] [--scale N] [--frame-rate FPS] [--bios-keys] [--check]\n", argv[0]);
            return 2;
        }
    }

    char exe_path[1024];
    snprintf(exe_path, sizeof exe_path, "%s/TDEGA.EXE", dir);
    char err[256];
    if (!mem_load_exe(exe_path, err, sizeof err)) {
        fprintf(stderr, "%s\n", err);
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Test Drive", err, NULL);
        return 1;
    }
    if (check) {
        printf("TDEGA.EXE ok: image %u bytes at %04X:0000, DGROUP %04X\n", mem_image_size, LOAD_SEG, DGROUP);
        return 0;
    }

    if (!host_init(dir, scale)) return 1;
    int rc = game_main();
    host_shutdown();
    return rc;
}
