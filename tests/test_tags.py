import unittest

from pm.tags import TAG, suggest


def d(removed, added):
    return "@@ -1 +1 @@\n-" + removed + "\n+" + added + "\n"


class TestTags(unittest.TestCase):
    def test_rule_cases(self):
        cases = [
            (d("for (i = 0; i <= n; i++)", "for (i = 0; i < n; i++)"), ["off-by-one"]),
            (d("x = a[n];", "x = a[n - 1];"), ["off-by-one"]),
            (d("for i in range(1, n):", "for i in range(1, n + 1):"), ["off-by-one"]),
            (d("int dp[100];", "int dp[101];"), ["off-by-one"]),
            (d("x = 10", "x = 20"), []),
            (d("if (i < n)", "if (i < m)"), []),
            (d("int sum = 0;", "long long sum = 0;"), ["overflow"]),
            (d("return a * b;", "return 1LL * a * b;"), ["overflow"]),
            (d("int best;", "int best = 0;"), ["uninit"]),
            (d("int seen[N];", "int seen[N] = {};"), ["uninit"]),
            ("@@ -1 +1,2 @@\n+if (p == NULL) return;\n", ["null-check"]),
            ("@@ -1 +1,2 @@\n+    if node is None:\n", ["null-check"]),
            ("@@ -1 +1,2 @@\n+if (j >= v.size()) break;\n", ["bounds"]),
            ("", []),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(suggest(text, []), expected)

    def test_exit_codes(self):
        self.assertEqual(suggest("", [-11]), ["segfault"])
        self.assertEqual(suggest("", [139]), ["segfault"])
        self.assertEqual(suggest("", [134, 1]), ["abort"])
        self.assertEqual(suggest("", [-6]), ["abort"])
        self.assertEqual(suggest("", [124]), ["timeout"])

    def test_two_rules_sorted(self):
        text = d("for (i = 0; i <= n; i++)", "for (i = 0; i < n; i++)")
        text += "@@ -2 +2,2 @@\n+if (p == NULL) return;\n"
        self.assertEqual(suggest(text, []), ["null-check", "off-by-one"])

    def test_headers_are_not_lines(self):
        self.assertEqual(suggest("--- a/int.c\n+++ b/long.c\n", []), [])

    def test_tag_pattern(self):
        self.assertTrue(TAG.fullmatch("off-by-one"))
        self.assertTrue(TAG.fullmatch("x1"))
        self.assertFalse(TAG.fullmatch("Bad Tag"))
        self.assertFalse(TAG.fullmatch("-x"))
