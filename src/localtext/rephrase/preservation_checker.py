"""Deterministic preservation checker for rephrasing outputs.

Adheres strictly to REP-07, REP-10, AT-07, and AT-08.
Validates negation, modality, named entities, entity-quantity associations,
structural coverage, and ensures no conversational commentary leaks into output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


NEGATION_WORDS_EN = {
    "not", "never", "no", "neither", "nor", "none", "cannot", "hardly",
    "scarcely", "barely", "without", "n't", "fails", "refuse",
}
NEGATION_WORDS_DE = {
    "nicht", "nie", "niemals", "weder", "noch", "kein", "keine", "keinem",
    "keinen", "keines", "keiner", "ohne", "scheitert", "misslingt",
}

MODALITY_WORDS_EN = {
    "may", "might", "could", "possible", "possibly", "potential", "potentially",
    "suggests", "indicates", "hypothesize", "plausible",
}
MODALITY_WORDS_DE = {
    "kann", "könnte", "möglicherweise", "eventuell", "vielleicht", "potenziell",
    "plausibel", "deutet", "vermutet",
}

COMMENTARY_PREFIXES = [
    r"^here is (?:the|a) rewrite",
    r"^certainly!?",
    r"^sure!?",
    r"^rewritten text:",
    r"^hier ist die (?:umformulierte|überarbeitete) version",
    r"^gerne!?",
]


@dataclass
class PreservationReport:
    passed: bool
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggested_repair_instruction: Optional[str] = None


class PreservationChecker:
    """Performs deterministic checks on candidate rewrites against source text."""

    def __init__(self, language: str = "en"):
        self.language = language.lower()

    def check_preservation(
        self,
        source_text: str,
        candidate_text: str,
        mode: str = "standard",
    ) -> PreservationReport:
        failed_checks: List[str] = []
        warnings: List[str] = []

        clean_src = source_text.strip()
        clean_cand = candidate_text.strip()

        # 1. Non-empty check
        if not clean_cand:
            return PreservationReport(
                passed=False,
                failed_checks=["Rewrite output is empty."],
                suggested_repair_instruction="Generate a valid non-empty rewrite of the target text.",
            )

        # 2. Commentary prefix check (REP-07)
        for pat in COMMENTARY_PREFIXES:
            if re.search(pat, clean_cand, re.IGNORECASE):
                failed_checks.append("Output contains conversational commentary or prefix wrapper.")
                break

        # 3. Negation check (REP-07, AT-07)
        neg_words = NEGATION_WORDS_DE if self.language == "de" else NEGATION_WORDS_EN
        src_tokens = re.findall(r"\b[A-Za-zäöüßÄÖÜ']+\b", clean_src.lower())
        cand_tokens = re.findall(r"\b[A-Za-zäöüßÄÖÜ']+\b", clean_cand.lower())

        src_has_neg = any(t in neg_words or t.endswith("n't") for t in src_tokens)
        cand_has_neg = any(t in neg_words or t.endswith("n't") for t in cand_tokens)

        if src_has_neg and not cand_has_neg:
            failed_checks.append(
                "Critical meaning reversal: source contains negation, but rewrite omits negation entirely."
            )

        # 4. Modality / Hedging check (REP-07, AT-07)
        mod_words = MODALITY_WORDS_DE if self.language == "de" else MODALITY_WORDS_EN
        src_has_mod = any(t in mod_words for t in src_tokens)
        cand_has_mod = any(t in mod_words for t in cand_tokens)

        if src_has_mod and not cand_has_mod:
            # Check if source had causality limitation as in AT-07
            if "causality" in src_tokens or "prove" in src_tokens or "kausalität" in src_tokens:
                failed_checks.append(
                    "Modality distortion: tentative hedging or causal limitation ('may/not prove') was turned into an absolute assertion."
                )
            else:
                warnings.append("Modality shift: source had tentative hedging ('may/might') that was weakened.")

        # 5. Entity-Quantity attachment check (AT-08)
        # Check specific pattern: Name + number co-occurrences
        # E.g. "Alice ... 5" and "Bob ... 9"
        src_attachments = self._extract_name_quantity_pairs(clean_src)
        if src_attachments:
            cand_attachments = self._extract_name_quantity_pairs(clean_cand)
            for name, qty in src_attachments.items():
                if name in cand_attachments:
                    cand_qty = cand_attachments[name]
                    if cand_qty != qty:
                        failed_checks.append(
                            f"Entity misattribution: '{name}' was associated with quantity {qty} in source, but received {cand_qty} in rewrite."
                        )

        # 6. Length ratio sanity check
        src_words = len(clean_src.split())
        cand_words = len(clean_cand.split())
        if src_words >= 15:
            ratio = cand_words / max(1, src_words)
            if mode != "shorten" and ratio < 0.45:
                failed_checks.append(
                    f"Drastic text truncation: rewrite length ({cand_words} words) is only {ratio*100:.1f}% of source."
                )

        passed = len(failed_checks) == 0
        repair_inst = None
        if not passed:
            repair_inst = "Repair the rewrite by addressing: " + "; ".join(failed_checks)

        return PreservationReport(
            passed=passed,
            failed_checks=failed_checks,
            warnings=warnings,
            suggested_repair_instruction=repair_inst,
        )

    def _extract_name_quantity_pairs(self, text: str) -> dict[str, str]:
        """Extract associations between capitalized names and the nearest quantity in the same clause."""
        pairs: dict[str, str] = {}
        # Split into clause-like segments by punctuation (periods, commas, semicolons, dashes)
        clauses = re.split(r"[,;—\n]|\b(?:whereas|while|whilst|however|although|but|and)\b", text, flags=re.IGNORECASE)
        stop_words = {"the", "a", "an", "this", "that", "these", "those", "in", "on", "at", "we", "total"}

        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            names = [m for m in re.finditer(r"\b([A-Z][a-z]+)\b", clause) if m.group(1).lower() not in stop_words]
            numbers = list(re.finditer(r"\b(\d+(?:[.,]\d+)?)\b", clause))

            if not names or not numbers:
                continue

            # For each name, find the number with minimum character distance in this clause
            for n_match in names:
                name_str = n_match.group(1)
                best_num = min(numbers, key=lambda num_m: abs(num_m.start() - n_match.start()))
                # Only associate if reasonably close (within 40 characters)
                if abs(best_num.start() - n_match.start()) <= 40:
                    pairs[name_str] = best_num.group(1)

        return pairs
