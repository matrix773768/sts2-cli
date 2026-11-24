"""Regression coverage for local Git discovery and mandatory checkout identity."""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.training_manager.common import HOME
from tools.training_manager import git_head


class GitHeadTests(unittest.TestCase):
    def setUp(self):
        HOME.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=HOME, prefix="inf2-git-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_desktop_copies_are_sorted_by_numeric_version(self):
        desktop = self.base / "GitHubDesktop"
        versions = ("app-3.9.9", "app-3.10.1-beta1", "app-3.10.1", "app-invalid", "packages")
        for name in versions:
            (desktop / name).mkdir(parents=True)
        self.assertEqual([item.parents[2].name for item in git_head.desktop_git_roots(self.base)],
                         ["app-3.10.1", "app-3.10.1-beta1", "app-3.9.9"])

    @unittest.skipUnless(os.name == "nt", "Windows discovery")
    def test_path_system_and_desktop_candidates(self):
        system = self.base / "System Install"
        custom = self.base / "Registered Git"
        local = self.base / "Local"
        engine = local / "GitHubDesktop/app-3.7.2/resources/app/git/cmd/git.exe"
        engine.parent.mkdir(parents=True)
        with (patch.dict(os.environ, {"PATH": f';.;"{system}";relative', "LOCALAPPDATA": str(local)}, clear=True),
              patch.object(Path, "home", return_value=self.base / "Profile"),
              patch.object(git_head, "registered_git_roots", return_value=iter([custom]))):
            ordered = list(git_head.candidates())
        self.assertEqual(ordered[:3], [system / "git.exe", custom / "cmd/git.exe", custom / "bin/git.exe"])
        self.assertIn(engine, ordered)

    def test_missing_git_explains_how_to_recover(self):
        with patch.object(git_head, "candidates", return_value=iter([self.base/"missing.exe"])):
            with self.assertRaisesRegex(ValueError, "找不到可执行的 Git.*GitHub Desktop"):
                git_head.checkout_head(self.base)

    def test_falls_back_after_a_stale_executable_and_queries_the_intended_checkout(self):
        old, working = self.base/"stale.exe", self.base/"working.exe"
        old.touch()
        working.touch()
        sha = "1" * 40
        output = subprocess.CompletedProcess(["git"], 0, stdout=f"{self.base.as_posix()}\n{sha}\n", stderr="")
        with (patch.object(git_head, "candidates", return_value=iter([old, working])),
              patch.dict(os.environ, {"GIT_DIR": "unrelated", "GIT_WORK_TREE": "unrelated"}),
              patch.object(git_head.subprocess, "run", side_effect=[FileNotFoundError(), output]) as call):
            self.assertEqual(git_head.checkout_head(self.base), sha)
        argv = call.call_args.args[0]
        self.assertEqual(argv, [str(working), "rev-parse", "--show-toplevel", "--verify", "HEAD^{commit}"])
        self.assertEqual(call.call_args.kwargs["cwd"], self.base)
        self.assertFalse({"GIT_DIR", "GIT_WORK_TREE"} & call.call_args.kwargs["env"].keys())

    def test_rejects_wrong_root_and_short_sha(self):
        git = self.base/"git.exe"
        git.touch()
        for root, sha, reason in ((self.base/"other", "1"*40, "根目录"),
                                  (self.base, "a12bc34", "完整的 HEAD")):
            with (self.subTest(reason=reason), patch.object(git_head, "candidates", return_value=iter([git])),
                  patch.object(git_head.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, stdout=f"{root}\n{sha}\n"))):
                with self.assertRaisesRegex(ValueError, reason):
                    git_head.checkout_head(self.base)


if __name__ == "__main__":
    unittest.main()
