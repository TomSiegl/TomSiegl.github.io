#!/usr/bin/env python3
"""PR-closed-without-merge entry point (ticket 09 / design in ticket 05).

Triggered when a paper-candidate PR is closed without merging. Reads the
candidate's title from the file it added and its Semantic Scholar paperId
from the PR body marker, then hands both to the shared rejection-recording
scaffolding (papers_lib.record_rejection, ticket 25), which records them to
the exclusion file and commits the update straight to main.

`paper-candidate-closed.yml` only checks out `ref: main`, so the candidate
file as it existed on the closed PR's branch has to be fetched explicitly
(`git fetch` + `git show` against the PR head commit). That commit can
become unreachable by the time this runs -- e.g. GitHub's "automatically
delete head branches" setting racing the `pull_request: closed` webhook --
in which case `read_candidate_title` falls back to the PR's own title
(ticket 23) instead of letting the whole run crash and lose the rejection.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from papers_lib import (
    CANDIDATE_PR_TITLE_PREFIX,
    EXCLUSIONS_PATH,
    EXCLUSIONS_SCHEMA_NOTE,
    configure_bot_identity,
    extract_paper_id,
    is_excluded,
    parse_front_matter,
    record_rejection,
    run_git as run,
)


def find_candidate_paper_path(pr_number):
    """The candidate paper's file path and the PR's own title, from a
    single `gh pr view` call. The title is carried along so
    `read_candidate_title` has a fallback source for the candidate's title
    if the PR head commit later turns out to be unreachable (ticket 23) --
    `find_new_papers.py`'s `open_candidate_pr` always sets the PR title to
    `CANDIDATE_PR_TITLE_PREFIX + title`, so it mirrors the file content.
    """
    pr_json = run("gh", "pr", "view", pr_number, "--json", "files,title", capture=True)
    data = json.loads(pr_json)
    pr_title = data.get("title", "")
    for f in data["files"]:
        path = f["path"]
        if path.startswith("content/papers/") and path.endswith(".md") and Path(path).name != "_index.md":
            return path, pr_title
    return None, pr_title


def read_candidate_title(pr_number, head_sha, paper_path, pr_title):
    """The candidate's title, read from the paper file as it existed on the
    closed PR's head commit.

    Falls back to the PR's own title (stripped of its
    `CANDIDATE_PR_TITLE_PREFIX`) if `git fetch`/`git show` against the head
    commit fails -- e.g. the head branch was auto-deleted around the same
    time the `pull_request: closed` webhook fired, so the commit is no
    longer reachable. Without this fallback, the uncaught
    `CalledProcessError` used to crash the whole script before the
    rejection was ever recorded, letting the candidate be re-proposed by a
    future find_new_papers.py run (ticket 23).
    """
    try:
        run("git", "fetch", "origin", head_sha)
        content = run("git", "show", f"{head_sha}:{paper_path}", capture=True)
    except subprocess.CalledProcessError:
        fallback_title = pr_title
        if fallback_title.startswith(CANDIDATE_PR_TITLE_PREFIX):
            fallback_title = fallback_title[len(CANDIDATE_PR_TITLE_PREFIX):]
        print(
            f"WARNING: could not fetch/read PR #{pr_number}'s head commit "
            f"{head_sha} (git fetch/show failed; the head branch may have "
            "been deleted). The candidate file's content could NOT be "
            f"read -- falling back to the PR title ({fallback_title!r}) so "
            "the rejection is still recorded instead of being lost."
        )
        return fallback_title
    return parse_front_matter(content)["title"]


def main():
    pr_number = os.environ["PR_NUMBER"]
    head_sha = os.environ["PR_HEAD_SHA"]
    pr_body = os.environ.get("PR_BODY", "")

    paper_path, pr_title = find_candidate_paper_path(pr_number)
    if not paper_path:
        print("No candidate paper file found on this PR; nothing to record.")
        return

    # This fetch/show/parse step (with ticket 23's unreachable-commit
    # fallback) is specific to candidate rejections -- an update rejection
    # only needs the slug from the PR's file list, not the file's content --
    # and is deliberately not folded into the shared scaffolding below; see
    # record_rejection's docstring.
    title = read_candidate_title(pr_number, head_sha, paper_path, pr_title)
    paper_id = extract_paper_id(pr_body)

    configure_bot_identity()

    record_rejection(
        path=EXCLUSIONS_PATH,
        schema_note=EXCLUSIONS_SCHEMA_NOTE,
        new_entry={
            "title": title,
            "paper_id": paper_id,
            "rejected_at": date.today().isoformat(),
        },
        # Guards against double-recording: if a prior attempt's push actually
        # landed on the remote but the local subprocess call still raised
        # (e.g. a dropped connection), this retry would otherwise re-append
        # the same rejection.
        already_excluded=lambda exclusions: is_excluded(
            {"title": title, "paperId": paper_id}, exclusions
        ),
        commit_message=f"Record rejection: {title}",
    )


if __name__ == "__main__":
    main()
