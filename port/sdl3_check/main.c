/* Toolchain check for the Test Drive port: a 320x200 indexed framebuffer shown through the
 * EGA palette with 4:3 letterboxing -- the same display path the port will use.
 * Runs until the window is closed (or for --frames N frames, for automated checks). */
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <stdlib.h>
#include <string.h>

static const Uint32 ega_palette[16] = {
    0xFF000000, 0xFF0000AA, 0xFF00AA00, 0xFF00AAAA, 0xFFAA0000, 0xFFAA00AA, 0xFFAA5500, 0xFFAAAAAA,
    0xFF555555, 0xFF5555FF, 0xFF55FF55, 0xFF55FFFF, 0xFFFF5555, 0xFFFF55FF, 0xFFFFFF55, 0xFFFFFFFF,
};

int main(int argc, char **argv)
{
    int max_frames = -1;
    if (argc > 2 && strcmp(argv[1], "--frames") == 0)
        max_frames = atoi(argv[2]);

    if (!SDL_Init(SDL_INIT_VIDEO)) {
        SDL_Log("SDL_Init failed: %s", SDL_GetError());
        return 1;
    }
    SDL_Window *window;
    SDL_Renderer *renderer;
    if (!SDL_CreateWindowAndRenderer("Test Drive port - SDL3 check", 960, 720, SDL_WINDOW_RESIZABLE, &window, &renderer)) {
        SDL_Log("window/renderer failed: %s", SDL_GetError());
        return 1;
    }
    SDL_SetRenderLogicalPresentation(renderer, 320, 240, SDL_LOGICAL_PRESENTATION_LETTERBOX);
    SDL_Texture *tex = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, 320, 200);
    SDL_SetTextureScaleMode(tex, SDL_SCALEMODE_NEAREST);

    Uint8 fb[200 * 320];
    SDL_Log("SDL %d.%d.%d, renderer %s", SDL_VERSIONNUM_MAJOR(SDL_GetVersion()),
            SDL_VERSIONNUM_MINOR(SDL_GetVersion()), SDL_VERSIONNUM_MICRO(SDL_GetVersion()),
            SDL_GetRendererName(renderer));

    for (int frame = 0; max_frames < 0 || frame < max_frames; frame++) {
        SDL_Event ev;
        int quit = 0;
        while (SDL_PollEvent(&ev))
            if (ev.type == SDL_EVENT_QUIT || (ev.type == SDL_EVENT_KEY_DOWN && ev.key.key == SDLK_ESCAPE))
                quit = 1;
        if (quit)
            break;

        for (int y = 0; y < 200; y++)
            for (int x = 0; x < 320; x++)
                fb[y * 320 + x] = (Uint8)(((x / 20) + (y / 25) + frame / 8) & 15);

        Uint32 *pixels;
        int pitch;
        if (SDL_LockTexture(tex, NULL, (void **)&pixels, &pitch)) {
            for (int y = 0; y < 200; y++)
                for (int x = 0; x < 320; x++)
                    pixels[y * (pitch / 4) + x] = ega_palette[fb[y * 320 + x]];
            SDL_UnlockTexture(tex);
        }
        SDL_RenderClear(renderer);
        SDL_FRect dst = {0, 0, 320, 240};
        SDL_RenderTexture(renderer, tex, NULL, &dst);
        SDL_RenderPresent(renderer);
        SDL_Delay(16);
    }
    SDL_Log("ok");
    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
