import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from prepare_release import git, prepare


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Patch Queue Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / "app.txt").write_text("official\n")
        self.commit("upstream baseline")
        git(self.repo, "tag", "v1.0.0")
        (self.repo / "app.txt").write_text("custom feature\n")
        feature = git(self.repo, "diff", "--", "app.txt")
        git(self.repo, "restore", "app.txt")
        directory = self.repo / "patches/downstream"
        directory.mkdir(parents=True)
        (directory / "feature.patch").write_bytes(feature)
        self.manifest = {
            "schema_version": 1,
            "patches": [{"id": "feature", "file": "feature.patch", "subject": "feat: custom feature"}],
            "maintenance_paths": ["patches/downstream"],
        }
        self.write_manifest()
        self.commit("maintenance source")
        self.source = git(self.repo, "rev-parse", "HEAD").decode().strip()

    def commit(self, subject):
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", subject)

    def write_manifest(self):
        (self.repo / "patches/downstream/series.json").write_text(json.dumps(self.manifest))

    def test_replays_only_features_on_new_official_release(self):
        git(self.repo, "switch", "--detach", "v1.0.0")
        (self.repo / "new-official.txt").write_text("new official functionality\n")
        self.commit("official next release")
        git(self.repo, "tag", "v1.1.0")
        result = prepare(self.repo, "v1.1.0", "v1.1.0", self.source)
        self.assertEqual(git(self.repo, "show", result["candidate_sha"] + ":app.txt"), b"custom feature\n")
        self.assertEqual(git(self.repo, "show", result["candidate_sha"] + ":new-official.txt"), b"new official functionality\n")
        self.assertEqual(git(self.repo, "show", result["base_sha"] + ":app.txt"), b"official\n")
        self.assertEqual(git(self.repo, "rev-parse", "main").decode().strip(), self.source)
        self.assertEqual(result["base_branch"], "release/v1.1.0")
        self.assertEqual(result["candidate_branch"], "custom/v1.1.0")
        self.assertEqual(git(self.repo, "diff", "--name-only", result["base_sha"], result["candidate_sha"]), b"app.txt\n")
        metadata = json.loads(git(self.repo, "show", result["candidate_sha"] + ":DOWNSTREAM_RELEASE.json"))
        self.assertEqual(metadata["maintenance_commit"], self.source)
        self.assertEqual(len(metadata["patches"][0]["sha256"]), 64)

    def test_applies_dependent_features_in_manifest_order(self):
        git(self.repo, "switch", "--detach", "v1.0.0")
        (self.repo / "app.txt").write_text("custom feature\n")
        self.commit("first feature")
        (self.repo / "app.txt").write_text("custom feature with enhancement\n")
        second = git(self.repo, "diff", "--", "app.txt")
        git(self.repo, "restore", "app.txt")
        git(self.repo, "switch", "main")
        (self.repo / "patches/downstream/second.patch").write_bytes(second)
        self.manifest["patches"].append({"id": "second", "file": "second.patch", "subject": "feat: enhancement"})
        self.write_manifest()
        self.commit("add dependent patch")
        result = prepare(self.repo, "v1.0.0", "v1.0.0", "main")
        self.assertEqual(git(self.repo, "show", result["candidate_sha"] + ":app.txt"), b"custom feature with enhancement\n")

    def test_conflict_preserves_worktree_without_changing_source(self):
        git(self.repo, "switch", "--detach", "v1.0.0")
        (self.repo / "app.txt").write_text("incompatible upstream replacement\n")
        self.commit("upstream conflicting change")
        git(self.repo, "tag", "v2.0.0")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaisesRegex(RuntimeError, "Patch feature needs adaptation"):
            prepare(self.repo, "v2.0.0", "v2.0.0", self.source)
        path = Path(errors.getvalue().strip().split("preserved at ")[-1])
        self.addCleanup(lambda: git(self.repo, "worktree", "remove", "--force", str(path)))
        self.assertIn(b"app.txt", git(path, "diff", "--name-only", "--diff-filter=U"))
        self.assertEqual(git(self.repo, "rev-parse", "main").decode().strip(), self.source)

    def test_rejects_non_release_tag_before_creating_worktree(self):
        with self.assertRaisesRegex(ValueError, "official vX.Y.Z"):
            prepare(self.repo, "main", "main;invalid", self.source)

    def test_stages_allowlisted_docs_even_when_upstream_ignores_them(self):
        (self.repo / ".gitignore").write_text("docs/\n")
        self.commit("upstream ignores docs")
        git(self.repo, "tag", "v1.2.0")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/maintenance.md").write_text("custom release instructions\n")
        git(self.repo, "add", "--force", "docs/maintenance.md")
        self.manifest["maintenance_paths"].append("docs/maintenance.md")
        self.write_manifest()
        self.commit("include maintenance documentation")
        result = prepare(self.repo, "v1.2.0", "v1.2.0", "main")
        self.assertEqual(
            git(self.repo, "show", result["candidate_sha"] + ":docs/maintenance.md"),
            b"custom release instructions\n",
        )

    def test_new_custom_revision_has_separate_review_branches(self):
        result = prepare(self.repo, "v1.0.0", "v1.0.0", self.source, revision=2)
        self.assertEqual(result["base_branch"], "release/v1.0.0-r2")
        self.assertEqual(result["candidate_branch"], "custom/v1.0.0-r2")
        self.assertEqual(result["custom_revision"], 2)


if __name__ == "__main__":
    unittest.main()
