"""Secret scrubbing tests. All secrets here are SYNTHETIC."""

import unittest

from housebroken.redact import redact


class TestRedact(unittest.TestCase):
    def test_aws_key(self):
        out = redact("key AKIAIOSFODNN7EXAMPLE end")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)
        self.assertIn("<redacted:aws-key>", out)

    def test_github_token(self):
        s = "ghp_" + "a" * 36
        self.assertIn("<redacted:github-token>", redact(f"token={s}"))
        self.assertNotIn(s, redact(f"token={s}"))

    def test_openai_style_key(self):
        s = "sk-" + "A1b2C3d4E5f6G7h8"
        self.assertIn("<redacted:api-key>", redact(s))

    def test_slack_token(self):
        s = "xoxb-1234567890-abcdefghij"
        self.assertIn("<redacted:slack-token>", redact(s))

    def test_email(self):
        out = redact("contact someone@example.com now")
        self.assertNotIn("someone@example.com", out)
        self.assertIn("<redacted:email>", out)

    def test_bearer_header(self):
        out = redact("Authorization: abcdef123456ghijkl")
        self.assertIn("<redacted:token>", out)

    def test_secret_env_assignment(self):
        out = redact("API_KEY=sup3rs3cr3tvalue123")
        self.assertIn("<redacted:secret-value>", out)
        self.assertNotIn("sup3rs3cr3tvalue123", out)

    def test_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123456"
        self.assertIn("<redacted:jwt>", redact(jwt))

    def test_plain_text_untouched(self):
        s = "git commit -m 'feat: add parser'"
        self.assertEqual(redact(s), s)

    def test_empty(self):
        self.assertEqual(redact(""), "")


if __name__ == "__main__":
    unittest.main()
