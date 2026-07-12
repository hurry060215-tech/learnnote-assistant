from __future__ import annotations

import unittest

from app.models import TaskOptions
from app.summarizer import note_generation_contract, note_style_instruction


class NoteProfileTests(unittest.TestCase):
    def test_custom_profile_enters_generation_contract(self):
        options = TaskOptions(
            note_style="custom",
            note_profile_name="Research review",
            note_profile_prompt="Organize claims by evidence strength.",
            note_profile_sections=["Question", "Evidence", "Limitations"],
        )
        contract = note_generation_contract(options)
        self.assertIn("Research review", contract)
        self.assertIn("Organize claims by evidence strength.", contract)
        self.assertIn("Question、Evidence、Limitations", contract)
        self.assertIn("真实性", contract)
        self.assertIn("Research review", note_style_instruction(options))

    def test_profile_limits_are_enforced(self):
        with self.assertRaises(ValueError):
            TaskOptions(note_profile_prompt="x" * 4001)
        with self.assertRaises(ValueError):
            TaskOptions(note_profile_sections=[str(index) for index in range(17)])


if __name__ == "__main__":
    unittest.main()
