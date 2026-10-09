import unittest
from unittest.mock import patch


class LinearEmailRedactionTests(unittest.TestCase):
    def test_punctuation_malformed_tokens_and_multiple_addresses(self):
        from app.community import _redact_email_tokens
        self.assertEqual(_redact_email_tokens("Ask (alice+tag@example.com). Or b@school.edu!"), "Ask ([邮箱已省略]). Or [邮箱已省略]!")
        self.assertEqual(_redact_email_tokens("a@b@school.edu and @handle"), "[邮箱已省略] and @handle")
        self.assertEqual(_redact_email_tokens("x@y.z %%%@no-domain plain text"), "x@y.z %%%@no-domain plain text")

    def test_unbounded_helper_handles_adversarial_near_matches_without_regex(self):
        from app.community import _redact_email_tokens
        # Exercise the helper beyond the production 2,000-char cap. Disjoint
        # maximal-token scanning does not retry a candidate at every percent.
        with patch("app.community.re.sub", side_effect=AssertionError("email redaction must not use regex")):
            for token in ("%" * 250_000, "%" * 250_000 + "@host.c", "a@" + "." * 250_000):
                self.assertEqual(_redact_email_tokens(token), token)
            self.assertEqual(_redact_email_tokens("%" * 250_000 + "@school.edu"), "[邮箱已省略]")
