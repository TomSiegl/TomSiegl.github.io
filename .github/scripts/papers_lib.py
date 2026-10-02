"""Shared helpers for the papers-detection automation (ticket 09).

Content files under content/papers/ use Hugo front matter whose values are
all written in JSON-compatible flow syntax (e.g. authors: ["A", "B"],
doi: null), so front matter is parsed/rendered with the stdlib json module
instead of pulling in a YAML dependency.

Exclusion file schema (.github/data/paper-exclusions.json): a JSON object
with an "exclusions" list; each entry has "title" (candidate title at
rejection time), "paper_id" (Semantic Scholar paperId) and "rejected_at"
(ISO date). A candidate is skipped if its title or paperId matches an entry.

Update-exclusion file schema (.github/data/paper-update-exclusions.json,
ticket 15): same shape, but keyed by "slug" (the content/papers/<slug>.md
file a rejected publication-venue update touched) instead of title/paperId.
"""

import json
import re
import subprocess
import urllib.request
from pathlib import Path

AUTHOR_ID = "2362086282"  # Tom Siegl; confirmed unique match in ticket 03
API_URL = (
    f"https://api.semanticscholar.org/graph/v1/author/{AUTHOR_ID}/papers"
    "?fields=paperId,title,externalIds,year,venue,authors"
)

EXCLUSIONS_PATH = Path(".github/data/paper-exclusions.json")
UPDATE_EXCLUSIONS_PATH = Path(".github/data/paper-update-exclusions.json")
PAPERS_DIR = Path("content/papers")
CANDIDATE_PR_TITLE_PREFIX = "New paper candidate: "
UPDATE_PR_TITLE_PREFIX = "Update publication venue: "
PAPER_UPDATE_BRANCH_PREFIX = "paper-update/"
PREPRINT_VENUE = "arXiv preprint"
PAPER_ID_RE = re.compile(r"<!--\s*semantic-scholar-paper-id:\s*(\S*?)\s*-->")

MAX_PUSH_ATTEMPTS = 5

FIELD_ORDER = [
    "title",
    "authors",
    "venue",
    "year",
    "doi",
    "arxiv_id",
    "external_url",  # not "url": Hugo reserves that key for the page's own output path
    "source",
    "selected",
]

EXCLUSIONS_SCHEMA_NOTE = (
    "One entry per rejected paper candidate. 'title' is the candidate's title "
    "at rejection time (matched case/whitespace-insensitively); 'paper_id' is "
    "its Semantic Scholar paperId. The papers-detection workflow skips any "
    "future candidate whose title or paper_id matches an entry here. "
    "'rejected_at' is the ISO date the candidate's PR was closed without merging."
)

UPDATE_EXCLUSIONS_SCHEMA_NOTE = (
    "One entry per rejected publication-venue update (ticket 15). 'slug' is "
    "the content/papers/<slug>.md file the update PR touched; 'paper_id' is "
    "the Semantic Scholar paperId that triggered it. The preprint-scan skips "
    "any future update for a slug that matches an entry here, so a rejected "
    "venue match isn't re-proposed every week. 'rejected_at' is the ISO date "
    "the update PR was closed without merging."
)


