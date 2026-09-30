import unittest

from bot import collect_approval_targets


class ApprovalTargetTests(unittest.TestCase):
    def test_priority_to_approval_chat_when_configured(self):
        targets = collect_approval_targets({10, 20}, "-100111", "-100222")
        self.assertEqual(targets, ["-100111"])

    def test_fallback_to_admins_and_group_when_no_approval_chat(self):
        targets = collect_approval_targets({10, 20}, "", "-100222")
        self.assertEqual(targets, [10, 20, "-100222"])


if __name__ == "__main__":
    unittest.main()
