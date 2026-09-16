cmake_minimum_required(VERSION 3.24)
project(sdl3_check C)

find_package(SDL3 REQUIRED CONFIG)

add_executable(sdl3_check main.c)
target_link_libraries(sdl3_check PRIVATE SDL3::SDL3)
