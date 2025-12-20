
# 🛡️ SeedCore Edge Guardian

> **Next-Generation AI Security Copilot powered by Tuya T5 AI + SeedCore Cloud Cortex**

**SeedCore Edge Guardian** is a neuro-symbolic cognitive edge node designed for high-stakes security environments. Built on the **Tuya T5 AI Development Board**, it transforms standard CCTV streams into actionable intelligence using local inference, seamless cloud synchronization, and real-time environmental control.

---

## 🚀 Built on TuyaOpen

Edge Guardian is built on top of **TuyaOpen**, Tuya’s open-source AI + IoT development platform powered by TuyaOS and production-proven across millions of devices.

* **TuyaOpen GitHub:** [https://github.com/tuya/TuyaOpen](https://github.com/tuya/TuyaOpen)
* **TuyaOpen Docs:** [https://tuyaopen.ai](https://tuyaopen.ai)
* **Supported hardware:** Tuya T5 series (Wi-Fi / BLE / AI)

**This project leverages TuyaOpen for:**

* **Secure Connectivity:** MQTT/HTTPS communication with the SeedCore Cloud Cortex.
* **AI Lifecycle:** Local inference execution on the T5-E1 Star-MC1 core.
* **Peripheral Management:** Hardware-abstracted control of PWM lighting and DVP camera interfaces.
* **OTA Updates:** Secure field deployment of new cognitive models.

> **Architecture Note:**  
> Tuya Cloud is used for secure device connectivity, DP-based actuation, OTA, and lifecycle management.  
> SeedCore Cloud Cortex (AWS) is responsible for **cross-device reasoning**, **energy-based decision routing**, and **explainable coordination** across rooms, roles, and time.
>
> This separation preserves Tuya's strengths at the device layer while enabling system-level intelligence beyond single-device automation.

---

## 🧠 System Architecture

Edge Guardian follows a "Planes of Control" design, decoupling high-level intelligence from low-level execution.

```text
┌──────────────────────────┐      ┌──────────────────────────┐
│   SeedCore Cloud Cortex  │◄────►│      AWS Cloud / App     │
│   (Context & Memory)     │      │   (Strategic Control)    │
└─────────────┬────────────┘      └─────────────┬────────────┘
              │                                 │
              │         Tuya Cloud / MQTT       │
              ▼                                 ▼
┌────────────────────────────────────────────────────────────┐
│                  SeedCore Edge Guardian (App)              │
│  (Local Inference - Vision/Voice - Real-time Response)     │
├────────────────────────────────────────────────────────────┤
│                  TuyaOpen / TuyaOS Framework               │
│  - Device OS   - Networking   - Security   - OTA / Lifecycle│
└──────────────────────────────┬─────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
        [T5-E1 AI Hardware]           [Peripherals]
        - 480MHz ARM M33F             - DVP CCTV Camera
        - 16MB PSRAM                  - PWM AI Lighting
        - AI NPU Accel                - Smart Relay/Switch

```

---

## 🛠️ Hardware Design & Pin Mapping

The hardware is centered around the **T5AI-Core (T5-E1 module)**. The pinmux configuration is optimized to avoid conflicts between the high-speed DVP camera interface and control peripherals.

### 📍 Conflict-Free Pin Configuration

| Component | Pin(s) | Function | Notes |
| --- | --- | --- | --- |
| **Camera Data** | P20–P27 | DVP D0–D7 | High-speed parallel bus |
| **Camera Sync** | P31, P32, P33 | HSYNC, VSYNC, PCLK | Dedicated CIS timing |
| **Camera I2C** | P19, P18 | SCL, SDA (I2C1) | Independent SCCB bus |
| **AI Light** | P9 | PWM | Dimmable security lighting |
| **AI Switch** | P6 | GPIO Input | Physical override button |
| **Relay** | P7 | GPIO Output | Electronic lock/Siren control |

> **Note:** All IO levels are 3.3V. Relays and high-power LEDs are driven via MOSFET/transistor isolation.

### 🧮 Memory & Performance Notes

* Camera frame buffers (e.g., 640×480 RGB565) are allocated in **external PSRAM (16MB)**.
* Internal SRAM (~640KB) is reserved for:
  * RTOS tasks
  * TuyaOS networking stack
  * Real-time control paths
* All camera DMA and AI inference buffers must avoid internal SRAM to prevent instability.

This design ensures stable real-time performance even under high event rates.

---

## 🏨 Flagship Scenario: Smart Hotel Night Shift

To demonstrate the capability of the Edge Guardian, we have implemented the **"Presidential Suite Incident"** demo.

* **Threat Detection:** AI detects unauthorized entry or prolonged loitering via the DVP camera.
* **Coordinated Actuation (via Tuya DPs):**
  * `switch` → Relay control (P7): secure service doors
  * `light_pwm` → PWM output (P9): corridor illumination / deterrent strobe
  * `event_type`, `anomaly_score` → reported upstream for audit and explanation
* **Cloud Escalation:** Real-time event telemetry is pushed to AWS via Tuya Cloud for human-in-the-loop intervention.

---

## 📦 Getting Started

### Prerequisites

* **Hardware:** Tuya T5-AI Core DevKit.
* **Toolchain:** `tos.py` (Tuya Operations System Python Tool).
* **SDK:** TuyaOpen C/C++ SDK.

> ⚠️ **Note:**  
> This repository contains **application-level code only**.  
> The TuyaOpen SDK is pulled as a dependency and must be initialized separately.

### Build & Flash

1. Clone the repository:
```bash
git clone https://github.com/youruser/edge-guardian.git
cd edge-guardian
git submodule update --init --recursive
```


2. Initialize the TuyaOpen environment:
```bash
./tos.py config

```


3. Compile the project:
```bash
./tos.py build apps/edge_guardian

```


4. Flash the firmware via Type-C:
```bash
./tos.py flash

```



---

## 🤝 Acknowledgments

* **Tuya Smart** for the T5-AI development hardware and TuyaOpen framework.
* **AWS** for the cloud infrastructure powering the SeedCore Cortex.

---

## 🏆 Why This Project Is Different

* Not a rule engine — a **coordination layer**
* Not reactive — **context-aware**
* Not cloud-heavy — **energy-guided escalation**
* Not device-centric — **hotel-wide unified state**

SeedCore Edge Guardian demonstrates how Tuya edge intelligence and cloud-scale reasoning can coexist to enable truly autonomous environments.

---

**[📄 Project Plan – Smart Hotel Edge Guardian](./docs/SeedCore_Edge_Guardian_Hotel.pdf)** | **[Hardware Schematics](https://www.google.com/search?q=./hw/SCHEMATICS.md)** | **[TuyaOpen Documentation](https://tuyaopen.ai)**
