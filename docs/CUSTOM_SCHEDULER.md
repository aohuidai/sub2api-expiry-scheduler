# Custom Scheduler Maintenance

This fork keeps one deliberately small local feature on top of official
Sub2API releases: the OpenAI advanced scheduler can score the recorded long
quota window instead of the usual 5-hour/session window.

## What The Patch Does

The setting is named `openai_advanced_scheduler_reset_window_mode`.

- `short` is the upstream-compatible default. The reset score uses the Codex
  5-hour window, then the legacy session window.
- `long` uses the canonical `codex_7d` quota reset timestamp. Despite the
  historic field name, this can represent a 7-day, 30-day, or another long
  provider window. Accounts without a valid future long reset timestamp get a
  reset factor of zero; they never fall back to a 5-hour window in this mode.

The existing reset-score weight still controls how strongly this factor affects
the final choice. A reset weight of `1` is a preference among the other health,
load, queue, sticky-session, and priority signals. Raise it deliberately when
the intended policy is to consume accounts with the soonest long-window reset
first.

The setting is available in the admin Settings page while the OpenAI advanced
scheduler is enabled. Existing deployments default to `short`, so upgrading
this fork alone does not change traffic routing.

## Branch And Release Model

`main` is the deployable custom fork. It contains an official release baseline
plus this patch. Do not replace `main` with upstream or force-push it to an
official tag.

Custom images use tags beginning with `dai-v`, such as `dai-v0.2.13.1`. This
avoids triggering the upstream release workflow, and each image remains pinned
to a specific reviewed source revision.

The `Build Custom Image` workflow publishes ARM64 images to:

```text
ghcr.io/aohuidai/sub2api-expiry-scheduler:<custom-tag>
```

Because this repository is private, the Oracle host needs a GitHub token with
read-only package access before it can pull from GHCR. Keep that token outside
this repository and outside Compose files. The image is intentionally never
tagged `latest`.

## Updating From Official Sub2API

`Propose Upstream Sync` runs daily and can also be run manually. It obtains the
latest official GitHub release and, only when needed, opens a branch named
`sync/upstream-<tag>` and a pull request to `main`.

It does not merge the PR, build an image, or touch the server. If Git reports a
conflict, the workflow stops before pushing a partial branch. Resolve that
conflict locally, preserve the tests below, and open the sync PR yourself.

Before accepting a sync PR:

1. Check the upstream release notes and the PR diff.
2. Verify the scheduler setting, tests, and UI still build.
3. Merge the reviewed PR into `main`.
4. Create and push a new annotated `dai-v...` tag to build a fresh ARM64 image.
5. Verify the GHCR image digest before changing the server's pinned image tag.

Useful local commands:

```bash
git fetch upstream --tags
git switch main
git switch -c sync/upstream-vX.Y.Z
git merge --no-ff upstream/vX.Y.Z
```

## Verification

Run the focused checks before publishing a custom tag:

```bash
cd backend
go test ./internal/service ./internal/handler/admin
go test -tags=unit ./internal/server

cd ../frontend
pnpm install --frozen-lockfile
pnpm test:run -- src/views/admin/__tests__/SettingsView.spec.ts
pnpm typecheck
```

After deployment, verify the health endpoint, the admin settings response, and
the score snapshot before enabling `long`. Enable it only after quota data has
recorded future long-window reset times for the accounts expected to take part.

## Rollback

Keep the last known-good custom image tag in the server change log. Roll back
by restoring that exact pinned tag and restarting only the Sub2API service; the
database and account data are not part of an image rollback. Do not use
`latest` for either deployment or rollback.

## Boundaries

Never put OAuth credentials, API keys, database passwords, or GitHub package
tokens in this repository, workflow logs, issue text, or pull-request bodies.
The fork changes scheduling behavior only; it does not modify account records,
API keys, groups, or routes by itself.
