#!/usr/bin/env python3
"""Weekly papers-detection entry point (ticket 09 / design in ticket 05).

Queries Semantic Scholar for Tom's papers, drops anything already published,
previously rejected, or already proposed via an open paper-candidate/* PR,
dedupes within-run API duplicates, and opens one PR per remaining candidate
using the workflow's own GITHUB_TOKEN.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from papers_lib import (
    CANDIDATE_PR_TITLE_PREFIX,
    EXCLUSIONS_PATH,
    PAPERS_DIR,
    build_paper_fields,
    checkout_fresh_main,
    configure_bot_identity,
    dedupe_candidates,
    fetch_candidates,
    fetch_open_candidate_prs,
    is_already_published,
    is_excluded,
    load_exclusions,
    load_published_papers,
    normalize_title,
    run_git,
    unique_slug,
    write_paper_file,
)


def open_candidate_pr(candidate, fields, slug):
    branch = f"paper-candidate/{slug}"
    checkout_fresh_main()
    run_git("git", "checkout", "-b", branch)

    paper_path = PAPERS_DIR / f"{slug}.md"
    write_paper_file(paper_path, fields)

    run_git("git", "add", str(paper_path))
    run_git("git", "commit", "-m", f"Add paper candidate: {fields['title']}")
    run_git("git", "push", "-u", "origin", branch)

    dash = "—"
    venue = fields["venue"] or dash
    year = fields["year"] or dash
    doi = fields["doi"] or dash
    arxiv_id = fields["arxiv_id"] or dash
    body = (
        "Semantic Scholar hit for Tom Siegl's author profile, opened by the "
        "weekly papers-detection workflow.\n\n"
        f"**Venue:** {venue} ({year})\n"
        f"**DOI:** {doi}\n"
        f"**arXiv:** {arxiv_id}\n\n"
        f"Merge to publish. Close without merging to reject {dash} this "
        "automatically records the candidate to the exclusion file so it "
        "isn't proposed again.\n\n"
        f"<!-- semantic-scholar-paper-id: {candidate.get('paperId', '')} -->"
    )
    run_git(
        "gh",
        "pr",
        "create",
        "--title",
        f"{CANDIDATE_PR_TITLE_PREFIX}{fields['title']}",
        "--body",
        body,
        "--base",
        "main",
        "--head",
        branch,
    )


def main():
    candidates = fetch_candidates()
    exclusions = load_exclusions(EXCLUSIONS_PATH)
    published = load_published_papers()
    open_prs = fetch_open_candidate_prs()

    new_candidates = []
    for candidate in candidates:
        title_norm = normalize_title(candidate.get("title"))
        if not title_norm:
            continue
        if is_excluded(candidate, exclusions, title_norm):
            continue
        if is_already_published(candidate, published, title_norm):
            continue
        if is_excluded(candidate, open_prs, title_norm):
            continue
        new_candidates.append(candidate)

    new_candidates = dedupe_candidates(new_candidates)

    if not new_candidates:
        print("No new paper candidates.")
        return

    configure_bot_identity()

    used_slugs = set()
    for candidate in new_candidates:
        fields = build_paper_fields(candidate)
        slug = unique_slug(fields["title"], extra_used=used_slugs)
        used_slugs.add(slug)
        print(f"Opening PR for candidate: {fields['title']} ({slug})")
        open_candidate_pr(candidate, fields, slug)


if __name__ == "__main__":
    main()
