"""Command-Line Interface for LocalText.

Allows immediate, direct execution from a user's perspective for detection,
rephrasing, difference visualization, and system health status.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from localtext.config import get_models_dir, get_xdg_data_dir
from localtext.contracts import (
    ChangeStrength,
    DetectorLabel,
    JobState,
    RephraseMode,
    RewriteRequest,
    TargetBlock,
    TextSpan,
)
from localtext.detection.pipeline import DetectionPipeline
from localtext.inference.job_controller import JobController
from localtext.inference.memory_guard import MemoryGuard
from localtext.rephrase.chunker import DocumentChunker
from localtext.rephrase.diff import TextDiffEngine
from localtext.rephrase.pipeline import RephrasePipeline, assemble_rewrite
from localtext.inference.ollama_client import OllamaHttpClient
from localtext.storage.document_io import DocumentIO


def cmd_status() -> None:
    """Display real system memory, hardware feasibility, and model status."""
    guard = MemoryGuard()
    avail_bytes = guard.get_available_memory_bytes()
    avail_gib = avail_bytes / (1024**3)

    print("=== LocalText System & Hardware Status ===")
    print(f"OS Available RAM: {avail_gib:.2f} GiB (Mandatory Headroom Reserve: 6.0 GiB)")
    print(f"Models Directory: {get_models_dir()}")
    print(f"Data Directory:   {get_xdg_data_dir()}\n")

    print("Model Admission Checks:")
    for profile in ["qwen-9b-q6k", "qwen-27b-q4km", "desklib-v1.01-en", "oculus-v2.0-multi"]:
        decision = guard.check_admission(profile)
        status = "ALLOWED" if decision.allowed else "REFUSED"
        print(f"  • [{status:7s}] {profile:18s} -> {decision.message}")


def cmd_detect(args: argparse.Namespace) -> None:
    """Run AI text detection on text or file."""
    if args.file:
        text, _ = DocumentIO.read_file(Path(args.file))
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    pipeline = DetectionPipeline()
    result = pipeline.run_detection(
        job_id="cli-detect",
        revision=1,
        text=text,
        language=args.language,
    )

    print("\n=== LocalText Detection Result ===")
    print(f"Status:             {result.label.value}")
    if result.score is not None:
        print(f"Model Score:        {result.score:.1f} / 100")
    else:
        print("Model Score:        N/A (Insufficient text or unvalidated profile)")
    if result.raw_model_score is not None:
        print(f"Raw model signal:   {result.raw_model_score:.1f}/100 (uncalibrated; not authorship probability)")
    print(f"Language:           {result.language}")
    print(f"Analyzed Coverage:  {result.analyzed_coverage_ratio * 100:.1f}%")
    print(f"Explanation:        {result.score_semantics}")
    print(f"Validation Status:  {result.validation_status.value}")
    print(f"Execution Timing:   {result.timings_ms.get('total_ms', 0):.1f} ms\n")


def cmd_rephrase(args: argparse.Namespace) -> None:
    """Run text rephrasing on text or file."""
    if args.file:
        text, _ = DocumentIO.read_file(Path(args.file))
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    mode = RephraseMode(args.mode.lower())
    strength = ChangeStrength(args.strength.lower())
    frozen = [w.strip() for w in args.freeze.split(",")] if args.freeze else []

    chunker = DocumentChunker()
    blocks = chunker.create_target_blocks(text)

    req = RewriteRequest(
        job_id="cli-rephrase",
        snapshot_revision=1,
        model_profile_id=args.model,
        mode=mode,
        strength=strength,
        custom_style=args.custom or "",
        target_blocks=tuple(blocks),
    )

    pipeline = RephrasePipeline()

    client = OllamaHttpClient(model=args.model)
    try:
        result = pipeline.run_rephrase(
            request=req,
            generator_fn=lambda prompt, system: client.generate_completion(prompt, system),
            language=args.language,
            user_frozen_words=frozen,
        )
    finally:
        client.close()

    print("\n=== LocalText Rephrase Output ===")
    full_output = assemble_rewrite(text, blocks, result)
    print(full_output)
    print("\n--- Summary ---")
    print(f"Status:         {result.status.value}")
    print(f"Blocks:         {len(result.candidate_blocks)}")
    if result.warnings:
        print(f"Warnings:       {result.warnings}")
    if result.failed_checks:
        print(f"Failed Checks:  {result.failed_checks}")
    print(f"Execution Time: {result.timings_ms.get('total_ms', 0):.1f} ms")

    if args.output:
        out_path = Path(args.output)
        DocumentIO.atomic_save(out_path, full_output, allow_overwrite=True)
        print(f"Exported to:    {out_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="localtext",
        description="LocalText: Private AI text detection and rephrasing on Arch Linux",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Status
    subparsers.add_parser("status", help="Show hardware feasibility and memory status")

    # Detect
    det_parser = subparsers.add_parser("detect", help="Run AI text detection")
    det_parser.add_argument("--text", "-t", type=str, help="Prose text to analyze")
    det_parser.add_argument("--file", "-f", type=str, help="Path to .txt or .md file")
    det_parser.add_argument("--language", "-l", type=str, default="en", help="Language code (en/de)")

    # Rephrase
    rep_parser = subparsers.add_parser("rephrase", help="Rephrase text with preservation")
    rep_parser.add_argument("--text", "-t", type=str, help="Text to rewrite")
    rep_parser.add_argument("--file", "-f", type=str, help="Path to input .txt or .md file")
    rep_parser.add_argument("--output", "-o", type=str, help="Path to output file")
    rep_parser.add_argument(
        "--mode",
        "-m",
        type=str,
        default="standard",
        choices=[m.value for m in RephraseMode],
        help="Rephrasing style mode",
    )
    rep_parser.add_argument(
        "--strength",
        "-s",
        type=str,
        default="medium",
        choices=["low", "medium", "high"],
        help="Change strength",
    )
    rep_parser.add_argument("--freeze", type=str, help="Comma-separated list of words/phrases to freeze")
    rep_parser.add_argument("--custom", type=str, help="Custom style instructions")
    rep_parser.add_argument("--language", "-l", type=str, default="en", help="Target language (en/de)")
    rep_parser.add_argument("--model", type=str, default="qwen3:8b", help="Exact installed Ollama model name")

    # GUI
    subparsers.add_parser("gui", help="Launch native desktop GUI")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status()
    elif args.command == "detect":
        cmd_detect(args)
    elif args.command == "rephrase":
        cmd_rephrase(args)
    elif args.command == "gui":
        from localtext.main import launch_gui
        launch_gui()
    else:
        # Default if no subcommand given: show status
        cmd_status()


if __name__ == "__main__":
    main()

