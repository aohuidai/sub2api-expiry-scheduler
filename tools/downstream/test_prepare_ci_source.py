import json
import tempfile
import unittest
from pathlib import Path

from prepare_ci_source import read_release_inputs


class PrepareCISourceTests(unittest.TestCase):
    def test_uses_manifest_baseline_for_maintenance_source(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            manifest_path = repo / "patches/downstream/series.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps({"baseline": "v1.2.3"}))

            self.assertEqual(read_release_inputs(repo), ("v1.2.3", 1, "HEAD"))

    def test_uses_metadata_maintenance_commit_for_review_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            repo.joinpath("DOWNSTREAM_RELEASE.json").write_text(json.dumps({
                "upstream_tag": "v1.2.3",
                "custom_revision": 4,
                "maintenance_commit": "a" * 40,
            }))

            self.assertEqual(read_release_inputs(repo), ("v1.2.3", 4, "a" * 40))


if __name__ == "__main__":
    unittest.main()
