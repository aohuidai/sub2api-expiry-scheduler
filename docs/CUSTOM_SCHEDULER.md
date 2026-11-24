# Sub2API Downstream Maintenance

This repository maintains a small feature patch queue on official Sub2API
releases. The feature source of truth is `patches/downstream/series.json` and
the patches it lists. Every new version is rebuilt from its official release
tag; it does not merge the entire old custom release into the new one.

## Account Scheduling Feature

`openai_advanced_scheduler_reset_window_mode` has three modes:

- `short`: official-compatible five-hour/session-window scoring (default).
- `long`: a weighted preference for future long quota reset times. The reset
  score weight controls its strength alongside other scheduling signals.
- `long_strict`: try eligible accounts in earliest future long-reset order for
  newly load-balanced requests. This bypasses TopK random ordering and falls
  back when an earlier account is full, rate-limited, or unavailable.

The historic `codex_7d` field can hold a 7-day, 30-day, or other long window.
Explicitly short or invalid durations are rejected. Missing or past reset
times get no long-window preference. Normal provider limits still apply.
Existing previous-response and session bindings retain conversation affinity.

The scheduling patch includes backend logic, settings API/cache/audit support,
admin UI, translations, and regression tests as one logical change. A second
patch contains frontend security updates and their tests/CI runtime. Maintenance
scripts and image workflows are separate from these application patches.

## Branches And Reviews

- `main` maintains the patch queue and release tooling. It is not deployed
  directly; CI reconstructs the declared baseline plus patches before testing.
- Official `Wei-Shaw/sub2api` release tags are the unmodified upstream source.
- `release/vX.Y.Z` starts at the official tag plus the explicitly allowlisted
  maintenance files. It is a version-specific review base.
- `custom/vX.Y.Z` adds the feature patches in manifest order. The generated PR
  targets `release/vX.Y.Z`, so its diff shows application features rather than
  every change made by upstream since the last custom release.
- After reviewing checks, merge that PR into its version's release branch.
  Merging the version PR automatically builds its reviewed merge commit as an
  ARM64 image. The image/source tag is derived from release metadata, e.g.
  `dai-v0.2.19.2`; runtime versions use SemVer, e.g. `0.2.19-dai.2`.

Version branches are never force-pushed by automation. Existing open, closed,
or merged proposals are recognized, and retries do not overwrite human work.
Old deployment tags and branches remain available for rollback.

For a new custom feature on the same official version, dispatch with
`revision=2` (then 3, etc.). This creates separate `release/vX.Y.Z-r2` and
`custom/vX.Y.Z-r2` branches and a new review; it preserves the first review.

`DOWNSTREAM_RELEASE.json` records the official tag/commit, maintenance commit,
custom revision, and SHA-256 of each applied feature patch. Image builds reject
a version tag or review branch that does not match this metadata.

## Building An Image

After merging a `custom/...` -> `release/...` version PR, `Build Custom Image`
runs automatically. A closed but unmerged PR does not build. The version source
tag is also created automatically without triggering a recursive tag build.

For a manual build, select `Build Custom Image` and click `Run workflow` from
`main`. There are no required input fields. It selects the highest official
version and custom revision among merged version PRs, reads that exact merge
commit's metadata, and derives the source/image tag. An older backport merged
later cannot replace a newer reviewed release as the default selection.

The build never takes the head of an unreviewed candidate or the application
checkout on `main` as its default. Existing source tags must resolve to the
same reviewed commit; they are not moved to publish different code. Explicit
`dai-v...` tag pushes remain a supported build trigger. Server deployment is
still a separate operation after publication.

## Automatic Preparation

`Propose Upstream Sync` checks the latest official stable release daily from
`main`. It also supports manual dispatch with an explicit official tag and a
maintenance branch to verify workflow changes before merging. It prepares both
version branches locally, then pushes them atomically
and opens the review PR. Preparation itself never merges, builds, or deploys
a release. Image publication begins only after the version PR is merged.

Preparation uses:

