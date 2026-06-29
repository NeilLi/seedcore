# C2PA Cryptographic Content Provenance Architecture Reference

**Date:** 2026-06-29  
**Status:** Architecture Reference  
**Scope:** Media Security, Cryptographic Chain of Custody, and Provenance Verification  

---

## 1. Executive Summary

The **C2PA (Coalition for Content Provenance and Authenticity)** technical specification shifts media security away from fragile, post-hoc "detection" (guessing if pixels are fake) and maps it directly to a **cryptographic chain of custody**.

Instead of adding a visual watermark that can be easily cropped out, C2PA embeds or links an immutable, multi-layered data structure that explicitly tracks the file's lineage from the lens/generator to the screen.

---

## 2. Core Architecture: The Manifest Store

At the center of C2PA is the **Manifest Store**, a sequence of historical records injected directly into the media file’s metadata container. The underlying container format varies by media type:

*   **JUMBF (JPEG Universal Metadata Box Format)** boxes for JPEGs and WebPs.
*   **Dedicated atoms/boxes** for MP4s, audio (e.g., MP3/AAC), and PDFs.

The manifest store functions like a git commit log. When an image is captured on a C2PA-enabled camera (such as a Leica M11-P or a device using an internal Titan M2 chip like the Google Pixel 10), it writes the initial manifest. When that file is edited in Photoshop or run through a generative model, a *new* manifest is added to the store, referencing the older manifest as an **Ingredient**. The most recent entry is always designated as the **Active Manifest**.

```text
┌───────────────────────────────────────────────────────────────┐
│ FILE CONTAINER (JPEG / MP4)                                   │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ MANIFEST STORE                                            │ │
│ │ ┌───────────────────┐     ┌─────────────────────────────┐ │ │
│ │ │ Ingredient (v1)   │ ──► │ Active Manifest (v2)        │ │ │
│ │ │ (Camera Capture)  │     │ (AI Composite/Edit)         │ │ │
│ │ └───────────────────┘     │ ─ Assertions (Actions, AI)  │ │ │
│ │                           │ ─ The Claim (hashes)        │ │ │
│ │                           │ ─ Claim Signature (X.509)   │ │ │
│ │                           └─────────────────────────────┘ │ │
│ └───────────────────────────────────────────────────────────┘ │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ PIXEL DATA / AUDIO ACCELERATOR TENSORS                     │ │
│ └───────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Anatomy of a Single Manifest

A single C2PA manifest is encoded as high-efficiency binary data in **CBOR** (Concise Binary Object Representation) format. It consists of three tightly coupled components:

### A. Assertions (The Facts)
Assertions are individual, declarative statements of fact regarding the event or asset. The specification standardizes dozens of assertion schemas, including:
*   `c2pa.actions`: Explicit records of what took place (e.g., `created`, `cropped`, `color_adjusted`, or `metadata_added`).
*   `c2pa.ai_disclosure`: Under the updated IPTC standards, this injects explicit metadata tracking fields such as `AISystemUsed`, `AISystemVersionUsed`, and `AIPromptWriterName`.
*   `c2pa.thumbnail`: A low-resolution JPEG of the asset *at that exact step in history*. This prevents a bad actor from replacing the pixel body of a real photo with completely different fake imagery while preserving the metadata.

### B. The Claim (The Binding Dictionary)
The Claim acts as the internal inventory ledger. It collects the cryptographic SHA-256 hashes of every single Assertion inside the manifest, alongside a critical piece of architecture known as the **Hard Binding**.

> **The Hard Binding:** The creator tool calculates a SHA-256 hash over the actual raw pixel, video, or audio byte payload of the parent file. This hash is written directly into the Claim. If an adversary attempts to alter even a single byte of the picture to change a detail, the recalculated file hash will mismatch the hard-binding hash, instantly invalidating the entire manifest chain.

### C. The Claim Signature (The Trust Anchor)
To prevent someone from simply generating a fake manifest with fabricated assertions, the Claim dictionary must be signed.
1.  The hashing engine calculates a hash across the entire Claim structure.
2.  The signing application uses Public Key Infrastructure (PKI)—specifically **X.509 digital certificates**, the same standard securing global HTTPS traffic.
3.  The application encrypts the Claim hash using its unique **Private Key**, producing the **Claim Signature**.
4.  The manifest embeds the corresponding **Public Key** and the complete **Certificate Chain** leading back to a root Certificate Authority (CA) recognized on the official **C2PA Trust List**.

---

## 4. The Validation Pipeline

When a compliant browser, social media platform, or operating system inspects a file containing Content Credentials, it executes a strict, multi-step deterministic validation algorithm:

```text
[Target Asset Uploaded]
         │
         ▼
[Step 1: Parse JUMBF / Container Atoms] ──► Extract Manifest Store
         │
         ▼
[Step 2: Recalculate File Byte Hash] ────► Compare with Active Manifest's Hard Binding
         │                                  (Catches Pixel Tampering)
         ▼
[Step 3: Decrypt Claim Signature] ──────► Verify against embedded Public Key
         │                                  (Confirms Manifest integrity)
         ▼
[Step 4: Trace X.509 Certificate Chain] ─► Verify Root CA exists on the C2PA Trust List
         │                                  (Confirms Signer Identity)
         ▼
[Step 5: Verify Independent Timestamp] ──► Query Trusted TSA to confirm certificate validity window
         │
         ▼
[Asset Verified: Render Content Credentials Tooltip]
```

---

## 5. Engineering Vulnerabilities & Countermeasures

While C2PA provides an exceptionally robust framework for verified provenance, the ecosystem is actively solving two technical limitations:

### A. The Strip Attack
*   **Vulnerability:** C2PA is an *additive* metadata standard. It lives inside the data headers of the file container. If an asset is opened in a legacy, non-compliant photo editor, or processed by an unaligned social network, the software may strip out the JUMBF data structures when saving. The file still opens normally, but its history is completely erased.
*   **Countermeasure:** Labs are deploying **Soft-Binding** implementations. If the metadata is stripped, a forensic watermarking engine (like Google's SynthID) can scan the pixel array, read a hidden identifier, query an open cloud registry, and dynamically re-anchor the missing manifest store back to the asset.

### B. The First-Mile Problem
*   **Vulnerability:** C2PA proves *which* device or model generated a piece of content, but it cannot verify intent. If a physical camera with a secure hardware chip takes a photo of a high-resolution deepfake displayed on a flat-screen monitor, C2PA will successfully verify the image as a genuine, untampered physical photograph. It verifies the *authenticity of the file capture*, not absolute objective truth.

---

## 6. External References

*   C2PA Technical Specification: <https://c2pa.org/specifications/>
*   LeRobotDataset v3.0: <https://huggingface.co/docs/lerobot/en/lerobot-dataset-v3>
*   rosbag2: <https://github.com/ros2/rosbag2>
*   NVIDIA Isaac Lab: <https://developer.nvidia.com/isaac/lab>
