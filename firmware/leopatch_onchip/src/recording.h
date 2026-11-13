/*
 * Recording settings shared by the recorder and the beat finder.
 */
#pragma once

#define SAMPLE_RATE_HZ 500
#ifndef RECORD_SECONDS /* set by CMakeLists.txt */
#define RECORD_SECONDS 10
#endif
#define RECORDING_LEN  (SAMPLE_RATE_HZ * RECORD_SECONDS)
