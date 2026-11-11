cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(leopatch_sex_cpu)

# TFLite Micro uses local statics; Zephyr has no thread-safe-static support, so turn it off
# (same as the in-tree tflite-micro samples).
set(NO_THREADSAFE_STATICS $<TARGET_PROPERTY:compiler-cpp,no_threadsafe_statics>)
zephyr_compile_options($<$<COMPILE_LANGUAGE:CXX>:${NO_THREADSAFE_STATICS}>)

target_include_directories(app PRIVATE src)
target_sources(app PRIVATE src/main.cc src/model_data.cc)
