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
 #include "edge_guardian.h"
 #include "edge_switch_sim.h"
 #include "edge_light_sim.h"
 #include "edge_cam_sim.h"
 #include <stdlib.h>
 #include <string.h>
 
 /* External Tuya CLI helpers */
 extern void tal_kv_cmd(int argc, char *argv[]);
 extern void netmgr_cmd(int argc, char *argv[]);

 /* Forward declarations */
 static void edge_help_cmd(int argc, char *argv[]);
 static void edge_report_cmd(int argc, char *argv[]);
 
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
  * SeedCore: Switch Simulation Commands
  * ========================================================= */

 /**
  * @brief Unified edge command handler (switch/relay/help/report)
  *
  * Usage:
  *   edge switch press      - Simulate button press
  *   edge switch release    - Simulate button release
  *   edge switch long       - Simulate long press
  *   edge relay on          - Turn relay ON
  *   edge relay off         - Turn relay OFF
  *   edge help              - Show help banner
  *   edge report            - Report all states
  */
 static void edge_unified_cmd(int argc, char *argv[])
 {
     if (argc < 2) {
         PR_NOTICE("usage: edge switch <press|release|long>");
         PR_NOTICE("       edge relay <on|off>");
         return;
     }

     // argv[0] = "edge", argv[1] = subcommand ("switch" or "relay")
     if (strcmp(argv[1], "switch") == 0) {
         if (argc < 3) {
             PR_NOTICE("usage: edge switch <press|release|long>");
             return;
         }
         if (strcmp(argv[2], "press") == 0) {
             edge_switch_sim_press();
         } else if (strcmp(argv[2], "release") == 0) {
             edge_switch_sim_release();
         } else if (strcmp(argv[2], "long") == 0) {
             edge_switch_sim_long_press();
         } else {
             PR_NOTICE("usage: edge switch <press|release|long>");
         }
     } else if (strcmp(argv[1], "relay") == 0) {
         if (argc < 3) {
             PR_NOTICE("usage: edge relay <on|off>");
             return;
         }
         if (strcmp(argv[2], "on") == 0) {
             edge_switch_sim_relay_on();
         } else if (strcmp(argv[2], "off") == 0) {
             edge_switch_sim_relay_off();
         } else {
             PR_NOTICE("usage: edge relay <on|off>");
         }
     } else if (strcmp(argv[1], "help") == 0) {
         edge_help_cmd(argc, argv);
     } else if (strcmp(argv[1], "report") == 0) {
         edge_report_cmd(argc, argv);
     } else {
         PR_NOTICE("usage: edge switch <press|release|long>");
         PR_NOTICE("       edge relay <on|off>");
         PR_NOTICE("       edge help");
         PR_NOTICE("       edge report");
     }
 }

 /**
  * @brief Control AI Light simulation
  *
  * Usage:
  *   edge_light on                    - Turn light ON
  *   edge_light off                   - Turn light OFF
  *   edge_light brightness <0-100>   - Set brightness
  *   edge_light rgb <r> <g> <b>      - Set RGB color (0-255 each)
  *   edge_light report                - Report current state
  */
 static void edge_light_cmd(int argc, char *argv[])
 {
     if (argc < 2) {
         PR_NOTICE("usage: edge_light <on|off|brightness|rgb|report>");
         PR_NOTICE("  brightness: edge_light brightness <0-100>");
         PR_NOTICE("  rgb: edge_light rgb <r> <g> <b> (0-255 each)");
         return;
     }

     // argv[0] = "edge_light", argv[1] = subcommand
     if (strcmp(argv[1], "on") == 0) {
         edge_light_sim_set_on(true);
     } else if (strcmp(argv[1], "off") == 0) {
         edge_light_sim_set_on(false);
     } else if (strcmp(argv[1], "brightness") == 0) {
         if (argc < 3) {
             PR_NOTICE("usage: edge_light brightness <0-100>");
             return;
         }
         uint8_t brightness = (uint8_t)atoi(argv[2]);
         edge_light_sim_set_brightness(brightness);
     } else if (strcmp(argv[1], "rgb") == 0) {
         if (argc < 5) {
             PR_NOTICE("usage: edge_light rgb <r> <g> <b> (0-255 each)");
             return;
         }
         uint8_t r = (uint8_t)atoi(argv[2]);
         uint8_t g = (uint8_t)atoi(argv[3]);
         uint8_t b = (uint8_t)atoi(argv[4]);
         edge_light_sim_set_rgb(r, g, b);
     } else if (strcmp(argv[1], "report") == 0) {
         edge_light_sim_report_state();
     } else {
         PR_NOTICE("usage: edge_light <on|off|brightness|rgb|report>");
     }
 }

 /**
  * @brief Trigger camera simulation events
  *
  * Usage:
  *   edge_camera trigger motion   - Trigger motion detection
  *   edge_camera trigger person   - Trigger person detection
  *   edge_camera trigger anomaly  - Trigger anomaly detection
  */
 static void edge_camera_cmd(int argc, char *argv[])
 {
     if (argc < 3 || strcmp(argv[1], "trigger") != 0) {
         PR_NOTICE("usage: edge_camera trigger <motion|person|anomaly>");
         return;
     }

     // argv[0] = "edge_camera", argv[1] = "trigger", argv[2] = event type
     if (strcmp(argv[2], "motion") == 0) {
         edge_cam_sim_trigger_event(EDGE_CAM_EVENT_MOTION);
     } else if (strcmp(argv[2], "person") == 0) {
         edge_cam_sim_trigger_event(EDGE_CAM_EVENT_PERSON);
     } else if (strcmp(argv[2], "anomaly") == 0) {
         edge_cam_sim_trigger_event(EDGE_CAM_EVENT_ANOMALY);
     } else {
         PR_NOTICE("usage: edge_camera trigger <motion|person|anomaly>");
     }
 }

 /* =========================================================
  * SeedCore: Help & Status Commands
  * ========================================================= */

 /**
  * @brief Display help banner with all available commands
  */
 static void edge_help_cmd(int argc, char *argv[])
 {
     PR_NOTICE("========================================");
     PR_NOTICE("Edge Guardian CLI Commands");
     PR_NOTICE("========================================");
     PR_NOTICE("");
     PR_NOTICE("Switch/Relay:");
     PR_NOTICE("  edge switch press|release|long");
     PR_NOTICE("  edge relay on|off");
     PR_NOTICE("");
     PR_NOTICE("Light Control:");
     PR_NOTICE("  edge_light on|off");
     PR_NOTICE("  edge_light brightness <0-100>");
     PR_NOTICE("  edge_light rgb <r> <g> <b>");
     PR_NOTICE("  edge_light report");
     PR_NOTICE("");
     PR_NOTICE("Camera Events:");
     PR_NOTICE("  edge_camera trigger motion|person|anomaly");
     PR_NOTICE("");
     PR_NOTICE("Status:");
     PR_NOTICE("  edge report  - Report all DP states");
     PR_NOTICE("  edge help    - Show this help");
     PR_NOTICE("");
     PR_NOTICE("========================================");
 }

 /**
  * @brief Report all simulated device states
  */
 static void edge_report_cmd(int argc, char *argv[])
 {
     PR_NOTICE("========================================");
     PR_NOTICE("Edge Guardian Status Report");
     PR_NOTICE("========================================");
     
     // Switch/Relay state
     PR_NOTICE("Switch/Relay:");
     PR_NOTICE("  Relay: %s", edge_switch_sim_get_relay_state() ? "ON" : "OFF");
     
     // Light state
     PR_NOTICE("Light:");
     PR_NOTICE("  State: %s", edge_light_sim_get_on() ? "ON" : "OFF");
     PR_NOTICE("  Brightness: %d%%", edge_light_sim_get_brightness());
     uint8_t r, g, b;
     edge_light_sim_get_rgb(&r, &g, &b);
     PR_NOTICE("  RGB: (%d, %d, %d)", r, g, b);
     
     // Camera (no state to report, but show it's active)
     PR_NOTICE("Camera:");
     PR_NOTICE("  Simulation: Active (synthetic frames)");
     
     PR_NOTICE("========================================");
     
     // Also report all states to Tuya Cloud
     edge_light_sim_report_state();
     edge_guardian_set_switch(edge_switch_sim_get_relay_state());
 }
 
 /* =========================================================
  * CLI Command Table
  * ========================================================= */
 
 static cli_cmd_t s_edge_cli_cmds[] = {
     /* SeedCore-specific - Switch/Relay (legacy) */
     { .name = "edge_switch", .func = edge_switch_cmd, .help = "control edge relay: on/off (legacy)" },
     
     /* SeedCore-specific - Unified edge command */
     { .name = "edge",        .func = edge_unified_cmd, .help = "edge switch/relay/help/report commands" },
     
     /* SeedCore-specific - Light */
     { .name = "edge_light",  .func = edge_light_cmd,  .help = "control AI light: on/off/brightness/rgb" },
     
     /* SeedCore-specific - Camera */
     { .name = "edge_camera", .func = edge_camera_cmd, .help = "trigger camera events: motion/person/anomaly" },
     
     /* SeedCore-specific - Help & Status */
     { .name = "edge_help",   .func = edge_help_cmd,   .help = "show help banner with all commands" },
     { .name = "edge_report", .func = edge_report_cmd, .help = "report all simulated device states" },
 
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
 