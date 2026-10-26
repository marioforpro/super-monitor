#!/usr/bin/env python3
"""super-monitor — live checks for the four Super products.

Runs every check once; whatever fails is retried once after RETRY_DELAY seconds
(a single blip is not an alert). Anything still failing makes the script exit 1,
which fails the GitHub Actions job, which makes GitHub email the repo owner.

Standard library only, so the workflow needs no install step.
Run locally: python3 check.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 20
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "60"))
# SELFTEST_FAIL=1 adds one check that always fails: proves the failure email still arrives.
SELFTEST_FAIL = os.environ.get("SELFTEST_FAIL") == "1"
UA = "Mozilla/5.0 (compatible; super-monitor/1.0; +https://github.com/marioforpro/super-monitor)"
SD_MIN_VERSION = (1, 5, 5)
SD_RELEASE = "https://github.com/marioforpro/super-downloads/releases/latest/download"


class CheckFailed(Exception):
    pass


def fetch(url: str, method: str = "GET", headers: dict | None = None) -> tuple[int, str, dict]:
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace") if method == "GET" else ""
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        raise CheckFailed(f"HTTP {e.code} on {url}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CheckFailed(f"unreachable {url}: {e}")


def page(url: str, *needles: str) -> str:
    """GET must be 200 and contain every needle (case-insensitive)."""
    status, body, _ = fetch(url)
    if status != 200:
        raise CheckFailed(f"HTTP {status}")
    low = body.lower()
    missing = [n for n in needles if n.lower() not in low]
    if missing:
        raise CheckFailed(f"200 but missing {missing}")
    return body


# --- Super Prompts ------------------------------------------------------------
def sp_landing():
    page("https://superprompts.pro", "<title", "Super Prompts")


def sp_signup():
    page("https://app.superprompts.pro/signup", "Create Account", "turnstile")


def sp_health():
    _, body, _ = fetch("https://app.superprompts.pro/api/health")
    if not json.loads(body).get("ok"):
        raise CheckFailed(f"ok != true: {body[:120]}")


# --- Super Podcatch -----------------------------------------------------------
def spc_landing():
    body = page("https://superpodcatch.com/es", "Super Podcatch")
    prices = set(re.findall(r"\d+(?:,\d+)?\s?€", body))
    if len(prices) < 3:
        raise CheckFailed(f"prices not rendered (found {sorted(prices)})")


def spc_supabase():
    # Same public URL + publishable key the landing ships in config.js — no secret.
    _, cfg, _ = fetch("https://superpodcatch.com/config.js")
    url = re.search(r'supabaseUrl:\s*"([^"]+)"', cfg)
    key = re.search(r'supabaseKey:\s*"([^"]+)"', cfg)
    if not (url and key):
        raise CheckFailed("config.js lost supabaseUrl/supabaseKey")
    k = key.group(1)
    _, body, _ = fetch(f"{url.group(1)}/rest/v1/podcasts?select=slug&limit=1",
                       headers={"apikey": k, "Authorization": f"Bearer {k}"})
    rows = json.loads(body)
    if not (isinstance(rows, list) and rows):
        raise CheckFailed(f"podcasts query returned no rows: {body[:120]}")


# --- Super Downloads ----------------------------------------------------------
def sd_landing():
    page("https://superdownloads.app", "Super Downloads", "Super-Downloads_aarch64.dmg")


def sd_latest_json():
    _, body, _ = fetch(f"{SD_RELEASE}/latest.json")
    data = json.loads(body)
    ver = data.get("version", "")
    parts = tuple(int(x) for x in re.findall(r"\d+", ver)[:3])
    if parts < SD_MIN_VERSION:
        raise CheckFailed(f"version {ver!r} < {'.'.join(map(str, SD_MIN_VERSION))}")
    plats = data.get("platforms", {})
    for p in ("darwin-aarch64", "darwin-x86_64"):
        if not (plats.get(p, {}).get("url") and plats.get(p, {}).get("signature")):
            raise CheckFailed(f"latest.json {ver}: {p} missing url/signature")


def _dmg(name: str):
    status, _, headers = fetch(f"{SD_RELEASE}/{name}", method="HEAD")
    size = int(headers.get("Content-Length") or 0)
    if status != 200 or size < 5_000_000:
        raise CheckFailed(f"HEAD {status}, {size} bytes")


def sd_dmg_arm():
    _dmg("Super-Downloads_aarch64.dmg")


def sd_dmg_intel():
    _dmg("Super-Downloads_x64.dmg")


# --- Super Guides -------------------------------------------------------------
def sg_landing():
    page("https://superguides.pro", "Super Guides")


def sg_safe_zones():
    page("https://superguides.pro/safe-zones", "safe zones")


CHECKS = [
    ("SP", "landing superprompts.pro", sp_landing),
    ("SP", "signup form (app)", sp_signup),
    ("SP", "/api/health", sp_health),
    ("SPC", "landing /es + prices", spc_landing),
    ("SPC", "Supabase REST (public key)", spc_supabase),
    ("SD", "landing superdownloads.app", sd_landing),
    ("SD", "updater latest.json >= 1.5.5", sd_latest_json),
    ("SD", "DMG Apple Silicon", sd_dmg_arm),
    ("SD", "DMG Intel", sd_dmg_intel),
    ("SG", "landing superguides.pro", sg_landing),
    ("SG", "/safe-zones", sg_safe_zones),
]


def run(fn) -> tuple[bool, str, float]:
    t0 = time.monotonic()
    try:
        fn()
        return True, "ok", time.monotonic() - t0
    except CheckFailed as e:
        return False, str(e), time.monotonic() - t0
    except Exception as e:  # a parse error is a failure too, never a crash
        return False, f"{type(e).__name__}: {e}", time.monotonic() - t0


def selftest_fail():
    raise CheckFailed("self-test: this check always fails (SELFTEST_FAIL=1)")


def main() -> int:
    if SELFTEST_FAIL:
        CHECKS.append(("TEST", "self-test failure", selftest_fail))
    results = {name: run(fn) for _, name, fn in CHECKS}
    failed = [c for c in CHECKS if not results[c[1]][0]]
    if failed:
        print(f"{len(failed)} check(s) failed — retrying once in {RETRY_DELAY}s", flush=True)
        time.sleep(RETRY_DELAY)
        for _, name, fn in failed:
            ok, msg, dt = run(fn)
            first = results[name][1]
            results[name] = (ok, msg if not ok else f"ok on retry (first: {first})", dt)

    lines = ["| | Product | Check | Result | s |", "|---|---|---|---|---|"]
    bad = 0
    for prod, name, _ in CHECKS:
        ok, msg, dt = results[name]
        bad += not ok
        lines.append(f"| {'✅' if ok else '❌'} | {prod} | {name} | {msg} | {dt:.1f} |")
    head = f"**super-monitor:** {len(CHECKS) - bad}/{len(CHECKS)} green"
    report = head + "\n\n" + "\n".join(lines) + "\n"
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
