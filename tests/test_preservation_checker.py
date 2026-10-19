"""Unit tests for deterministic preservation checks.

Verifies REP-07, REP-10, AT-07, and AT-08:
- AT-07: "The method may reduce errors but does not prove causality."
- AT-08: "Alice received 5 units and Bob received 9."
"""

import unittest
from localtext.rephrase.preservation_checker import PreservationChecker


class TestPreservationChecker(unittest.TestCase):
    def setUp(self):
        self.checker_en = PreservationChecker(language="en")
        self.checker_de = PreservationChecker(language="de")

    def test_at07_modality_and_negation_retained(self):
        """AT-07: 'The method may reduce errors but does not prove causality.'"""
        source = "The method may reduce errors but does not prove causality."
        
        # Good candidate preserving modality ("may") and negation ("not prove causality")
        valid_cand = "Although this technique might decrease mistakes, it fails to demonstrate a causal link."
        rep_good = self.checker_en.check_preservation(source, valid_cand)
        self.assertTrue(rep_good.passed)

        # Bad candidate 1: Omits negation (claims it DOES prove causality)
        bad_cand_no_neg = "This method can reduce errors and proves causality."
        rep_bad1 = self.checker_en.check_preservation(source, bad_cand_no_neg)
        self.assertFalse(rep_bad1.passed)
        self.assertTrue(any("negation" in err for err in rep_bad1.failed_checks))

        # Bad candidate 2: Modality dropped into absolute assertion without hedge
        bad_cand_no_hedge = "The method will eliminate errors but does not prove causality."
        # Even with negation, if hedging on causality is dropped
        bad_cand_absolute = "The method reduces errors and confirms causality."
        rep_bad2 = self.checker_en.check_preservation(source, bad_cand_absolute)
        self.assertFalse(rep_bad2.passed)

    def test_at08_entity_quantity_attachment(self):
        """AT-08: 'Alice received 5 units and Bob received 9.'"""
        source = "Alice received 5 units and Bob received 9 units."

        # Correct rewrite
        valid_cand = "A total of 5 units was given to Alice, whereas Bob was allocated 9 units."
        rep_valid = self.checker_en.check_preservation(source, valid_cand)
        self.assertTrue(rep_valid.passed)

        # Swapped attribution: Alice gets 9, Bob gets 5 (Multiset of numbers matches, but entities swapped!)
        swapped_cand = "Bob received 5 units, while Alice received 9 units."
        rep_swapped = self.checker_en.check_preservation(source, swapped_cand)
        self.assertFalse(rep_swapped.passed)
        self.assertTrue(any("Entity misattribution" in err for err in rep_swapped.failed_checks))

    def test_commentary_prefix_rejected(self):
        source = "This is a simple sentence."
        cand = "Certainly! Here is the rewritten text: This is an uncomplicated sentence."
        rep = self.checker_en.check_preservation(source, cand)
        self.assertFalse(rep_valid := rep.passed)
        self.assertTrue(any("commentary" in err for err in rep.failed_checks))

    def test_german_negation_preservation(self):
        source = "Dieses Verfahren ist nicht für den produktiven Einsatz geeignet."
        cand_bad = "Dieses Verfahren ist für den produktiven Einsatz geeignet."
        rep = self.checker_de.check_preservation(source, cand_bad)
        self.assertFalse(rep.passed)
        self.assertTrue(any("negation" in err for err in rep.failed_checks))


if __name__ == "__main__":
    unittest.main()
