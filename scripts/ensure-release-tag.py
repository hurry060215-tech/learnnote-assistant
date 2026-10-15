"""Create an absent exact version tag only after the release workflow's build gates.

Uses the workflow's existing GitHub token through gh. Never updates/deletes refs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def ensure_tag(tag, commit, repository):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Invalid release tag")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Exact commit SHA required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    head = run("git", "rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != commit:
        raise ValueError("Checkout does not match release commit")
    version = json.loads((ROOT / "web/release-notes.json").read_text(encoding="utf-8"))["current"]
    if tag != "v" + version:
        raise ValueError("Release tag does not match client version")
    endpoint = f"repos/{repository}/git/ref/tags/{tag}"
    result = run("gh", "api", endpoint)
    if result.returncode:
        # Fail closed on authentication, permissions, network and server errors.
        if "HTTP 404" not in result.stderr:
            raise RuntimeError("Cannot inspect release tag")
        created = run("gh", "api", "--method", "POST", f"repos/{repository}/git/refs",
                      "-f", f"ref=refs/tags/{tag}", "-f", f"sha={commit}")
        if created.returncode:
            raise RuntimeError("Tag creation failed; no release was published")
        result = run("gh", "api", endpoint)
        if result.returncode:
            raise RuntimeError("Created tag could not be verified")
    obj = json.loads(result.stdout)["object"]
    if obj["type"] == "tag":
        annotated = run("gh", "api", f"repos/{repository}/git/tags/{obj['sha']}")
        if annotated.returncode:
            raise RuntimeError("Cannot verify annotated tag")
        obj = json.loads(annotated.stdout)["object"]
    if obj["type"] != "commit" or obj["sha"] != commit:
        raise RuntimeError("Existing tag does not match release commit; never overwritten")
    return commit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for key in ("tag", "commit", "repository"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    ensure_tag(args.tag, args.commit, args.repository)
    print("Release tag verified at exact build commit")
