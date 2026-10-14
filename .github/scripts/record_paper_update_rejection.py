#!/usr/bin/env python3
"""PR-closed-without-merge entry point for update PRs (ticket 15).

Triggered when a paper-update PR is closed without merging. Reads the
paper's slug from the file the PR touched and its proposed venue and
Semantic Scholar paperId from the PR body markers, then hands all three to
the shared rejection-recording scaffolding (papers_lib.record_rejection,
ticket 25), which records them to the update-exclusion file and commits the
update straight to main. The exclusion is scoped to slug + venue, so the
preprint scan doesn't re-propose the same rejected venue every week, but
still proposes a later, different venue for the same paper.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from papers_lib import (
    UPDATE_EXCLUSIONS_PATH,
    UPDATE_EXCLUSIONS_SCHEMA_NOTE,
    configure_bot_identity,
    extract_paper_id,
    extract_venue,
    is_update_excluded,
    record_rejection,
    run_git as run,
)


def find_updated_paper_path(pr_number):
    files_json = run("gh", "pr", "view", pr_number, "--json", "files", capture=True)
    files = json.loads(files_json)["files"]
    for f in files:
        path = f["path"]
        if path.startswith("content/papers/") and path.endswith(".md") and Path(path).name != "_index.md":
            return path
    return None


def main():
    pr_number = os.environ["PR_NUMBER"]
    pr_body = os.environ.get("PR_BODY", "")

    paper_path = find_updated_paper_path(pr_number)
    if not paper_path:
        print("No updated paper file found on this PR; nothing to record.")
        return

    slug = Path(paper_path).stem
    paper_id = extract_paper_id(pr_body)
    venue = extract_venue(pr_body)

    configure_bot_identity()

    record_rejection(
        path=UPDATE_EXCLUSIONS_PATH,
        schema_note=UPDATE_EXCLUSIONS_SCHEMA_NOTE,
        new_entry={
            "slug": slug,
            "venue": venue,
            "paper_id": paper_id,
            "rejected_at": date.today().isoformat(),
        },
        already_excluded=lambda exclusions: is_update_excluded(slug, venue, exclusions),
        commit_message=f"Record publication update rejection: {slug}",
    )


if __name__ == "__main__":
    main()
