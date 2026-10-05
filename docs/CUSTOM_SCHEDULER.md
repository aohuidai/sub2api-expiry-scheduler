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

Custom images use `dai-vX.Y.Z.N` tags, such as `dai-v0.2.13.1`. This avoids
triggering the upstream release workflow, and each image remains pinned to a
specific reviewed source revision. The running binary reports the compatible
semantic version `0.2.13-dai.1`, so the admin update check continues to compare
correctly against official versions.

The `Build Custom Image` workflow also publishes ARM64 images to:

```text
ghcr.io/aohuidai/sub2api-expiry-scheduler:<custom-tag>
```

The image is intentionally never tagged `latest`.

The production Oracle host currently uses a local ARM64 build from the reviewed
tag rather than pulling the private GHCR package. That keeps the repository and
package private and avoids storing a GitHub package token on the server. GHCR
is therefore a build artifact and an optional future deployment source, not a
deployment prerequisite. If GHCR is used later, give the host a dedicated
read-only `read:packages` credential outside this repository and outside
Compose files.

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
5. Deploy that exact tag only after review and a fresh server backup. Never
   change production because a GitHub workflow merely detected an upstream
   release.

Useful local commands:

```bash
git fetch upstream --tags
git switch main
git switch -c sync/upstream-vX.Y.Z
git merge --no-ff upstream/vX.Y.Z
```

### Oracle Deployment Path

For the current private deployment, archive the reviewed tag, transfer only
that source archive to the Oracle host, and build an ARM64 image there. The
running Compose image must stay pinned to the matching custom tag, for example
`sub2api-expiry-scheduler:dai-v0.2.13.1`.

Each deployment must:

1. Back up the Compose files, `.env`, PostgreSQL dump, and `/srv/sub2api/data`
   under `/srv/backups/sub2api/` before changing the image.
2. Validate the database dump with `pg_restore --list` and preserve checksums.
3. Recreate only the `sub2api` Compose service with `--no-deps`.
4. Verify Docker health, `/health`, startup logs, and the intended scheduler
   setting before treating the deployment as complete.

Do not use Sub2API's online-update button for this fork: it can replace the
custom image with an official image and remove this scheduler behavior.

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
The setting cache expires within a few seconds; a separate restart is not
required solely to switch between `short` and `long`.

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
