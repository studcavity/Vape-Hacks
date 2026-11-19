/*
 * lb_version.h — what firmware this is. Bump by hand when behaviour changes.
 *
 * The firmware version is separate from the wire format (LB_FORMAT_* in
 * lb_sync.h): many firmware releases share one format. Both, plus a build ID
 * stamped from git by tools/lb_flash.py, are in the first words of the sync
 * block, so `lb_sync.py info` can say exactly what a unit is running.
 */
#pragma once

#define LB_FW_MAJOR 0
#define LB_FW_MINOR 5
#define LB_FW_PATCH 1
#define LB_FW_VERSION ((uint32_t)((LB_FW_MAJOR << 16) | (LB_FW_MINOR << 8) | LB_FW_PATCH))

// Stamped by tools/lb_flash.py build:  -DLB_BUILD_ID=0x<first 8 hex digits of the git commit>u
// and -DLB_BUILD_DIRTY=1 when the working tree had uncommitted changes. A build made
// any other way (Arduino IDE) reports build 0, i.e. "unknown".
#ifndef LB_BUILD_ID
#define LB_BUILD_ID 0u
#endif
#ifndef LB_BUILD_DIRTY
#define LB_BUILD_DIRTY 0
#endif

// Which board this is. The host knows what each id can do (sensors, links) from host/lb_catalog.py,
// so the firmware only reports it. Build for another board with  -DLB_MODEL_ID=<id>u.
#ifndef LB_MODEL_ID
#define LB_MODEL_ID 0u
#endif
