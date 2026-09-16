cmake_minimum_required(VERSION 3.24)
project(tdport C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

find_package(SDL3 REQUIRED CONFIG)

file(GLOB_RECURSE TD_SOURCES CONFIGURE_DEPENDS src/*.c)
add_executable(tdport ${TD_SOURCES})
target_include_directories(tdport PRIVATE src)
target_link_libraries(tdport PRIVATE SDL3::SDL3)

if(MSVC)
    target_compile_options(tdport PRIVATE /W3)
else()
    # The memory model reads multi-byte values through byte pointers (see src/mem.h).
    target_compile_options(tdport PRIVATE -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing)
endif()

if(WIN32)
    add_custom_command(TARGET tdport POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_RUNTIME_DLLS:tdport> $<TARGET_FILE_DIR:tdport>
        COMMAND_EXPAND_LISTS)
endif()
