import copy
import unittest

from image_release import ensure_source_tag, image_metadata, latest_reviewed, reviewed_version


REPOSITORY = "owner/project"
SHA = "a" * 40


def review(version="v0.2.19", revision=2, sha=SHA):
    suffix = "" if revision == 1 else "-r" + str(revision)
    return {
        "number": 4, "merged_at": "2026-10-31T14:35:18Z", "merge_commit_sha": sha,
        "base": {"ref": "release/" + version + suffix, "repo": {"full_name": REPOSITORY}},
        "head": {"ref": "custom/" + version + suffix, "repo": {"full_name": REPOSITORY}},
    }


class ImageReleaseTests(unittest.TestCase):
    def test_selects_highest_version_not_most_recent_old_backport(self):
        old = review("v0.2.9", 9)
        old["merged_at"] = "2026-11-01T12:00:00Z"
        new = review("v0.2.20", 1, "b" * 40)
        self.assertIs(latest_reviewed([old, new], REPOSITORY), new)

    def test_selects_newest_custom_revision(self):
        first, second = review(revision=1), review(revision=2)
        self.assertIs(latest_reviewed([second, first], REPOSITORY), second)

    def test_excludes_unmerged_unrelated_and_external_reviews(self):
        closed, maintenance, external = review(), review(), review()
        closed["merged_at"] = None
        maintenance["base"]["ref"] = "main"
        external["head"]["repo"]["full_name"] = "other/fork"
        for candidate in (closed, maintenance, external):
            self.assertIsNone(reviewed_version(candidate, REPOSITORY))
        with self.assertRaisesRegex(ValueError, "No merged"):
            latest_reviewed([closed, maintenance, external], REPOSITORY)

    def test_uses_merge_commit_and_derives_all_names_from_metadata(self):
        pr = review()
        data = image_metadata(pr["merge_commit_sha"],
                              {"upstream_tag": "v0.2.19", "custom_revision": 2},
                              reviewed_version(pr, REPOSITORY))
        self.assertEqual(data, {"source_sha": SHA, "image_tag": "dai-v0.2.19.2",
                                "runtime_version": "0.2.19-dai.2"})

    def test_rejects_metadata_version_or_revision_mismatch(self):
        for metadata in ({"upstream_tag": "v0.2.20", "custom_revision": 2},
                         {"upstream_tag": "v0.2.19", "custom_revision": 3}):
            with self.assertRaisesRegex(ValueError, "does not match"):
                image_metadata(SHA, metadata, (0, 2, 19, 2))

    def test_rejects_invalid_metadata_and_sha(self):
        for revision in (None, True, 0, "2"):
            with self.assertRaises(ValueError):
                image_metadata(SHA, {"upstream_tag": "v0.2.19", "custom_revision": revision})
        with self.assertRaises(ValueError):
            image_metadata("main", {"upstream_tag": "v0.2.19", "custom_revision": 2})

    def test_existing_annotated_tag_is_checked_without_rewriting(self):
        calls = []

        def api(repo, endpoint, **kwargs):
            calls.append((endpoint, kwargs))
            if endpoint.startswith("git/ref/"):
                return {"object": {"type": "tag", "sha": "c" * 40}}
            return {"object": {"type": "commit", "sha": SHA}}

        ensure_source_tag(REPOSITORY, "dai-v0.2.19.2", SHA, api)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any("fields" in kwargs for _, kwargs in calls))

    def test_refuses_to_retarget_existing_source_tag(self):
        def api(repo, endpoint, **kwargs):
            return {"object": {"type": "commit", "sha": "b" * 40}}

        with self.assertRaisesRegex(ValueError, "points elsewhere"):
            ensure_source_tag(REPOSITORY, "dai-v0.2.19.2", SHA, api)

    def test_creates_source_tag_for_a_new_reviewed_release(self):
        calls = []

        def api(repo, endpoint, **kwargs):
            calls.append((endpoint, copy.deepcopy(kwargs)))
            if kwargs.get("missing_ok"):
                return None
            return {"sha": "c" * 40}

        ensure_source_tag(REPOSITORY, "dai-v0.2.19.2", SHA, api)
        self.assertEqual(calls[1][1]["fields"]["object"], SHA)
        self.assertEqual(calls[2][1]["fields"],
                         {"ref": "refs/tags/dai-v0.2.19.2", "sha": "c" * 40})


if __name__ == "__main__":
    unittest.main()
