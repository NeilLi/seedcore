
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
* **SDK:** TuyaOpen C/C++ SDK (cloned separately).

> ⚠️ **Important:**  
> Tuya apps can **only be built inside the TuyaOpen workspace** using `tos.py`.  
> This repository contains **application-level code only** and must be linked into TuyaOpen for building.

### Development Model

Edge Guardian follows a **symlink-based development model**:

* **SeedCore repo** (`/path/to/seedcore/apps/edge_guardian`) = source of truth, product logic, docs
* **TuyaOpen workspace** (`/path/to/TuyaOpen`) = build system, SDK root, flash environment

This approach ensures:
* ✅ No code duplication
* ✅ Git stays clean
* ✅ Single source of truth
* ✅ Native TuyaOpen build compatibility

### Setup Instructions

#### Step 1: Clone TuyaOpen SDK

```bash
git clone https://github.com/tuya/TuyaOpen.git
cd TuyaOpen
```

#### Step 2: Link Edge Guardian into TuyaOpen

Create a symbolic link so TuyaOpen sees your app as a native app:

```bash
cd /path/to/TuyaOpen/apps
cp -r /../../seedcore/apps/edge_guardian edge_guardian
```

**Resulting structure:**
```text
/path/to/
├── seedcore/
│   └── apps/
│       └── edge_guardian/          ← Source of truth
│           ├── src/
│           ├── CMakeLists.txt
│           └── README.md
│
└── TuyaOpen/
    ├── apps/
    │   └── edge_guardian →  🔗 symlink to seedcore
    └── tos.py
```

#### Step 3: Navigate to Project Directory

Go to the Edge Guardian project directory:

```bash
cd /path/to/TuyaOpen/apps/edge_guardian
```

#### Step 4: Configure Project

Run `tos.py config choice` from the project directory to select the configuration file for your hardware. For Tuya T5-AI development boards, select `T5AI.config`:

```bash
tos.py config choice
```

You'll see a menu like:
```
[INFO]: Running tos.py ...
[INFO]: Fullclean success.
--------------------
1. LN882H.config
2. EWT103-W15.config
3. Ubuntu.config
4. ESP32-C3.config
5. ESP32-S3.config
6. ESP32.config
7. T3.config
8. T5AI.config    ← Select this for T5-AI boards
9. T2.config
10. BK7231X.config
--------------------
Input "q" to exit.
Choice config file:
```

#### Step 5: Build the Application

Build the project using `tos.py build` from the project directory:

```bash
tos.py build
```

The build output will show the generated binary path:
```
[INFO]: ******************************
[INFO]: /xxx/TuyaOpen/apps/edge_guardian/.build/bin/edge_guardian_QIO_1.0.0.bin
[INFO]: ******************************
[INFO]: ******* Build Success ********
[INFO]: ******************************
```

#### Step 6: Flash Firmware

Flash the firmware via Type-C:

```bash
tos.py flash
```

#### Step 7: Monitor Output

Monitor device output:

```bash
tos.py monitor
```

**Note:** To clear build cache, use `./tos.py clean` (standard) or `./tos.py clean -f` (force deep cleanup).

> 📖 **Reference:** [TuyaOpen Project Compilation Documentation](https://tuyaopen.ai/docs/quick-start/project-compilation)

### App Template Reference

Edge Guardian combines patterns from two TuyaOpen reference apps:

| Source App               | Purpose                  | Use For                        |
| ------------------------ | ------------------------ | ------------------------------ |
| `tuya_cloud/switch_demo` | IoT DP / relay / button  | **Edge Guardian control plane** |
| `tuya.ai/your_chat_bot` | AI task loop / inference | **Edge Guardian cognition plane** |

**Conceptual components to adopt:**

From **`switch_demo`**:
* `tuya_main.c` structure
* DP registration & callbacks
* Network / activation flow
* `reset_netcfg.c`

From **`your_chat_bot`**:
* AI task thread
* Model loading
* PSRAM allocation
* Event → inference → action loop

### Application Structure

The Edge Guardian app follows this modular structure:

```text
src/
├── tuya_main.c          # System entry + lifecycle
├── edge_guardian.c     # Core AI logic
├── edge_guardian.h
├── camera_dvp.c        # Camera init + frame capture
├── light_ctrl.c        # PWM light control
├── relay_ctrl.c        # Relay / switch logic
├── cli_cmd.c           # Debug CLI
├── reset_netcfg.c      # Network reset utilities
└── tuya_config.h       # Configuration constants
```

### Development Evolution Path

**Phase 1** (Foundation):
* Based on `switch_demo`
* Button → relay → PWM light
* Cloud DP working

**Phase 2** (Camera Pipeline):
* Add camera init (DVP)
* Capture frames, discard (pipeline test)

**Phase 3** (AI Integration):
* Add AI loop (from `your_chat_bot`)
* Run inference on reduced frame
* Trigger relay/light on detection

**Phase 4** (Cloud Integration):
* Event → Tuya Cloud → AWS → SeedCore
* Full hotel-wide coordination



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

**[📄 Project Plan – Smart Hotel Edge Guardian](./SeedCore_Edge_Guardian_Hotel.pdf)** | **[Hardware Schematics](https://www.google.com/search?q=./hw/SCHEMATICS.md)** | **[TuyaOpen Documentation](https://tuyaopen.ai)**
