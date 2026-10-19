#!/usr/bin/env bash
# LocalText Model Download & Verification Script
# Adheres to Section 7 and Section 14
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODELS_DIR="${HOME}/.local/share/localtext/models"
mkdir -p "${MODELS_DIR}"

echo "=== LocalText Model Acquisition ==="
echo "Target models directory: ${MODELS_DIR}"

# 1. Check disk space
AVAIL_KB=$(df -k "${MODELS_DIR}" | awk 'NR==2 {print $4}')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
echo "Available disk space: ${AVAIL_GB} GiB"

if [ "${AVAIL_GB}" -lt 15 ]; then
    echo "Warning: Less than 15 GiB free. Full models require ~10 GiB."
fi

# Baseline Rephrasing Model: Qwen3.5-9B Q6_K GGUF (~7.96 GB)
QWEN_URL="https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q6_K.gguf"
QWEN_TARGET="${MODELS_DIR}/Qwen3.5-9B-Q6_K.gguf"

# English Detector Model: Desklib DeBERTa v3 large (~1.74 GB)
DETECTOR_URL="https://huggingface.co/desklib/ai-text-detector-v1.01/resolve/main/model.safetensors"
DETECTOR_TARGET="${MODELS_DIR}/desklib_model.safetensors"

echo ""
echo "Select models to download:"
echo "1) Rephrasing Model: Qwen 3.5 9B Q6_K (~7.96 GB)"
echo "2) Detector Model: Desklib AI Detector v1.01 (~1.74 GB)"
echo "3) Both models (~9.7 GB)"
echo "4) Offline import existing local GGUF file"
echo "5) Exit"
echo ""

read -rp "Enter choice [1-5]: " CHOICE

case "${CHOICE}" in
    1)
        echo "Downloading Qwen 3.5 9B Q6_K GGUF..."
        curl -L --progress-bar -C - "${QWEN_URL}" -o "${QWEN_TARGET}"
        echo "✓ Qwen model saved to: ${QWEN_TARGET}"
        ;;
    2)
        echo "Downloading Desklib AI Detector safetensors..."
        curl -L --progress-bar -C - "${DETECTOR_URL}" -o "${DETECTOR_TARGET}"
        echo "✓ Detector model saved to: ${DETECTOR_TARGET}"
        ;;
    3)
        echo "Downloading Qwen 3.5 9B Q6_K GGUF..."
        curl -L --progress-bar -C - "${QWEN_URL}" -o "${QWEN_TARGET}"
        echo "Downloading Desklib AI Detector safetensors..."
        curl -L --progress-bar -C - "${DETECTOR_URL}" -o "${DETECTOR_TARGET}"
        echo "✓ Both models acquired successfully."
        ;;
    4)
        read -rp "Enter full path to local .gguf file: " LOCAL_PATH
        if [ -f "${LOCAL_PATH}" ]; then
            DEST="${MODELS_DIR}/$(basename "${LOCAL_PATH}")"
            ln -sf "${LOCAL_PATH}" "${DEST}"
            echo "✓ Linked ${LOCAL_PATH} -> ${DEST}"
        else
            echo "Error: File not found at ${LOCAL_PATH}"
            exit 1
        fi
        ;;
    5)
        echo "Exiting."
        exit 0
        ;;
    *)
        echo "Invalid selection."
        exit 1
        ;;
esac

echo "=== Model acquisition complete ==="
