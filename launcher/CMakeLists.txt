# The launcher, "Test Drive": picks a version of the port and starts it.
#
#   cmake -S launcher -B launcher/build -G Ninja && cmake --build launcher/build
#
# or, from tdport, -DTDPORT_LAUNCHER=ON builds it next to the port executables.
# Needs wxWidgets 3.2 (MSYS2: mingw-w64-x86_64-wxwidgets3.2-msw; Debian and Ubuntu: libwxgtk3.2-dev).
cmake_minimum_required(VERSION 3.24)
project(tdlauncher LANGUAGES CXX)
if(WIN32)
    enable_language(RC)
endif()

# MSYS2 and wxWidgets' own CMake builds install a package config; distributions
# such as Debian only ship wx-config, which CMake's FindwxWidgets uses.
find_package(wxWidgets 3.2 CONFIG QUIET COMPONENTS core base)
if(wxWidgets_FOUND AND TARGET wx::wxcore)
    set(TDL_WX_LIBRARIES wx::wxcore wx::wxbase)
else()
    find_package(wxWidgets 3.2 REQUIRED COMPONENTS core base)
    include(${wxWidgets_USE_FILE})
    set(TDL_WX_LIBRARIES ${wxWidgets_LIBRARIES})
endif()

add_executable(tdlauncher WIN32
    app.cpp
    icon.cpp
    keys.cpp
    launcher.cpp
    settings.cpp
    versions.cpp
)
set_target_properties(tdlauncher PROPERTIES OUTPUT_NAME "Test Drive" CXX_EXTENSIONS OFF)
target_compile_features(tdlauncher PRIVATE cxx_std_17)
target_link_libraries(tdlauncher PRIVATE ${TDL_WX_LIBRARIES})
# Built from tdport: beside the port executables, where it looks for them.
if(NOT PROJECT_IS_TOP_LEVEL)
    set_target_properties(tdlauncher PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
endif()

if(WIN32)
    target_sources(tdlauncher PRIVATE app.rc)
    target_link_libraries(tdlauncher PRIVATE comctl32)
    if(MINGW)
        # The C++ runtime inside the exe, so the build needs fewer DLLs beside it.
        target_link_options(tdlauncher PRIVATE -static-libgcc -static-libstdc++ $<$<CONFIG:Release>:-s>)
    endif()
    # The wxWidgets DLLs and everything they load, found where the compiler's own DLLs are.
    get_filename_component(TDL_DLL_DIR "${CMAKE_CXX_COMPILER}" DIRECTORY)
    add_custom_command(TARGET tdlauncher POST_BUILD
        COMMAND ${CMAKE_COMMAND} -DEXE=$<TARGET_FILE:tdlauncher> "-DSEARCH=${TDL_DLL_DIR}"
                -DCMAKE_OBJDUMP=${CMAKE_OBJDUMP} -P ${CMAKE_CURRENT_SOURCE_DIR}/copy_dlls.cmake)
endif()

if(MSVC)
    target_compile_options(tdlauncher PRIVATE /W4 /utf-8)
else()
    target_compile_options(tdlauncher PRIVATE -Wall -Wextra)
endif()
