# Makefile for Test Drive SDL3 port — reverse-engineering + build pipeline
# Targets are numbered by pipeline stage:
#   env → 1 unpack → 2 index → 3 roadmap → 4 cars → 5 sound → 6 sheets →
#   7 report → symbols → build → run → dev
SERVICE = Test Drive SDL3 port

# Variables
GAME_DIR    ?= Game
WORK_DIR    = work
BUILD_DIR   = tdport/build
CHECK_DIR   = port/sdl3_check/build
BUILD_TYPE  ?= Release
VENV_DIR    = .venv
PYTHON      = $(VENV_DIR)/bin/python
PIP         = $(VENV_DIR)/bin/pip
CC          ?= cc
GAME_EXE    = $(GAME_DIR)/TDEGA.EXE
UNPACKED    = $(WORK_DIR)/TDEGA_unp.exe
DGROUP      ?= 0xC9A0
CMAKE_FLAGS ?= -DCMAKE_BUILD_TYPE=$(BUILD_TYPE)
off         ?= 0x2054
len         ?= 0x40

# MinGW builds the port as tdport.exe; MSYS/MinGW sets OS=Windows_NT.
ifeq ($(OS),Windows_NT)
PORT_BIN = $(BUILD_DIR)/tdport.exe
else
PORT_BIN = $(BUILD_DIR)/tdport
endif

.PHONY: help install clean \
        data-unpack data-index data-roadmap data-cars data-sound data-sheets data-report \
        symbols symbols-merge symbols-gen \
        build check-toolchain \
        run run-check \
        dis lint

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — reverse-engineering + build pipeline\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install the reverse-engineering tool dependencies (capstone, numpy, pillow)
	@if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(PIP) install -U pip wheel; \
		$(PIP) install capstone numpy pillow; \
	fi
	@echo "Tool environment ready."

clean: ## Remove build dirs, .venv and Python caches (keeps work/ and generated specs)
	rm -rf $(BUILD_DIR)
	rm -rf $(CHECK_DIR)
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."

# ── Stage 1 · Unpack (TDEGA.EXE → work/TDEGA_unp.exe) ────────────────────────

data-unpack: install ## [STEP  1] EXEPACK-unpack $(GAME_EXE) into work/TDEGA_unp.exe
	@test -f "$(GAME_EXE)" || { echo "Missing $(GAME_EXE) — put your original game files in $(GAME_DIR)/"; exit 1; }
	$(PYTHON) tools/unexepack.py "$(GAME_EXE)" "$(UNPACKED)"

# ── Stage 2 · Function index (Capstone) ──────────────────────────────────────

data-index: install data-unpack ## [STEP  2] Index functions → port/tdega_functions.json / .csv
	$(PYTHON) tools/funcindex.py "$(UNPACKED)" $(DGROUP)

# ── Stage 3 · Road layout ────────────────────────────────────────────────────

data-roadmap: install data-unpack ## [STEP  3] Extract road stream + render maps → work/road.json, route_map.png, elevation.png
	$(PYTHON) tools/roadmap.py "$(UNPACKED)"

# ── Stage 4 · Car data ───────────────────────────────────────────────────────

data-cars: install ## [STEP  4] Decode car .BIN fields → work/cars/*.json
	$(PYTHON) tools/cardata.py "$(GAME_DIR)" "$(WORK_DIR)/cars"

# ── Stage 5 · Sound ──────────────────────────────────────────────────────────

data-sound: install data-unpack ## [STEP  5] Render songs from TDSND.SND → work/sound/*.wav
	$(PYTHON) tools/sndplay.py --snd "$(GAME_DIR)/TDSND.SND" --exe "$(UNPACKED)" --out "$(WORK_DIR)/sound"

# ── Stage 6 · Sprite sheets ──────────────────────────────────────────────────

data-sheets: install ## [STEP  6] Render PES/CMP sprite contact sheets → work/sheets/*.png
	$(PYTHON) tools/sheet.py "$(GAME_DIR)" "$(WORK_DIR)/sheets"

# ── Stage 7 · HTML report ────────────────────────────────────────────────────

data-report: install data-cars ## [STEP  7] Build work/report/index.html (also needs work/stages_compact.json)
	$(PYTHON) tools/build_report.py
	@echo "Open work/report/index.html."

# ── Symbols (port/spec/*_symbols.csv → port/symbols.csv → tdport/src/symbols.h) ─

symbols: symbols-gen ## Regenerate port/symbols.csv and tdport/src/symbols.h from the spec symbol tables
	@echo "Symbols regenerated."

symbols-merge: install ## Merge port/spec/*_symbols.csv → port/symbols.csv, symbols_ghidra.txt, symbol_conflicts.txt
	$(PYTHON) tools/merge_symbols.py

symbols-gen: symbols-merge ## Generate tdport/src/symbols.h from port/symbols.csv
	$(PYTHON) tools/gen_symbols.py

# ── Build ────────────────────────────────────────────────────────────────────

build: ## Configure and build the SDL3 port into tdport/build (override CMAKE_FLAGS for MinGW: -G Ninja -DCMAKE_C_COMPILER=gcc)
	cmake -S tdport -B $(BUILD_DIR) $(CMAKE_FLAGS)
	cmake --build $(BUILD_DIR) --parallel

check-toolchain: ## Build port/sdl3_check to verify the C compiler + SDL3 setup
	cmake -S port/sdl3_check -B $(CHECK_DIR) $(CMAKE_FLAGS)
	cmake --build $(CHECK_DIR) --parallel

# ── Run ──────────────────────────────────────────────────────────────────────

run: build ## Run the port against $(GAME_DIR) (usage: make run GAME_DIR=Game scale=3)
	$(PORT_BIN) --game-dir "$(GAME_DIR)" $(if $(scale),--scale "$(scale)")

run-check: build ## Load TDEGA.EXE and exit without opening a window
	$(PORT_BIN) --game-dir "$(GAME_DIR)" --check

# ── Development ──────────────────────────────────────────────────────────────

dis: install data-unpack ## Disassemble the unpacked image (usage: make dis off=0x2054 len=0x40)
	$(PYTHON) tools/x86dis.py "$(UNPACKED)" dis "$(off)" "$(len)"

lint: ## Compile-check every tdport source without linking (same warnings as CMake)
	@for f in $$(find tdport/src -name '*.c'); do \
		echo "check $$f"; \
		$(CC) -std=c11 -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing -fsyntax-only \
			-Itdport/src $$(pkg-config --cflags sdl3 2>/dev/null) $$f || exit 1; \
	done
	@echo "All sources compile."
