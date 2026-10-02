#!/usr/bin/env python3
"""Weekly preprint-publication-scan entry point (ticket 15).

Re-checks every content/papers/<slug>.md still marked `venue: "arXiv
preprint"` against Semantic Scholar, and opens one PR per paper that now
reports a real publication venue, updating its venue/doi/external_url.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from papers_lib import (
    PAPER_UPDATE_BRANCH_PREFIX,
    PREPRINT_VENUE,
    UPDATE_EXCLUSIONS_PATH,
    UPDATE_PR_TITLE_PREFIX,
    apply_publication_update,
    checkout_fresh_main,
    configure_bot_identity,
    fetch_candidates,
    fetch_open_update_branches,
    find_publication_update,
    is_update_excluded,
    load_exclusions,
    load_published_papers_with_paths,
    run_git,
    write_paper_file,
)


def open_update_pr(path, fields, candidate):
    slug = Path(path).stem
    branch = f"{PAPER_UPDATE_BRANCH_PREFIX}{slug}"
    checkout_fresh_main()
    run_git("git", "checkout", "-b", branch)

    write_paper_file(path, fields)

    run_git("git", "add", str(path))
    run_git("git", "commit", "-m", f"Update publication venue: {fields['title']}")
    run_git("git", "push", "-u", "origin", branch)

    dash = "—"
    body = (
        "Semantic Scholar now reports a publication venue for this paper, "
        "found by the weekly papers-detection workflow's preprint scan.\n\n"
        f"**Venue:** {fields['venue'] or dash}\n"
        f"**DOI:** {fields['doi'] or dash}\n\n"
        "Merge to update the site. Close without merging to leave it as a "
        "preprint for now.\n\n"
        f"<!-- semantic-scholar-paper-id: {candidate.get('paperId', '')} -->"
    )
    run_git(
        "gh",
        "pr",
        "create",
        "--title",
        f"{UPDATE_PR_TITLE_PREFIX}{fields['title']}",
        "--body",
        body,
        "--base",
        "main",
        "--head",
        branch,
    )


def main():
    preprints = [
        (path, fields)
        for path, fields in load_published_papers_with_paths()
        if fields.get("venue") == PREPRINT_VENUE
    ]
    if not preprints:
        print("No preprints to check.")
        return

    candidates = fetch_candidates()
    open_branches = fetch_open_update_branches()
    update_exclusions = load_exclusions(UPDATE_EXCLUSIONS_PATH)

    updates = []
    for path, fields in preprints:
        slug = Path(path).stem
        if f"{PAPER_UPDATE_BRANCH_PREFIX}{slug}" in open_branches:
            continue
        if is_update_excluded(slug, update_exclusions):
            continue
        candidate = find_publication_update(fields, candidates)
        if candidate is None:
            continue
        updates.append((path, fields, candidate))

    if not updates:
        print("No publication updates found.")
        return

    configure_bot_identity()

    for path, fields, candidate in updates:
        updated_fields = apply_publication_update(fields, candidate)
        print(f"Opening PR for publication update: {fields['title']}")
        open_update_pr(path, updated_fields, candidate)


if __name__ == "__main__":
    main()
