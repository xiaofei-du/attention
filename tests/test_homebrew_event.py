import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("homebrew_event", ROOT / "scripts/homebrew_event.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HomebrewEventTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.event = {"repository": {"full_name": "xiaofei-du/attention"}, "workflow_run": {
            "event": "push", "conclusion": "success", "status": "completed",
            "head_branch": "main", "head_sha": self.sha,
            "head_repository": {"full_name": "xiaofei-du/attention"},
            "path": ".github/workflows/tests.yml",
        }}

    def check(self, version="0.1.8", formula_version="0.1.7"):
        return module.should_dispatch(self.event, self.sha,
                                      f'[project]\nversion = "{version}"\n',
                                      f'class Attention < Formula\n  version "{formula_version}"\nend\n')

    def test_tested_main_version_ahead_of_tap_requests_an_update(self):
        self.assertTrue(self.check())
        self.assertTrue(self.check("0.10.0", "0.9.0"))

    def test_docs_only_or_older_version_does_not_trigger_the_tap(self):
        self.assertFalse(self.check("0.1.7"))
        self.assertFalse(self.check("0.1.6"))

    def test_failed_pr_fork_or_different_workflow_cannot_dispatch(self):
        for field, value in (("event", "pull_request"), ("conclusion", "failure"),
                             ("head_branch", "feature"), ("head_sha", "b" * 40),
                             ("path", ".github/workflows/untrusted.yml"),
                             ("head_repository", {"full_name": "other/attention"})):
            with self.subTest(field=field):
                previous = self.event["workflow_run"][field]
                self.event["workflow_run"][field] = value
                self.assertFalse(self.check())
                self.event["workflow_run"][field] = previous

    def test_fork_repository_cannot_dispatch(self):
        self.event["repository"]["full_name"] = "other/attention"
        self.assertFalse(self.check())

    def test_malformed_or_prerelease_versions_fail_closed(self):
        for version in ("0.1.8-rc1", "1.2.3\\noutput=bad", "$(bad)", "1.2", "01.2.3"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.check(version)


if __name__ == "__main__":
    unittest.main()