def fetch_candidates():
    """Fetch Tom's papers from the Semantic Scholar author API."""
    req = urllib.request.Request(
        API_URL, headers={"User-Agent": "TomSiegl.github.io papers-detection workflow"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    return payload.get("data", [])


def run_git(*args, capture=False):
    """Run a git/gh subprocess call, shared by both automation entry points."""
    result = subprocess.run(args, check=True, capture_output=capture, text=True)
    return result.stdout if capture else None


def checkout_fresh_main():
    run_git("git", "fetch", "origin", "main")
    run_git("git", "checkout", "-B", "main", "origin/main")


def configure_bot_identity():
    run_git("git", "config", "user.name", "github-actions[bot]")
    run_git("git", "config", "user.email", "github-actions[bot]@users.noreply.github.com")


def extract_paper_id(pr_body):
    match = PAPER_ID_RE.search(pr_body or "")
    return match.group(1) if match else ""


def fetch_open_candidate_prs():
    """Open paper-candidate/* PRs, shaped like exclusion entries for is_excluded().

    Lets find_new_papers.py skip candidates that already have an open PR,
    instead of re-proposing them on every weekly run while the PR is pending.
    """
    output = run_git(
        "gh",
        "pr",
        "list",
        "--state",
        "open",
        "--json",
        "headRefName,title,body",
        "--limit",
        "100",
        capture=True,
    )
    prs = json.loads(output)
    result = []
    for pr in prs:
        if not pr.get("headRefName", "").startswith("paper-candidate/"):
            continue
        title = pr.get("title", "")
        if title.startswith(CANDIDATE_PR_TITLE_PREFIX):
            title = title[len(CANDIDATE_PR_TITLE_PREFIX):]
        result.append({"title": title, "paper_id": extract_paper_id(pr.get("body", ""))})
    return result


def dedupe_candidates(candidates):
    """Drop within-run duplicates (same paperId or normalized title).

    Guards against the author-papers API returning two records for the same
    paper under different paperIds (seen in ticket 03 for a preprint/published
    split), which would otherwise pass the exclusion/published checks twice
    and open two PRs for one paper.
    """
    seen_ids = set()
    seen_titles = set()
    deduped = []
    for candidate in candidates:
        paper_id = candidate.get("paperId")
        title_norm = normalize_title(candidate.get("title"))
        if paper_id and paper_id in seen_ids:
            continue
        if title_norm and title_norm in seen_titles:
            continue
        if paper_id:
            seen_ids.add(paper_id)
        if title_norm:
            seen_titles.add(title_norm)
        deduped.append(candidate)
    return deduped


def normalize_title(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug[:60].strip("-") or "paper"


def unique_slug(title, papers_dir=PAPERS_DIR, extra_used=()):
    """Slug not already on disk under papers_dir, nor in extra_used.

    extra_used covers slugs claimed earlier in the same run: each candidate
    is committed to its own branch off a freshly reset main, so a sibling
    candidate's file from earlier in the run never appears on disk.
    """
    base = slugify(title)
    candidate = base
    i = 2
    while (Path(papers_dir) / f"{candidate}.md").exists() or candidate in extra_used:
        candidate = f"{base}-{i}"
        i += 1
    return candidate


def parse_front_matter(text):
    """Parse a content file's front matter into a field dict."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing front matter delimiter")
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        key, _, raw_value = line.partition(":")
        fields[key.strip()] = json.loads(raw_value.strip())
    missing = [key for key in FIELD_ORDER if key not in fields]
    if missing:
        raise ValueError(f"front matter missing required field(s): {missing}")
    return fields


def read_front_matter(path):
    return parse_front_matter(Path(path).read_text(encoding="utf-8"))


def read_body(path):
    """The page body below a content file's closing front-matter delimiter
    (ticket 16: a paper's detail-page content), or "" if the file doesn't
    exist or has none.
    """
    if not Path(path).exists():
        return ""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :]).strip("\n")
    return ""


def render_front_matter(fields):
    """Fields outside FIELD_ORDER (e.g. a hand-added `build` override that
    enables a paper's detail page, ticket 16) are preserved at the end, so
    an automated rewrite of this file never silently drops them.
    """
    lines = ["---"]
    for key in FIELD_ORDER:
        lines.append(f"{key}: {json.dumps(fields[key])}")
    for key, value in fields.items():
        if key not in FIELD_ORDER:
            lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def write_paper_file(path, fields, body=None):
    """Write `fields` as front matter, followed by `body` (a paper's
    detail-page content, ticket 16). `body` defaults to whatever body the
    file already has on disk, so an automated field update (e.g. a
    publication-venue update) never silently deletes it.
    """
    if body is None:
        body = read_body(path)
    text = render_front_matter(fields)
    if body:
        text += "\n" + body.strip("\n") + "\n"
    Path(path).write_text(text, encoding="utf-8")


def load_published_papers_with_paths(papers_dir=PAPERS_DIR):
    papers = []
    for path in sorted(Path(papers_dir).glob("*.md")):
        if path.name == "_index.md":
            continue
        try:
            papers.append((path, read_front_matter(path)))
        except ValueError as exc:
            print(f"Warning: skipping {path}: {exc}")
            continue
    return papers


def load_published_papers(papers_dir=PAPERS_DIR):
    return [fields for _, fields in load_published_papers_with_paths(papers_dir)]


def load_exclusions(path):
    """Load an exclusion store's entries (ticket 25: shared by the
    paper-candidate exclusions file and the paper-update exclusions file --
    the two stores differ only in path/schema note/entry shape, not in how
    they're loaded).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("exclusions", [])


def save_exclusions(exclusions, path, schema_note):
    """Save an exclusion store's entries, tagged with `schema_note` (ticket
    25; see load_exclusions).
    """
    data = {"_schema": schema_note, "exclusions": exclusions}
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def is_excluded(candidate, exclusions, title_norm=None):
    """Paper-candidate exclusion match: title or Semantic Scholar paperId.

    Kept distinct from is_update_excluded (ticket 25) -- candidates are
    matched two ways (title or paperId) because a candidate's title at
    rejection time may differ slightly from how it resurfaces later, while
    an update rejection is keyed by the stable content/papers/<slug>.md path
    the update PR touched, so a single slug match is all it needs.
    """
    title_norm = title_norm if title_norm is not None else normalize_title(candidate.get("title"))
    paper_id = candidate.get("paperId")
    for entry in exclusions:
        if paper_id and entry.get("paper_id") == paper_id:
            return True
        if title_norm and normalize_title(entry.get("title")) == title_norm:
            return True
    return False


def is_update_excluded(slug, exclusions):
    """Paper-update exclusion match: slug only. See is_excluded."""
    return any(entry.get("slug") == slug for entry in exclusions)


def record_rejection(path, schema_note, new_entry, already_excluded, commit_message):
    """Shared retry/commit/push scaffolding for recording a rejection to an
    exclusion store (ticket 25), used by record_paper_rejection.py and
    record_paper_update_rejection.py.

    Each caller resolves its own `new_entry` (what to append), the
    `already_excluded(exclusions)` guard (how to tell this rejection was
    already recorded by a prior attempt whose push actually landed but whose
    local subprocess call still raised -- e.g. a dropped connection), and
    `commit_message` before calling this; that resolution step is genuinely
    different per caller (a candidate rejection needs its title read off the
    PR head commit via git fetch/show, an update rejection only needs the
    slug from the PR's file list) and stays each script's own logic.

    On each attempt: checks out a fresh main, loads `path`, returns early if
    `already_excluded` says this rejection is already recorded, otherwise
    appends `new_entry`, saves, commits `path`, and pushes to main -- retrying
    against a freshly re-fetched main on a non-fast-forward push (the two
    callers' workflows also each serialize their own runs via a concurrency
    group, but this covers races with any other push to main).
    """
    for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
        checkout_fresh_main()

        exclusions = load_exclusions(path)
        if already_excluded(exclusions):
            print("Rejection already recorded on main; nothing more to do.")
            return
        exclusions.append(new_entry)
        save_exclusions(exclusions, path, schema_note)

        run_git("git", "add", str(path))
        run_git("git", "commit", "-m", commit_message)
        try:
            run_git("git", "push", "origin", "main")
            return
        except subprocess.CalledProcessError:
            if attempt == MAX_PUSH_ATTEMPTS:
                raise
            print(f"Push rejected (attempt {attempt}/{MAX_PUSH_ATTEMPTS}); retrying against latest main.")


def is_already_published(candidate, published, title_norm=None):
    title_norm = title_norm if title_norm is not None else normalize_title(candidate.get("title"))
    external = candidate.get("externalIds") or {}
    doi = external.get("DOI")
    arxiv_id = external.get("ArXiv")
    for paper in published:
        if doi and paper.get("doi") and paper["doi"].lower() == doi.lower():
            return True
        if arxiv_id and paper.get("arxiv_id") and paper["arxiv_id"] == arxiv_id:
            return True
        if title_norm and normalize_title(paper.get("title")) == title_norm:
            return True
    return False


def external_url_for(doi, arxiv_id, fallback):
    """The canonical link for a paper, preferring DOI then arXiv (shared by
    build_paper_fields and apply_publication_update so the preference order
    lives in one place). `fallback` is used when neither is available.
    """
    if doi:
        return f"https://doi.org/{doi}"
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return fallback


def build_paper_fields(candidate):
    external = candidate.get("externalIds") or {}
    doi = external.get("DOI")
    arxiv_id = external.get("ArXiv")
    venue = candidate.get("venue") or (PREPRINT_VENUE if arxiv_id else "")
    url = external_url_for(
        doi, arxiv_id, f"https://www.semanticscholar.org/paper/{candidate.get('paperId', '')}"
    )

    authors = [a.get("name") for a in (candidate.get("authors") or []) if a.get("name")]

    return {
        "title": candidate.get("title") or "",
        "authors": authors,
        "venue": venue,
        "year": candidate.get("year"),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "external_url": url,
        "source": "semantic_scholar",
        "selected": False,
    }


def fetch_open_update_branches():
    """Branch names of currently open paper-update/* PRs (ticket 15).

    Lets check_preprint_updates.py skip papers that already have an update
    PR pending, instead of re-proposing the same update every week.
    """
    output = run_git(
        "gh",
        "pr",
        "list",
        "--state",
        "open",
        "--json",
        "headRefName",
        "--limit",
        "100",
        capture=True,
    )
    prs = json.loads(output)
    return {
        pr["headRefName"]
        for pr in prs
        if pr.get("headRefName", "").startswith(PAPER_UPDATE_BRANCH_PREFIX)
    }


def find_publication_update(paper, candidates):
    """Find a Semantic Scholar record reporting `paper` (today an arXiv
    preprint) as now published somewhere else (ticket 15).

    Matches candidates by arxiv_id or normalized title, same keys used for
    already-published detection. Only a candidate with a real, different
    venue counts as a hit: Semantic Scholar sometimes relists the arXiv
    preprint itself as a second record (the ticket 03/09 duplicate-paperId
    pattern), which must not be mistaken for a publication update.
    """
    title_norm = normalize_title(paper.get("title"))
    arxiv_id = paper.get("arxiv_id")
    for candidate in candidates:
        external = candidate.get("externalIds") or {}
        candidate_arxiv_id = external.get("ArXiv")
        title_matches = title_norm and normalize_title(candidate.get("title")) == title_norm
        if not ((arxiv_id and candidate_arxiv_id == arxiv_id) or title_matches):
            continue
        venue = candidate.get("venue") or ""
        if venue and venue != PREPRINT_VENUE:
            return candidate
    return None


def apply_publication_update(fields, candidate):
    """Return a copy of `fields` with venue/doi/external_url updated from
    `candidate` (ticket 15). Title/authors/year/arxiv_id/source/selected
    are left as originally curated.
    """
    external = candidate.get("externalIds") or {}
    doi = external.get("DOI") or fields.get("doi")
    venue = candidate.get("venue") or fields["venue"]
    url = external_url_for(doi, fields.get("arxiv_id"), fields["external_url"])

    updated = dict(fields)
    updated["venue"] = venue
    updated["doi"] = doi
    updated["external_url"] = url
    return updated
