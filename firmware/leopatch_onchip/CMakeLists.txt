cmake_minimum_required(VERSION 3.20.0)

# The Axon NPU driver comes from the Edge AI Add-on, used as an extra Zephyr module.
if(NOT DEFINED EXTRA_ZEPHYR_MODULES AND NOT DEFINED ENV{EXTRA_ZEPHYR_MODULES})
  if(DEFINED ENV{EDGE_AI_ADDON_DIR})
    set(EXTRA_ZEPHYR_MODULES $ENV{EDGE_AI_ADDON_DIR})
  else()
    set(EXTRA_ZEPHYR_MODULES /opt/nordic/ncs/sdk-edge-ai)
  endif()
endif()

# --- Which model to build in -------------------------------------------------------------------
# MODEL_DIR is a folder from the Axon export (deploy/out_<name>/firmware_generated) holding
#   nrf_axon_model_<name>_.h, frontend_params.h and test_beats.h.
# Example: west build -b nrf54lm20dk/nrf54lm20b/cpuapp -- -DMODEL_DIR=<dir> -DRUN_MODEL=1
#   -DRECORD_SECONDS=5 "-DMODEL_POS_LABEL=CHD" "-DMODEL_NEG_LABEL=NO CHD"
# With sysbuild (the NCS default) the -D options land in the sysbuild cache, not in this app's
# cache, and they are needed before find_package(Zephyr) (the NPU buffer is a Kconfig option),
# so read them from there by hand. The app-prefixed form (-Dleopatch_onchip_MODEL_DIR) works too.
function(leopatch_option name default type help)
  set(value "${default}")
  if(DEFINED CACHE{${name}})
    set(value "$CACHE{${name}}")
  endif()
  if(DEFINED SYSBUILD_CACHE AND EXISTS "${SYSBUILD_CACHE}")
    file(STRINGS "${SYSBUILD_CACHE}" lines REGEX "^(leopatch_onchip_)?${name}:[A-Z]+=")
    foreach(prefix "" "leopatch_onchip_") # the app-prefixed entry wins
      foreach(line IN LISTS lines)
        if(line MATCHES "^${prefix}${name}:[A-Z]+=(.*)$")
          set(value "${CMAKE_MATCH_1}")
        endif()
      endforeach()
    endforeach()
  endif()
  set(${name} "${value}" CACHE ${type} "${help}" FORCE)
endfunction()

leopatch_option(MODEL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/src/generated PATH "Axon model package folder")
leopatch_option(MODEL_POS_LABEL "MAN" STRING "Result shown when sigmoid(logit) >= threshold")
leopatch_option(MODEL_NEG_LABEL "WOMAN" STRING "Result shown below the threshold")
leopatch_option(RUN_MODEL 0 STRING "1: run the model on the chip, 0: record and send only")
leopatch_option(RECORD_SECONDS 10 STRING "Recording length in seconds")

file(GLOB MODEL_HEADER RELATIVE ${MODEL_DIR} ${MODEL_DIR}/nrf_axon_model_*_.h)
list(LENGTH MODEL_HEADER n_headers)
if(NOT n_headers EQUAL 1)
  message(FATAL_ERROR "MODEL_DIR ${MODEL_DIR} must hold exactly one nrf_axon_model_<name>_.h")
endif()
foreach(f frontend_params.h test_beats.h)
  if(NOT EXISTS ${MODEL_DIR}/${f})
    message(FATAL_ERROR "MODEL_DIR ${MODEL_DIR} has no ${f}")
  endif()
endforeach()
string(REGEX REPLACE "^nrf_axon_model_(.*)_\\.h$" "\\1" MODEL_NAME ${MODEL_HEADER})
string(TOUPPER ${MODEL_NAME} MODEL_NAME_UPPER)

# The NPU scratch buffer is a Kconfig option; size it for this model.
file(STRINGS ${MODEL_DIR}/${MODEL_HEADER} il_line
     REGEX "#define NRF_AXON_MODEL_${MODEL_NAME_UPPER}_MAX_IL_BUFFER_USED")
string(REGEX MATCH "[0-9]+$" MODEL_IL_BUFFER "${il_line}")
file(STRINGS ${MODEL_DIR}/frontend_params.h ch_line REGEX "#define FRONTEND_STEM_CHANNELS")
string(REGEX MATCH "[0-9]+$" MODEL_STEM_CHANNELS "${ch_line}")
set(model_conf ${CMAKE_CURRENT_BINARY_DIR}/model.conf)
file(WRITE ${model_conf} "CONFIG_NRF_AXON_INTERLAYER_BUFFER_SIZE=${MODEL_IL_BUFFER}\n")
list(APPEND EXTRA_CONF_FILE ${model_conf})
message(STATUS "LeoPatch model: ${MODEL_NAME} (${MODEL_STEM_CHANNELS} stem channels, "
               "${MODEL_IL_BUFFER} B NPU buffer) from ${MODEL_DIR}")

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(leopatch_onchip)

target_sources(app PRIVATE
    src/main.c
    src/beats.c
    src/frontend.c
    src/notch.c
    src/upload.c
)
target_include_directories(app PRIVATE ${MODEL_DIR})
target_compile_definitions(app PRIVATE
    MODEL_HEADER="${MODEL_HEADER}"
    MODEL=model_${MODEL_NAME}
    MODEL_NAME_STR="${MODEL_NAME}"
    MODEL_OUTPUT_SIZE=NRF_AXON_MODEL_${MODEL_NAME_UPPER}_PACKED_OUTPUT_SIZE
    MODEL_STEM_CHANNELS=${MODEL_STEM_CHANNELS}
    MODEL_POS_LABEL="${MODEL_POS_LABEL}"
    MODEL_NEG_LABEL="${MODEL_NEG_LABEL}"
    RUN_MODEL=${RUN_MODEL}
    RECORD_SECONDS=${RECORD_SECONDS}
)
