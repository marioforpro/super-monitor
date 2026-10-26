# super-monitor

External uptime checks for the four Super products. Runs on GitHub Actions every 15 minutes, off any
single machine, so it keeps watching when the dev machine is asleep, offline or dead.

## What it checks

| Product | Check | Passes when |
|---|---|---|
| Super Prompts | `https://superprompts.pro` | 200 + title contains «Super Prompts» |
| Super Prompts | `https://app.superprompts.pro/signup` | 200 + «Create Account» + Turnstile widget present |
| Super Prompts | `https://app.superprompts.pro/api/health` | 200 + `{"ok": true}` |
| Super Podcatch | `https://superpodcatch.com/es` | 200 + «Super Podcatch» + ≥ 3 prices in € rendered |
| Super Podcatch | Supabase REST | `podcasts?select=slug&limit=1` returns rows, using the **public** URL + publishable key read live from `superpodcatch.com/config.js` (no secret stored here) |
| Super Downloads | `https://superdownloads.app` | 200 + «Super Downloads» + the DMG link |
| Super Downloads | `releases/latest/download/latest.json` | 200, version ≥ 1.5.5, both macOS platforms have url + signature |
| Super Downloads | both DMGs (`_aarch64`, `_x64`) | `HEAD` 200 and > 5 MB |
| Super Guides | `https://superguides.pro` | 200 + «Super Guides» |
| Super Guides | `https://superguides.pro/safe-zones` | 200 + «safe zones» |

Every check runs once; whatever fails is **retried once after 60 s**. Only a check that fails twice
fails the job. Each run writes a table to the run's summary page.

Run it locally: `python3 check.py` (standard library only).

## How the alert arrives

A failed job → GitHub emails the account that owns the workflow. That depends on the notification
setting being on: <https://github.com/settings/notifications> → **Actions** → «Email» ticked, «Only
notify for failed workflows» ticked (GitHub's default).

Prove the email still arrives (adds one check that always fails, retry after 5 s):

```bash
gh workflow run super-monitor -R marioforpro/super-monitor -f selftest_fail=true
```

**Dead-man (optional, recommended):** create a free check at healthchecks.io (period 15 min, grace
30 min), then `gh secret set HC_PING_URL -R marioforpro/super-monitor` with its ping URL. Every green
run pings it; if runs stop happening at all, healthchecks.io sends the email instead.

## Cadence

Every 15 minutes (`3,18,33,48 * * * *` — off the round minutes, where GitHub drops the most runs). The repo is public on purpose: it holds only public URLs and no
secrets, and Actions minutes are free and unlimited on public repos. GitHub's scheduler can delay or
skip runs under load, so the real spacing is 15 min or a little more.

Public repos have one catch: GitHub disables scheduled workflows after 60 days without repository
activity. The `keepalive` job (Mondays 06:41 UTC) re-enables the workflow through the API so that
never happens; the dead-man ping is the backstop.

## Pause / resume

```bash
gh workflow disable super-monitor -R marioforpro/super-monitor   # pause (e.g. planned maintenance)
gh workflow enable  super-monitor -R marioforpro/super-monitor   # resume
gh workflow run     super-monitor -R marioforpro/super-monitor   # run now
gh run list -R marioforpro/super-monitor --limit 5               # last runs
```

## Changing what it checks

Edit `CHECKS` in `check.py` — one function per check, raise `CheckFailed("why")` on failure. When a
product changes a title, a price layout or the SD release asset names, update the matching needle
here in the same change.