```bash
git fetch --no-tags upstream refs/tags/vX.Y.Z:refs/tags/upstream/vX.Y.Z
python3 tools/downstream/prepare_release.py \
  --upstream-ref refs/tags/upstream/vX.Y.Z \
  --upstream-tag vX.Y.Z --source-ref main --output /tmp/release.json
```

The script creates commits in an isolated worktree and prints the candidate
names/SHAs in the output JSON. It does not move `main` or publish anything.
If a patch conflicts, it stops with the feature ID and preserves the worktree
for inspection. Adapt that feature, update its patch in the maintenance branch,
and retry. No partial version branches are pushed on a preparation failure.

## Adding Or Adapting A Feature

1. Start a feature branch from the intended official baseline, applying earlier
   patches first if the feature depends on them.
2. Keep the behavior, UI/settings integration, and tests in that feature's
   commits. Do not copy entire old application files over official files.
3. Export the feature's diff with `git diff --binary --full-index BASE FEATURE`
   into its `.patch` file. `BASE` is the official version or preceding feature,
   not the maintenance commit containing unrelated tools.
4. Add its ID, filename, and commit subject to `series.json` in dependency
   order. Set `baseline` to an official tag against which the entire queue is
   tested. Remove a patch once upstream implements the same behavior.
5. Run queue, application, and security checks before merging the maintenance
   change. The next official version is independently reconstructed from this
   queue; an application-only edit is not automatically a persistent patch.

## GitHub Authentication

`UPSTREAM_SYNC_SSH_KEY` is a repository-only writable deploy key stored as an
encrypted Actions secret. `actions/checkout` uses it to push version branches,
including official workflow changes. The API uses the job's temporary
`GITHUB_TOKEN` with `pull-requests: write`; the repository must allow Actions
to create pull requests. No personal OAuth token is stored in Actions.

The private deploy key backup and its inventory entry live in the local
private directory, outside this repository. Never print the private key.
Revoke it through this repository's Deploy keys settings if no longer needed.

Deploy-key pushes trigger the upstream CI and Security Scan on the candidate
commit. GitHub may additionally request approval for PR-event checks created
with `GITHUB_TOKEN`; candidate push checks run independently. No workflow uses
`pull_request_target` to execute unreviewed candidate code with secrets.

## Verification

The `Downstream Patch Queue` workflow tests isolated reconstruction, ordering,
conflict preservation, and replay of the real patch against its baseline.
Upstream CI retains its unit/integration tests, lint, and frontend checks.

Focused application checks:

```bash
python3 -m unittest discover -s tools/downstream -p 'test_*.py'
cd backend
go test ./internal/service ./internal/handler/admin
go test -tags=unit ./internal/server -run '^TestAPIContracts$'
cd ../frontend
pnpm test:run -- src/views/admin/__tests__/SettingsView.spec.ts
pnpm typecheck
```

Official v0.2.24 uses Go 1.27.4, fixed Brotli and zstd dependencies, Node 24,
and Vue I18n v11. The separate frontend security patch replaces npm's old
`xlsx` 0.18.5 with the official SheetJS 0.20.3 tarball and verifies the admin
export API can create and read a workbook. pnpm's advisory feed does not
reliably recognize the CDN tarball version, so the two upstream `xlsx` audit
exceptions remain documented until the advisory tooling can verify it directly.
Keep security scanning enabled and review new findings on each update.

The integration test patch uses `redis:8-alpine`, the same supported tag used
by the production Compose files. It replaces a stale `redis:8.4-alpine` test
tag that Docker Hub no longer serves; no application runtime image changes.

## Deployment And Rollback

The Oracle host uses a native ARM64 Docker build from a reviewed custom tag.
GHCR artifacts are optional; the repository/package remain private and no
GitHub registry token is required on the server.

Before deployment, back up Compose, `.env`, PostgreSQL, and application data;
validate the dump/checksums; build the exact reviewed source; then recreate only
`sub2api` with `--no-deps`. Check health, logs, and scheduler settings afterward.
Record the source, tag/image, backup, and rollback in the server change log.

Do not use the application's official online-update button when this feature
is required. For rollback, restore the prior pinned image and compatible
scheduler setting. Database restoration is only for a deliberate full rollback.
