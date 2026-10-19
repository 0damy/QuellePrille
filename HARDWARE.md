# Target Hardware Profile & Feasibility Assessment

**Assessment Date:** 19 October 2026  
**Operating System:** Arch Linux (rolling release, kernel `7.2.11-arch1-1`, x86_64)  
**Host Architecture:** Intel x86_64

---

## 1. Measured System Specifications

### 1.1 Processor (CPU)
- **Model:** Intel(R) Core(TM) Ultra 7 155H
- **Topology:** 1 socket, 16 physical cores, 22 logical threads
  - 6 Performance Cores (P-cores, hyperthreaded: 12 threads), max boost 4.8 GHz
  - 8 Efficient Cores (E-cores: 8 threads)
  - 2 Low-Power Efficient Cores (LP E-cores: 2 threads)
- **Caches:**
  - L1d: 544 KiB (14 instances)
  - L1i: 896 KiB (14 instances)
  - L2: 18 MiB (9 instances)
  - L3: 24 MiB (unified)
- **Key Vector & Instruction Extensions:**
  - `avx`, `avx2`, `fma`, `f16c`
  - `avx_vnni` (Vector Neural Network Instructions for INT8/INT16 inference)
  - `sha_ni`, `gfni`, `vaes`
  - Note: Intel Meteor Lake does not support AVX-512, but has full AVX2 + AVX-VNNI acceleration.

### 1.2 Memory & Swap (RAM)
- **Physical Memory (RAM):** 30 GiB usable (32 GB physical LPDDR5)
  - Used: ~13 GiB
  - Buff/Cache: ~20 GiB (including ~3.5 GiB shared)
  - Available: ~17 GiB
- **Swap:** 15.4 GiB `zram0` (compressed memory swap)
- **Memory Admission Policy (NFR-06):**
  - Minimum mandatory OS/application headroom: 6.0 GiB.
  - Safe maximum resident memory allocation for inference:
    $$\text{Max Safe Footprint} = \text{Available RAM (17 GiB)} - \text{Headroom (6 GiB)} \approx 11 \text{ GiB}$$
  - Uncontrolled swapping to `zram0` must be prevented because compressed RAM swap competes directly with physical RAM.

### 1.3 Graphics & Acceleration (GPU / Vulkan)
- **Controller:** Intel Corporation Meteor Lake-P [Intel Arc Graphics] (rev 08)
- **Driver:** Mesa 26.2.5-arch1.1 open-source driver (`DRIVER_ID_INTEL_OPEN_SOURCE_MESA`)
- **Vulkan Support:**
  - Device: `Intel(R) Arc(tm) Graphics (MTL)`
  - Vulkan Instance API: 1.4.363, Device API: 1.4.354
  - Extensions: `VK_KHR_wayland_surface`, `VK_KHR_external_memory`, compute shaders supported.
- **VRAM:** Unified memory architecture (UMA) sharing system RAM. Any allocation for GPU inference consumes system RAM.
- **Policy (NFR-05):** CPU inference is mandatory and the baseline. Vulkan acceleration is an optional comparison path; VRAM must not be double-counted against system RAM.

### 1.4 Storage & Partitions
- **Drive:** NVMe SSD (`/dev/nvme0n1p5`)
- **Partition Size:** 492 GiB
- **Free Space Available:** 236 GiB (50% use)
- **Assessment:** Ample disk space for local models (~10–20 GB), Python virtual environments, evaluation datasets, and test fixtures.

### 1.5 Desktop Environment & Display Session
- **Display Server:** Wayland (`XDG_SESSION_TYPE=wayland`, `WAYLAND_DISPLAY=wayland-1`)
- **Desktop Environment:** KDE Plasma 6 (kwin, wayland-native)
- **GUI Toolkit Support:** PySide6 / Qt6 widgets run natively via Wayland integration (`QT_QPA_PLATFORM=wayland;xcb`).

### 1.6 Toolchain & Compilers
- **Compilers:**
  - GCC (`gcc`, `g++`) installed
  - Clang (`clang`, `clang++`) installed
  - CMake (`cmake`) installed
  - Rust/Cargo (`cargo`) installed
  - Ninja: available via system or build tools
- **System Python:** Python 3.14.8
  - Isolated venv required to prevent pollution of system packages.
  - Core packaging tools (`pip`, `setuptools`, `wheel`, `venv`) available.

---

## 2. Model Feasibility & Selection Decision

### 2.1 Rephrasing Candidate: Baseline vs Higher-Capacity
1. **`Qwen/Qwen3.5-9B` (GGUF Q6_K, ~7.96 GB file size)**
   - **RAM Footprint:** ~8.0 GB weights + ~1.5–2.5 GB context/KV cache at 4,096 tokens $\approx 9.5\text{--}10.5$ GiB peak.
   - **Admission Check:** $10.5\text{ GiB} \le 11\text{ GiB}$ (17 GiB available minus 6 GiB headroom).
   - **Feasibility:** **FEASIBLE**. This is selected as the primary baseline for the local rewrite pipeline.
   - **Compute:** Fast multi-threaded CPU inference via AVX2/AVX-VNNI (16 cores/22 threads).

2. **`Qwen/Qwen3.6-27B` (GGUF Q4_K_M, ~19.1 GB file size)**
   - **RAM Footprint:** ~19.1 GB weights + ~3–4 GB context/KV cache $\approx 22\text{--}24$ GiB peak.
   - **Admission Check:** Exceeds currently available 17 GiB RAM and violates NFR-06 (which requires leaving 6 GiB free for OS). Loading this would force 8–12 GiB into `zram0`, thrashing CPU and memory.
   - **Feasibility:** **UNFEASIBLE in current state** (AT-13). Must be refused by memory admission check with a clear notification to the user, offering the tested 9B baseline.

### 2.2 Detection Candidates
1. **`desklib/ai-text-detector-v1.01` (English Baseline)**
   - **Architecture:** DeBERTa-v3-large base with custom masked mean pooling and single-logit linear head.
   - **Format:** PyTorch safetensors (~1.74 GB).
   - **RAM Footprint:** ~2.0–2.5 GiB in float32 CPU inference mode.
   - **Feasibility:** **FEASIBLE**. Fits easily within RAM headroom.
   - **Loader Audit:** Must load custom pooled classification head without randomly initializing generic classification layers (AT-12).

2. **`danibor/oculus-v2.0-multilingual` (Experimental Multilingual / German)**
   - **Architecture:** XLM-RoBERTa-large with custom pooling and classification head.
   - **Format:** PyTorch safetensors (~2.2 GB).
   - **RAM Footprint:** ~2.5–3.0 GiB in float32 CPU inference mode.
   - **Feasibility:** **FEASIBLE** for testing. Labeled strictly as experimental until independent German validation passes (DET-10).

---

## 3. Concurrency & Scheduling Policy
- In accordance with Section 6, the system runs at most **one heavy inference job at a time** (either detection or rephrasing).
- Total peak inference memory:
  - Rephrasing: $\approx 10.5$ GiB
  - Detection: $\approx 2.5$ GiB
- Because both models together could reach $13$ GiB (tight against the 11 GiB safe allocation), the controller will unload or idle the non-active model when switching tasks or when memory admission indicates headroom below 6 GiB.
