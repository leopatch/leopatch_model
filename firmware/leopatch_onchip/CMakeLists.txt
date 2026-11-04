cmake_minimum_required(VERSION 3.20.0)

# The Axon NPU driver comes from the Edge AI Add-on, used as an extra Zephyr module.
if(NOT DEFINED EXTRA_ZEPHYR_MODULES AND NOT DEFINED ENV{EXTRA_ZEPHYR_MODULES})
  if(DEFINED ENV{EDGE_AI_ADDON_DIR})
    set(EXTRA_ZEPHYR_MODULES $ENV{EDGE_AI_ADDON_DIR})
  else()
    set(EXTRA_ZEPHYR_MODULES /opt/nordic/ncs/sdk-edge-ai)
  endif()
endif()

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(leopatch_onchip)

target_sources(app PRIVATE
    src/main.c
    src/beats.c
    src/frontend.c
    src/notch.c
    src/upload.c
)
