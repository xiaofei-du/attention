"""Decide whether a successful main CI event needs a Homebrew update."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib


REPO = "xiaofei-du/attention"


def should_dispatch(event, checked_out_sha, project_text, formula_text):
    run = event.get("workflow_run", {})
    required = {"event": "push", "status": "completed", "conclusion": "success",
                "head_branch": "main", "head_sha": checked_out_sha,
                "path": ".github/workflows/tests.yml"}
    if (event.get("repository", {}).get("full_name") != REPO
            or (run.get("head_repository") or {}).get("full_name") != REPO
            or not re.fullmatch(r"[0-9a-f]{40}", checked_out_sha)
            or any(run.get(key) != value for key, value in required.items())):
        return False
    source = tomllib.loads(project_text)["project"]["version"]
    versions = re.findall(r'^  version "([^"]+)"$', formula_text, re.MULTILINE)
    if len(versions) != 1:
        raise ValueError("Expected exactly one Homebrew formula version")

    def stable_version(value):
        if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
            raise ValueError("Expected a stable three-part numeric version")
        return tuple(map(int, value.split(".")))

    return stable_version(source) > stable_version(versions[0])


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    response = subprocess.check_output(
        ["gh", "api", "repos/xiaofei-du/homebrew-tap/contents/Formula/attention.rb?ref=main"],
        text=True, timeout=60)
    content = json.loads(response)
    if content["encoding"] != "base64":
        raise ValueError("Unexpected GitHub formula encoding")
    formula = base64.b64decode(content["content"]).decode("utf-8")
    needed = should_dispatch(event, sha, Path("pyproject.toml").read_text(), formula)
    print("Homebrew update needed" if needed else "No new version to send to Homebrew")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"needed={str(needed).lower()}\n")


if __name__ == "__main__":
    main()
