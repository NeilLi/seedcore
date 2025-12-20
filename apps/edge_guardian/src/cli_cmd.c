/**
 * @file cli_cmd.c
 * @brief SeedCore Edge Guardian CLI Commands (v1.0)
 *
 * This file defines the initial Command Line Interface (CLI) commands
 * for the SeedCore Edge Guardian application running on TuyaOpen / TuyaOS.
 *
 * Design goals:
 *  - Safe, minimal, debuggable
 *  - Familiar to Tuya developers (based on switch_demo)
 *  - SeedCore-oriented semantics (edge, AI-ready)
 *  - Extendable without breaking ABI
 *
 * v1.0 Scope:
 *  - Relay / switch control
 *  - IoT lifecycle control
 *  - Memory diagnostics
 *  - Network & KV debug passthrough
 *
 * Future versions will extend this with:
 *  - Camera capture & status
 *  - AI inference triggers
 *  - Event simulation & replay
 *
 * Copyright (c) 2025 SeedCore
 */

 #include "tal_api.h"
 #include "tuya_iot.h"
 #include <stdlib.h>
 #include <string.h>
 
 /* External Tuya CLI helpers */
 extern void tal_kv_cmd(int argc, char *argv[]);
 extern void netmgr_cmd(int argc, char *argv[]);
 
 /* =========================================================
  * SeedCore: Relay / Switch Control
  * ========================================================= */
 
 /**
  * @brief Control the Edge Guardian relay (AI switch)
  *
  * Usage:
  *   edge_switch on
  *   edge_switch off
  *
  * This maps to DP ID 1 ("switch") in the Tuya product model.
  */
 static void edge_switch_cmd(int argc, char *argv[])
 {
     if (argc < 2) {
         PR_NOTICE("usage: edge_switch <on|off>");
         return;
     }
 
     char dp_json[64];
 
     if (strcmp(argv[1], "on") == 0) {
         snprintf(dp_json, sizeof(dp_json), "{\"1\":true}");
     } else if (strcmp(argv[1], "off") == 0) {
         snprintf(dp_json, sizeof(dp_json), "{\"1\":false}");
     } else {
         PR_NOTICE("usage: edge_switch <on|off>");
         return;
     }
 
     PR_INFO("Edge Guardian: switch %s", argv[1]);
     tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
 }
 
 /* =========================================================
  * System / OS Utilities
  * ========================================================= */
 
 /**
  * @brief Execute system shell command (DEBUG ONLY)
  *
  * Usage:
  *   sys <command>
  *
  * NOTE:
  *  - Intended for development builds only
  *  - Should be removed or disabled for production firmware
  */
 static void system_cmd(int argc, char *argv[])
 {
     if (argc < 2) {
         PR_NOTICE("usage: sys <cmd>");
         return;
     }
 
     char cmd[256] = {0};
     size_t offset = 0;
 
     for (int i = 1; i < argc; i++) {
         int ret = snprintf(cmd + offset, sizeof(cmd) - offset, "%s ", argv[i]);
         if (ret < 0 || offset + ret >= sizeof(cmd)) {
             break;
         }
         offset += ret;
     }
 
     PR_DEBUG("exec: %s", cmd);
     system(cmd);
 }
 
 /**
  * @brief Display current free heap memory
  *
  * Useful for:
  *  - Camera buffer tuning
  *  - AI model loading validation
  */
 static void mem_cmd(int argc, char *argv[])
 {
     int free_heap = tal_system_get_free_heap_size();
     PR_NOTICE("free heap: %d bytes", free_heap);
 }
 
 /* =========================================================
  * IoT Lifecycle Control
  * ========================================================= */
 
 /**
  * @brief Reset device (unpair / unactivate)
  */
 static void iot_reset_cmd(int argc, char *argv[])
 {
     PR_WARN("IoT reset triggered");
     tuya_iot_reset(tuya_iot_client_get());
 }
 
 /**
  * @brief Start Tuya IoT service
  */
 static void iot_start_cmd(int argc, char *argv[])
 {
     PR_INFO("IoT start");
     tuya_iot_start(tuya_iot_client_get());
 }
 
 /**
  * @brief Stop Tuya IoT service
  */
 static void iot_stop_cmd(int argc, char *argv[])
 {
     PR_INFO("IoT stop");
     tuya_iot_stop(tuya_iot_client_get());
 }
 
 /* =========================================================
  * CLI Command Table
  * ========================================================= */
 
 static cli_cmd_t s_edge_cli_cmds[] = {
     /* SeedCore-specific */
     { .name = "edge_switch", .func = edge_switch_cmd, .help = "control edge relay: on/off" },
 
     /* Diagnostics */
     { .name = "mem",         .func = mem_cmd,         .help = "show free heap size" },
 
     /* Tuya passthrough */
     { .name = "kv",          .func = tal_kv_cmd,      .help = "kv storage commands" },
     { .name = "netmgr",      .func = netmgr_cmd,      .help = "network manager commands" },
 
     /* IoT lifecycle */
     { .name = "iot_reset",   .func = iot_reset_cmd,  .help = "reset IoT (factory reset)" },
     { .name = "iot_start",   .func = iot_start_cmd,  .help = "start IoT service" },
     { .name = "iot_stop",    .func = iot_stop_cmd,   .help = "stop IoT service" },
 
     /* Debug */
     { .name = "sys",         .func = system_cmd,     .help = "execute system command (debug)" },
 };
 
 /* =========================================================
  * CLI Initialization
  * ========================================================= */
 
 /**
  * @brief Initialize SeedCore Edge Guardian CLI
  *
  * Called from tuya_main.c during application startup.
  */
 void tuya_app_cli_init(void)
 {
     tal_cli_cmd_register(
         s_edge_cli_cmds,
         sizeof(s_edge_cli_cmds) / sizeof(s_edge_cli_cmds[0])
     );
 
     PR_NOTICE("SeedCore Edge Guardian CLI initialized");
 }
 