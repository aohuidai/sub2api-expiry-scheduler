#!/usr/bin/env python3
"""Build an upstream release plus an ordered, reviewable downstream patch set."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def git(repo, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def read_manifest(repo, source):
    raw = git(repo, "show", source + ":patches/downstream/series.json")
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported downstream manifest schema")
    ids = set()
    for patch in manifest["patches"]:
        if patch["id"] in ids:
            raise ValueError("Duplicate patch id: " + patch["id"])
        ids.add(patch["id"])
        if Path(patch["file"]).name != patch["file"]:
            raise ValueError("Patch file must be a filename")
    return manifest


def copy_maintenance(repo, source, destination, paths):
    for name in paths:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Maintenance path must be repository-relative")
    archive = git(repo, "archive", "--format=tar", source, "--", *paths)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Invalid archive path")
            target = destination / path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
                target.chmod(member.mode & 0o777)
            else:
                raise ValueError("Maintenance archive must contain regular files")


def prepare(repo, upstream_ref, tag, source, revision=1):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Expected an official vX.Y.Z release tag")
    if not 1 <= revision <= 9999:
        raise ValueError("Custom revision must be between 1 and 9999")
    source_sha = git(repo, "rev-parse", source + "^{commit}").decode().strip()
    upstream_sha = git(repo, "rev-parse", upstream_ref + "^{commit}").decode().strip()
    manifest = read_manifest(repo, source_sha)
    patch_data = []
    for patch in manifest["patches"]:
        path = "patches/downstream/" + patch["file"]
        data = git(repo, "show", source_sha + ":" + path)
        patch_data.append((patch, data))

    worktree = Path(tempfile.mkdtemp(prefix="sub2api-downstream-"))
    git(repo, "worktree", "add", "--detach", str(worktree), upstream_sha)
    succeeded = False
    try:
        copy_maintenance(repo, source_sha, worktree, manifest["maintenance_paths"])
        metadata = {
            "upstream_tag": tag,
            "custom_revision": revision,
            "upstream_commit": upstream_sha,
            "maintenance_commit": source_sha,
            "patches": [
                {"id": p["id"], "sha256": hashlib.sha256(data).hexdigest()}
                for p, data in patch_data
            ],
        }
        (worktree / "DOWNSTREAM_RELEASE.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        # Some official tags ignore docs/; stage only this explicit allowlist.
        git(worktree, "add", "--force", "--", *manifest["maintenance_paths"], "DOWNSTREAM_RELEASE.json")
        git(worktree, "commit", "-m", "chore(downstream): prepare " + tag + " review base [skip ci]")
        base_sha = git(worktree, "rev-parse", "HEAD").decode().strip()
        for patch, data in patch_data:
            try:
                git(worktree, "apply", "--3way", "--index", "-", data=data)
            except RuntimeError as exc:
                raise RuntimeError("Patch " + patch["id"] + " needs adaptation: " + str(exc)) from exc
            git(worktree, "commit", "-m", patch["subject"])
        candidate_sha = git(worktree, "rev-parse", "HEAD").decode().strip()
        git(worktree, "merge-base", "--is-ancestor", upstream_sha, candidate_sha)
        succeeded = True
        suffix = "" if revision == 1 else "-r" + str(revision)
        return {
            **metadata,
            "base_branch": "release/" + tag + suffix,
            "candidate_branch": "custom/" + tag + suffix,
            "base_sha": base_sha,
            "candidate_sha": candidate_sha,
        }
    finally:
        if succeeded:
            git(repo, "worktree", "remove", str(worktree))
        else:
            print("Conflict worktree preserved at " + str(worktree), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-ref", required=True)
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--source-ref", default="HEAD")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.repo.resolve(), args.upstream_ref, args.upstream_tag, args.source_ref, args.revision)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Prepared " + result["candidate_branch"] + " from " + result["upstream_tag"])


if __name__ == "__main__":
    main()
