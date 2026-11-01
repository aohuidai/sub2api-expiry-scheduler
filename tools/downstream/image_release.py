#!/usr/bin/env python3
"""Resolve a reviewed custom release and its image/source tag without inputs."""

import argparse
import base64
import json
import os
import re
import subprocess
from pathlib import Path


RELEASE = re.compile(r"release/v([0-9]+)\.([0-9]+)\.([0-9]+)(?:-r([1-9][0-9]*))?")
IMAGE_TAG = re.compile(r"dai-v([0-9]+)\.([0-9]+)\.([0-9]+)\.([1-9][0-9]*)")


def gh_api(repository, endpoint, fields=None, missing_ok=False, paginate=False):
    args = ["gh", "api"]
    if paginate:
        args += ["--paginate", "--slurp"]
    args += ["repos/" + repository + "/" + endpoint]
    if fields is not None:
        args += ["--method", "POST"]
        for key, value in fields.items():
            args += ["-f", key + "=" + value]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        if missing_ok and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def reviewed_version(pr, repository):
    base = pr.get("base", {})
    head = pr.get("head", {})
    match = RELEASE.fullmatch(base.get("ref", ""))
    if not pr.get("merged_at") or not match:
        return None
    if base.get("repo", {}).get("full_name") != repository:
        return None
    if (head.get("repo") or {}).get("full_name") != repository:
        return None
    if head.get("ref") != "custom/" + base["ref"].removeprefix("release/"):
        return None
    return tuple(int(value or 1) for value in match.groups())


def latest_reviewed(prs, repository):
    candidates = [(reviewed_version(pr, repository), pr) for pr in prs]
    candidates = [(version, pr) for version, pr in candidates if version]
    if not candidates:
        raise ValueError("No merged custom-to-release PR exists; merge a reviewed version PR first")
    return max(candidates, key=lambda item: (item[0], item[1]["merged_at"]))[1]


def image_metadata(sha, metadata, expected_version=None):
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha):
        raise ValueError("Expected a full source commit SHA")
    version = metadata.get("upstream_tag", "")
    match = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)", version)
    revision = metadata.get("custom_revision")
    if not match or type(revision) is not int or revision < 1:
        raise ValueError("Source lacks valid reviewed release metadata")
    resolved = tuple(int(value) for value in match.groups()) + (revision,)
    if expected_version is not None and resolved != expected_version:
        raise ValueError("Review/tag version does not match source metadata")
    upstream = version.removeprefix("v")
    return {
        "source_sha": sha,
        "image_tag": "dai-" + version + "." + str(revision),
        "runtime_version": upstream + "-dai." + str(revision),
    }


def ensure_source_tag(repository, tag, sha, api=gh_api):
    if not IMAGE_TAG.fullmatch(tag):
        raise ValueError("Invalid custom source tag")
    existing = api(repository, "git/ref/tags/" + tag, missing_ok=True)
    if existing:
        obj = existing["object"]
        for _ in range(8):
            if obj["type"] != "tag":
                break
            obj = api(repository, "git/tags/" + obj["sha"])["object"]
        if obj["type"] != "commit" or obj["sha"] != sha:
            raise ValueError("Existing source tag points elsewhere; use a new custom revision")
        return
    annotation = api(repository, "git/tags", fields={
        "tag": tag, "message": "Reviewed custom release " + tag,
        "object": sha, "type": "commit",
    })
    api(repository, "git/refs", fields={"ref": "refs/tags/" + tag, "sha": annotation["sha"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    expected = None
    review = None
    if event_name == "workflow_dispatch":
        pages = gh_api(repository, "pulls?state=closed&per_page=100", paginate=True)
        review = latest_reviewed([pr for page in pages for pr in page], repository)
    elif event_name == "pull_request":
        review = event["pull_request"]
        if reviewed_version(review, repository) is None:
            raise ValueError("Only a merged custom-to-release PR can publish an image")
    elif event_name == "push":
        match = IMAGE_TAG.fullmatch(os.environ["GITHUB_REF_NAME"])
        if not match:
            raise ValueError("Expected a custom source tag")
        expected = tuple(int(value) for value in match.groups())
        sha = subprocess.check_output(
            ["git", "rev-parse", os.environ["GITHUB_REF"] + "^{commit}"], text=True
        ).strip()
    else:
        raise ValueError("Unsupported image-build event")
    if review is not None:
        sha = review["merge_commit_sha"]
        expected = reviewed_version(review, repository)
    content = gh_api(repository, "contents/DOWNSTREAM_RELEASE.json?ref=" + sha)
    metadata = json.loads(base64.b64decode(content["content"]))
    resolved = image_metadata(sha, metadata, expected)
    ensure_source_tag(repository, resolved["image_tag"], resolved["source_sha"])
    with args.output.open("a") as stream:
        for name, value in resolved.items():
            stream.write(name + "=" + value + "\n")
    summary = "Build " + resolved["image_tag"] + " from " + resolved["source_sha"]
    if review:
        summary += " (merged PR #" + str(review["number"]) + ")"
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
            stream.write(summary + "\n")


if __name__ == "__main__":
    main()
