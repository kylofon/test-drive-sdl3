cmake_minimum_required(VERSION 3.24)
project(tdport C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# The EGA port (tdport) is always built. The other graphics modes of the original release are ports of
# TDCGA.EXE and are opt-in:
option(TDPORT_CGA      "Also build tdport-cga: TDCGA.EXE, CGA 4 colours" OFF)
option(TDPORT_HERCULES "Also build tdport-herc: TDCGA.EXE in Hercules monochrome mode" OFF)
# The Amiga release is a separate program (td, 68000) with its own sources in src/amiga.
option(TDPORT_AMIGA    "Also build tdport-amiga: the Amiga release (td)" OFF)

find_package(SDL3 REQUIRED CONFIG)

# The MSYS2 SDL3.dll imports libiconv-2.dll. TARGET_RUNTIME_DLLS does not list it, so it is copied separately.
if(WIN32)
    find_file(TDPORT_ICONV_DLL libiconv-2.dll HINTS "${SDL3_DIR}/../../../bin" NO_DEFAULT_PATH)
endif()

file(GLOB_RECURSE TD_SOURCES CONFIGURE_DEPENDS src/*.c)
list(FILTER TD_SOURCES EXCLUDE REGEX "/src/amiga/")
# One graphics layer per executable: gfx.c drives the EGA planes, gfx_cga.c the CGA/Hercules screen.
list(FILTER TD_SOURCES EXCLUDE REGEX "/platform/gfx(_cga)?\\.c$")

function(tdport_setup target)
    target_include_directories(${target} PRIVATE src)
    target_link_libraries(${target} PRIVATE SDL3::SDL3)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W3)
    else()
        # The memory model reads multi-byte values through byte pointers (see src/mem.h).
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing)
    endif()
    if(WIN32)
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_RUNTIME_DLLS:${target}> $<TARGET_FILE_DIR:${target}>
            COMMAND_EXPAND_LISTS)
        if(TDPORT_ICONV_DLL)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different ${TDPORT_ICONV_DLL} $<TARGET_FILE_DIR:${target}>)
        endif()
    endif()
endfunction()

function(tdport_add_variant target gfx_source)
    add_executable(${target} ${TD_SOURCES} src/platform/${gfx_source})
    target_compile_definitions(${target} PRIVATE ${ARGN})
    tdport_setup(${target})
endfunction()

tdport_add_variant(tdport gfx.c)
if(TDPORT_CGA)
    tdport_add_variant(tdport-cga gfx_cga.c TD_CGA=1)
endif()
if(TDPORT_HERCULES)
    tdport_add_variant(tdport-herc gfx_cga.c TD_CGA=1 TD_HERC=1)
endif()
if(TDPORT_AMIGA)
    file(GLOB_RECURSE TD_AMIGA_SOURCES CONFIGURE_DEPENDS src/amiga/*.c)
    # keybind.c (the key bindings) is shared with the DOS builds.
    add_executable(tdport-amiga ${TD_AMIGA_SOURCES} src/keybind.c)
    tdport_setup(tdport-amiga)
endif()

# The launcher ("Test Drive"), which lets players pick one of the executables above. It needs wxWidgets 3.2.
option(TDPORT_LAUNCHER "Also build the launcher, Test Drive.exe (wxWidgets)" OFF)
if(TDPORT_LAUNCHER)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../launcher launcher)
endif()
