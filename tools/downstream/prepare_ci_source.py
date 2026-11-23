#!/usr/bin/env python3
"""Reconstruct the actual downstream candidate before CI checks it."""

import json
import re
import subprocess
from pathlib import Path

from prepare_release import git, prepare


TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
SHA_RE = re.compile(r"[0-9a-f]{40}")


def read_release_inputs(repo):
    release_file = repo / "DOWNSTREAM_RELEASE.json"
    if release_file.exists():
        metadata = json.loads(release_file.read_text(encoding="utf-8"))
        tag = metadata.get("upstream_tag")
        revision = metadata.get("custom_revision")
        source = metadata.get("maintenance_commit")
        if not isinstance(source, str) or not SHA_RE.fullmatch(source):
            raise ValueError("DOWNSTREAM_RELEASE.json has an invalid maintenance commit")
    else:
        manifest = json.loads((repo / "patches/downstream/series.json").read_text(encoding="utf-8"))
        tag = manifest.get("baseline")
        revision = 1
        source = "HEAD"
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
        raise ValueError("Expected an official vX.Y.Z release tag")
    if not isinstance(revision, int) or not 1 <= revision <= 9999:
        raise ValueError("Expected a custom revision between 1 and 9999")
    return tag, revision, source


def main():
    repo = Path.cwd().resolve()
    tag, revision, source = read_release_inputs(repo)
    git(repo, "config", "user.name", "github-actions[bot]")
    git(repo, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    subprocess.run(
        [
            "git", "fetch", "--no-tags", "https://github.com/Wei-Shaw/sub2api.git",
            "refs/tags/{}:refs/tags/upstream/{}".format(tag, tag),
        ],
        cwd=repo,
        check=True,
    )
    result = prepare(repo, "refs/tags/upstream/{}".format(tag), tag, source, revision)
    git(repo, "checkout", "--detach", result["candidate_sha"])
    print("Prepared CI source {} from {}".format(result["candidate_sha"], tag))


if __name__ == "__main__":
    main()
