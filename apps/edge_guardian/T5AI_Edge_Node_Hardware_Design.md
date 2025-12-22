# T5AI Edge Node Hardware & Pin Configuration Documentation

**Target Platform:** Tuya T5-AI Core (T5-E1 Module)  
**Use Case:** AI Camera (CCTV) + AI Light + AI Switch (Edge AI + Cloud Control)

## 1. Overview

This document describes the hardware pin mapping, electrical constraints, and firmware considerations for building an AI-enabled edge node based on the Tuya T5-AI Core (T5-E1) module.

The design integrates:

* 📷 CCTV / AI Camera (Parallel DVP)
* 💡 AI Light (PWM / RGB)
* 🔘 AI Switch (Button + Relay)
* ☁️ Tuya Cloud for control, monitoring, and OTA
* 🧠 On-device AI inference using PSRAM

The solution is optimized to:

* Avoid pin-multiplexing conflicts
* Respect T5 electrical limits
* Be stable for long-running AI workloads
* Comply with TuyaOS and TuyaOpen best practices

## 2. Hardware Platform Summary

### Core Module

* **SoC:** Tuya T5-E1
* **CPU:** Dual-core MCU with AI acceleration
* **Internal SRAM:** ~640 KB
* **External PSRAM:** 16 MB
* **Operating Voltage:** 3.3 V
* **GPIO Voltage Tolerance:** ❌ Not 5V tolerant

### Header Reference

* **Header:** HDR254-1x22-M-H890
* **Logic Level:** 3.3 V on all GPIO (Pxx)

## 3. Power & Electrical Design (Critical)

### Power Pins

| Pin | Signal | Usage |
|-----|--------|-------|
| Pin 1 | VDD_3V3 | Main logic supply (3.3 V) |
| Pin 21 | VCC_5V | USB / external 5 V input |
| Pin 22 | GND | Ground |

### Electrical Rules (Must Follow)

⚠️ **Never connect 5 V to any Pxx GPIO**

* All GPIO operate at 3.3 V logic
* Relays, motors, LED strips must use external drivers
* Camera I/O must be 3.3 V compatible

**Failure to follow these rules can permanently damage the T5 SoC.**

## 4. CCTV / AI Camera Design (Parallel DVP)

### Design Rationale

The T5-E1 provides a hardware CIS (CMOS Image Sensor) interface for parallel cameras. However, incorrect pin usage can cause:

* Camera initialization failure
* I2C bus lockups
* Unstable video capture

The design below eliminates all pin-mux conflicts.

### 4.1 Camera Control Interface (SCCB / I2C)

To avoid conflicts with DVP data lines:

* ❌ Do not use I2C0 (P20/P21)
* ✅ Use I2C1 for camera configuration

| Function | Pin |
|----------|-----|
| Camera SDA | P18 |
| Camera SCL | P19 |

This isolates camera configuration traffic from high-speed video data.

### 4.2 Camera Data & Sync (DVP)

The T5-E1 exposes dedicated CIS pins optimized for camera input.

| Camera Signal | Pin | Notes |
|---------------|-----|-------|
| D0–D7 | P20–P27 | Parallel pixel data |
| HSYNC | P31 | Line sync |
| VSYNC | P32 | Frame sync |
| PCLK | P33 | Pixel clock |
| XCLK | P30 | Sensor master clock |

This mapping:

* Matches Tuya reference designs
* Supports QVGA / VGA reliably
* Avoids SPI / QSPI / I2C conflicts

### 4.3 Camera Power

Most supported camera modules (e.g. OV2640):

* **IO voltage:** 3.3 V
* **Core voltage:** internally regulated on module

Always verify your camera board includes onboard regulators.

## 5. AI Light Design (PWM / RGB)

### 5.1 PWM-Controlled Light (Recommended)

| Function | Pin |
|----------|-----|
| PWM Output | P9 (PWM0:3) |

**Advantages:**

* Hardware-timed PWM
* Flicker-free dimming
* No interference with camera

**Example (TuyaOS):**

```c
tkl_pwm_init(P9, 1000);
tkl_pwm_set_duty(P9, duty);
```

### 5.2 RGB / Addressable LEDs (Optional)

* **P8:** GPIO / PWM0:2 (bit-banged WS2812)
* **P16:** SPI0_MOSI (higher timing accuracy)

## 6. AI Switch Design (Button + Relay)

### 6.1 Button Input

| Function | Pin |
|----------|-----|
| Button Input | P6 |

**Configuration:**

* Enable internal pull-up
* Software debounce recommended

```c
tkl_gpio_init(P6, TUYA_GPIO_IN_PULLUP);
```

### 6.2 Relay Output (Safety-Critical)

| Function | Pin |
|----------|-----|
| Relay Control | P7 |

⚠️ **Do not drive relay coils directly from GPIO**

**Required external components:**

* Logic-level MOSFET (e.g. AO3400 / 2N7002)
* Flyback diode across relay coil
* Separate 5 V relay supply (via Pin 21)

This prevents:

* Overcurrent damage
* Brown-outs
* Random MCU resets

## 7. Final Conflict-Free Pin Mapping (Authoritative)

| Module | Pins | Function |
|--------|------|----------|
| Camera I2C | P18, P19 | SDA / SCL (I2C1) |
| Camera Data | P20–P27 | D0–D7 |
| Camera Sync | P31, P32, P33 | HSYNC / VSYNC / PCLK |
| Camera Clock | P30 | CIS_XCLK |
| AI Light | P9 | PWM |
| Button | P6 | GPIO IN |
| Relay | P7 | GPIO OUT (via MOSFET) |
| 3.3 V | Pin 1 | Logic Power |
| 5 V | Pin 21 | Relay / LED Power |
| GND | Pin 22 | Ground |

✅ Zero pin conflicts  
✅ Camera + PWM + relay coexist safely  
✅ TuyaOS-compliant

## 8. Firmware & Memory Considerations

### 8.1 Pinmux Configuration

All camera, PWM, and GPIO pins must be explicitly configured in:

* `board_config.c`
* or TuyaOpen BSP pinmux definitions

Missing pinmux configuration may result in:

* No camera frames
* PWM jitter
* Silent device resets

### 8.2 PSRAM Usage (Very Important)

The T5-E1 internal SRAM is not sufficient for camera buffers.

**Example:**

* VGA RGB565 frame ≈ 600 KB

👉 **Always allocate camera buffers in external PSRAM:**

```c
void *frame_buf = tkl_system_psram_malloc(size);
```

**Never allocate frame buffers on:**

* Stack
* Internal heap

## 9. System Architecture Summary

```text
[CCTV Camera]
    │ (DVP)
    ▼
[T5AI Core – T5-E1]
    ├── AI Inference (PSRAM)
    ├── PWM → AI Light
    ├── GPIO → Relay / Switch
    └── Tuya Cloud → App / API / LLM
```

This architecture supports:

* Smart home / hotel
* AI security
* Edge AI + cloud hybrid control
* Hackathon and commercialization paths

## 10. Hackathon Readiness Checklist

* ✅ Pin-mux conflict free
* ✅ Electrical safety ensured
* ✅ Camera stable at runtime
* ✅ PSRAM-safe AI buffers
* ✅ Tuya Cloud integration ready
* ✅ CES / demo-day friendly

## References

* Tuya T5-E1 Module Datasheet
* TuyaOpen SDK Documentation
* Tuya T5AI Board Review: https://www.youtube.com/watch?v=sXizFoUFPm8
