cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(SenseMind_Hardware VERSION 0.7.0 LANGUAGES C)
target_sources(app PRIVATE src/main.c src/sensors.c src/wire.c src/display_ui.c src/buttons.c)
