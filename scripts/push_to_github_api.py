#!/usr/bin/env python
"""Push the current working tree to a GitHub repository over the REST API.

Why this exists: `git push` needs plain HTTPS access to github.com, which may be
blocked in a sandboxed/proxied environment.  The REST endpoint (api.github.com)
is often reachable even when the git protocol is not, so we build the commit by
hand: upload blobs -> create a tree -> create a commit -> move the branch ref.

Usage:
    python scripts/push_to_github_api.py --owner hxdanke --repo apphysicsc-data-base
        --token <PAT>            # or set GITHUB_TOKEN in the environment
        [--branch main] [--message "..."] [--dry-run]

The token needs "Contents: read and write" on the target repository.
Everything is streamed file by file, so no secrets ever touch the repo files.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svgz", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pdf", ".zip",
}


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #
def tracked_files() -> list[tuple[str, str]]:
    """Return [(path, mode)] for every file tracked by git in the work tree."""
    out = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")
    items: list[tuple[str, str]] = []
    for entry in out.split("\0"):
        if not entry.strip():
            continue
        meta, _, path = entry.partition("\t")
        mode = meta.split(" ", 1)[0]  # 100644 / 100755 / 120000(symlink)
        items.append((path, mode))
    return items


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _request(method: str, url: str, token: str, payload: dict | None = None,
             retries: int = 3):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8", "replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                last_err = RuntimeError(f"HTTP {exc.code}: {detail[:200]}")
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"{method} {url} failed: HTTP {exc.code}\n{detail[:600]}"
            ) from exc
        except urllib.error.URLError as exc:
            last_err = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc
    raise RuntimeError(f"{method} {url} failed: {last_err}")


def get_ref_sha(owner: str, repo: str, branch: str, token: str) -> str | None:
    """Return the current commit sha of branch, or None when branch is absent."""
    try:
        data = _request("GET", f"{API}/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
        return data.get("object", {}).get("sha")
    except RuntimeError as exc:
        if "HTTP 404" in str(exc) or "HTTP 409" in str(exc):
            return None
        raise


# --------------------------------------------------------------------------- #
# push pipeline
# --------------------------------------------------------------------------- #
def push(owner: str, repo: str, branch: str, token: str, message: str,
         dry_run: bool = False) -> None:
    files = tracked_files()
    total_bytes = 0
    print(f"[1/5] repository   : {owner}/{repo} (branch {branch})")
    print(f"[2/5] files tracked: {len(files)}")

    if dry_run:
        for path, mode in files:
            total_bytes += (ROOT / path).stat().st_size
        print(f"[dry-run] nothing uploaded; would send {total_bytes / 1e6:.1f} MB")
        return

    parent = get_ref_sha(owner, repo, branch, token)
    print(f"[3/5] base commit  : {parent or '(none - first commit)'}")

    tree_entries: list[dict] = []
    uploaded = 0
    for idx, (path, mode) in enumerate(files, start=1):
        full = ROOT / path
        raw = full.read_bytes()
        total_bytes += len(raw)
        is_binary = full.suffix.lower() in BINARY_SUFFIXES
        content = base64.b64encode(raw).decode("ascii")
        blob = _request(
            "POST", f"{API}/repos/{owner}/{repo}/git/blobs", token,
            {"content": content, "encoding": "base64"},
        )
        tree_entries.append({
            "path": path,
            "mode": mode if mode in ("100644", "100755") else "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        uploaded += 1
        if idx % 25 == 0 or idx == len(files):
            print(f"      blob {idx}/{len(files)}  ({total_bytes / 1e6:.1f} MB)"
                  + ("  [binary]" if is_binary else ""))

    tree = _request("POST", f"{API}/repos/{owner}/{repo}/git/trees", token,
                    {"tree": tree_entries})
    print(f"[4/5] tree created : {tree['sha']} ({uploaded} entries)")

    commit_payload: dict = {"message": message, "tree": tree["sha"]}
    if parent:
        commit_payload["parents"] = [parent]
    commit = _request("POST", f"{API}/repos/{owner}/{repo}/git/commits", token,
                      commit_payload)
    print(f"[5/5] commit made  : {commit['sha']}")

    if parent:
        _request("PATCH", f"{API}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                 token, {"sha": commit["sha"]})
    else:
        _request("POST", f"{API}/repos/{owner}/{repo}/git/refs", token,
                 {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
    print(f"done: {branch} -> {commit['sha'][:12]}  "
          f"({len(files)} files, {total_bytes / 1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", default="hxdanke")
    ap.add_argument("--repo", default="apphysicsc-data-base")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ap.add_argument("--message", default="v0.1 initial version: AP Physics C Mechanics question bank")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.token and not args.dry_run:
        print("error: provide --token or set GITHUB_TOKEN", file=sys.stderr)
        return 2

    try:
        push(args.owner, args.repo, args.branch, args.token,
             args.message, args.dry_run)
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
