import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import papers_lib as lib


SAMPLE_FRONT_MATTER = """---
title: "[Sample paper title one]"
authors: ["Tom Siegl"]
venue: "ECAI 2025"
year: 2025
doi: null
arxiv_id: null
external_url: "#"
source: "manual"
selected: true
---
"""


class ParseRenderFrontMatterTests(unittest.TestCase):
    def test_parses_all_field_types(self):
        fields = lib.parse_front_matter(SAMPLE_FRONT_MATTER)
        self.assertEqual(fields["title"], "[Sample paper title one]")
        self.assertEqual(fields["authors"], ["Tom Siegl"])
        self.assertEqual(fields["year"], 2025)
        self.assertIsNone(fields["doi"])
        self.assertIs(fields["selected"], True)

    def test_round_trips_through_render(self):
        fields = lib.parse_front_matter(SAMPLE_FRONT_MATTER)
        rendered = lib.render_front_matter(fields)
        self.assertEqual(lib.parse_front_matter(rendered), fields)

    def test_round_trip_preserves_fields_outside_field_order(self):
        # A hand-added `build` override (ticket 16, enables a paper's detail
        # page) must survive an automated rewrite of the file, e.g. a
        # check_preprint_updates.py venue update.
        fields = lib.parse_front_matter(SAMPLE_FRONT_MATTER)
        fields["build"] = {"render": "always"}
        rendered = lib.render_front_matter(fields)
        self.assertEqual(lib.parse_front_matter(rendered), fields)

    def test_missing_delimiter_raises(self):
        with self.assertRaises(ValueError):
            lib.parse_front_matter("title: \"no delimiter\"\n")

    def test_missing_required_field_raises_with_specific_message(self):
        # ticket 22: a hand-edited paper file that drops a FIELD_ORDER key
        # (e.g. external_url) must fail loudly and specifically at parse
        # time, naming the missing field, not just "invalid front matter".
        text = """---
title: "[Sample paper title one]"
authors: ["Tom Siegl"]
venue: "ECAI 2025"
year: 2025
doi: null
arxiv_id: null
source: "manual"
selected: true
---
"""
        with self.assertRaises(ValueError) as ctx:
            lib.parse_front_matter(text)
        self.assertIn("external_url", str(ctx.exception))

    def test_missing_multiple_required_fields_names_all(self):
        text = """---
title: "[Sample paper title one]"
authors: ["Tom Siegl"]
---
"""
        with self.assertRaises(ValueError) as ctx:
            lib.parse_front_matter(text)
        message = str(ctx.exception)
        for missing in ("venue", "year", "doi", "arxiv_id", "external_url", "source", "selected"):
            self.assertIn(missing, message)

    def test_write_and_read_paper_file(self):
        fields = lib.build_paper_fields(
            {
                "title": "A New Paper",
                "year": 2026,
                "venue": "ECAI 2026",
                "externalIds": {"DOI": "10.1/abc"},
                "authors": [{"name": "Tom Siegl"}],
                "paperId": "abc123",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a-new-paper.md"
            lib.write_paper_file(path, fields)
            self.assertEqual(lib.read_front_matter(path), fields)
            self.assertEqual(lib.read_body(path), "")

    def test_write_paper_file_preserves_existing_body_by_default(self):
        # ticket 16: an automated field rewrite (e.g. a publication-venue
        # update) must not silently delete a paper's detail-page body.
        fields = lib.build_paper_fields({"title": "A New Paper", "paperId": "p1"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a-new-paper.md"
            lib.write_paper_file(path, fields, body="Hand-written detail-page content.")
            self.assertEqual(lib.read_body(path), "Hand-written detail-page content.")

            updated = dict(fields, venue="ECAI 2026")
            lib.write_paper_file(path, updated)

            self.assertEqual(lib.read_front_matter(path), updated)
            self.assertEqual(lib.read_body(path), "Hand-written detail-page content.")

    def test_write_paper_file_body_override_replaces_existing_body(self):
        fields = lib.build_paper_fields({"title": "A New Paper", "paperId": "p1"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a-new-paper.md"
            lib.write_paper_file(path, fields, body="Old body.")
            lib.write_paper_file(path, fields, body="New body.")
            self.assertEqual(lib.read_body(path), "New body.")

    def test_read_body_missing_file_returns_empty(self):
        self.assertEqual(lib.read_body(Path("/nonexistent/paper.md")), "")

    def test_read_body_no_closing_delimiter_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.md"
            path.write_text("---\ntitle: \"T\"\n", encoding="utf-8")
            self.assertEqual(lib.read_body(path), "")


class SlugTests(unittest.TestCase):
    def test_slugify_basic(self):
        self.assertEqual(lib.slugify("SubROC: AUC-Based Discovery!"), "subroc-auc-based-discovery")

    def test_unique_slug_avoids_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            (papers_dir / "my-paper.md").write_text("---\n---\n")
            self.assertEqual(lib.unique_slug("My Paper", papers_dir), "my-paper-2")

    def test_unique_slug_no_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lib.unique_slug("My Paper", Path(tmp)), "my-paper")

    def test_unique_slug_avoids_extra_used_from_same_run(self):
        # Two candidates with the same title in one run (e.g. duplicate
        # preprint/published-version hits) must not collide, even though
        # neither is on disk yet (each is committed to its own branch).
        with tempfile.TemporaryDirectory() as tmp:
            first = lib.unique_slug("My Paper", Path(tmp), extra_used=set())
            second = lib.unique_slug("My Paper", Path(tmp), extra_used={first})
            self.assertNotEqual(first, second)


class ExternalUrlForTests(unittest.TestCase):
    def test_prefers_doi(self):
        self.assertEqual(lib.external_url_for("10.1/x", "1234.5", "fallback"), "https://doi.org/10.1/x")

    def test_falls_back_to_arxiv(self):
        self.assertEqual(lib.external_url_for(None, "1234.5", "fallback"), "https://arxiv.org/abs/1234.5")

    def test_falls_back_to_given_fallback(self):
        self.assertEqual(lib.external_url_for(None, None, "fallback"), "fallback")


class BuildPaperFieldsTests(unittest.TestCase):
    def test_prefers_doi_link(self):
        fields = lib.build_paper_fields(
            {"title": "T", "externalIds": {"DOI": "10.1/x", "ArXiv": "1234.5"}, "paperId": "p1"}
        )
        self.assertEqual(fields["external_url"], "https://doi.org/10.1/x")
        self.assertEqual(fields["doi"], "10.1/x")
        self.assertEqual(fields["arxiv_id"], "1234.5")

    def test_falls_back_to_arxiv_link(self):
        fields = lib.build_paper_fields(
            {"title": "T", "externalIds": {"ArXiv": "1234.5"}, "paperId": "p1"}
        )
        self.assertEqual(fields["external_url"], "https://arxiv.org/abs/1234.5")
        self.assertEqual(fields["venue"], "arXiv preprint")

    def test_falls_back_to_semantic_scholar_link(self):
        fields = lib.build_paper_fields({"title": "T", "paperId": "p1"})
        self.assertEqual(fields["external_url"], "https://www.semanticscholar.org/paper/p1")

    def test_defaults_are_unselected(self):
        fields = lib.build_paper_fields({"title": "T", "paperId": "p1"})
        self.assertIs(fields["selected"], False)
        self.assertEqual(fields["source"], "semantic_scholar")


class MatchingTests(unittest.TestCase):
    def test_is_excluded_by_paper_id(self):
        exclusions = [{"title": "Something Else", "paper_id": "p1"}]
        candidate = {"title": "New Title", "paperId": "p1"}
        self.assertTrue(lib.is_excluded(candidate, exclusions))

    def test_is_excluded_by_normalized_title(self):
        exclusions = [{"title": "  My Paper!! ", "paper_id": "different"}]
        candidate = {"title": "my paper", "paperId": "p2"}
        self.assertTrue(lib.is_excluded(candidate, exclusions))

    def test_not_excluded(self):
        exclusions = [{"title": "Other", "paper_id": "px"}]
        candidate = {"title": "New Title", "paperId": "p1"}
        self.assertFalse(lib.is_excluded(candidate, exclusions))

    def test_is_already_published_by_doi(self):
        published = [{"title": "Different Title", "doi": "10.1/X", "arxiv_id": None}]
        candidate = {"title": "New Title", "externalIds": {"DOI": "10.1/x"}}
        self.assertTrue(lib.is_already_published(candidate, published))

    def test_is_already_published_by_arxiv_id(self):
        published = [{"title": "Different Title", "doi": None, "arxiv_id": "1234.5"}]
        candidate = {"title": "New Title", "externalIds": {"ArXiv": "1234.5"}}
        self.assertTrue(lib.is_already_published(candidate, published))

    def test_is_already_published_by_title(self):
        published = [{"title": "My Paper", "doi": None, "arxiv_id": None}]
        candidate = {"title": "my paper", "externalIds": {}}
        self.assertTrue(lib.is_already_published(candidate, published))

    def test_not_already_published(self):
        published = [{"title": "Other Paper", "doi": None, "arxiv_id": None}]
        candidate = {"title": "New Title", "externalIds": {}}
        self.assertFalse(lib.is_already_published(candidate, published))

    def test_finance_namesake_false_positive_is_not_a_title_match(self):
        # Regression guard for ticket 03's known Semantic Scholar false positive:
        # a real published paper must not accidentally suppress an unrelated candidate.
        published = [{"title": "SubROC: AUC-Based Discovery", "doi": None, "arxiv_id": None}]
        candidate = {"title": "Better anti-procyclicality?", "externalIds": {}}
        self.assertFalse(lib.is_already_published(candidate, published))


class ExtractPaperIdTests(unittest.TestCase):
    def test_extracts_id_from_marker(self):
        body = "Some text\n\n<!-- semantic-scholar-paper-id: abc123 -->"
        self.assertEqual(lib.extract_paper_id(body), "abc123")

    def test_missing_marker_returns_empty_string(self):
        self.assertEqual(lib.extract_paper_id("no marker here"), "")

    def test_none_body_returns_empty_string(self):
        self.assertEqual(lib.extract_paper_id(None), "")


class ExtractVenueTests(unittest.TestCase):
    def test_extracts_venue_from_marker(self):
        body = "Some text\n\n<!-- semantic-scholar-venue: ECAI 2026 -->"
        self.assertEqual(lib.extract_venue(body), "ECAI 2026")

    def test_missing_marker_returns_empty_string(self):
        self.assertEqual(lib.extract_venue("no marker here"), "")

    def test_none_body_returns_empty_string(self):
        self.assertEqual(lib.extract_venue(None), "")


class DedupeCandidatesTests(unittest.TestCase):
    def test_drops_duplicate_paper_id(self):
        candidates = [
            {"title": "A", "paperId": "p1"},
            {"title": "A (preprint)", "paperId": "p1"},
        ]
        deduped = lib.dedupe_candidates(candidates)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["title"], "A")

    def test_drops_duplicate_normalized_title_with_different_paper_ids(self):
        # Regression guard for ticket 09's preprint/published-DOI split pattern:
        # the same paper can surface under two different paperIds in one run.
        candidates = [
            {"title": "SubROC: AUC-Based Discovery", "paperId": "p1"},
            {"title": "subroc auc based discovery", "paperId": "p2"},
        ]
        deduped = lib.dedupe_candidates(candidates)
        self.assertEqual(len(deduped), 1)

    def test_keeps_distinct_candidates(self):
        candidates = [{"title": "A", "paperId": "p1"}, {"title": "B", "paperId": "p2"}]
        self.assertEqual(lib.dedupe_candidates(candidates), candidates)

    def test_keeps_first_occurrence(self):
        candidates = [{"title": "A", "paperId": "p1"}, {"title": "a", "paperId": "p1"}]
        deduped = lib.dedupe_candidates(candidates)
        self.assertEqual(deduped, [{"title": "A", "paperId": "p1"}])


class FetchOpenCandidatePrsTests(unittest.TestCase):
    def test_filters_to_candidate_branches_and_strips_title_prefix(self):
        prs = [
            {
                "headRefName": "paper-candidate/my-paper",
                "title": f"{lib.CANDIDATE_PR_TITLE_PREFIX}My Paper",
                "body": "<!-- semantic-scholar-paper-id: p1 -->",
            },
            {
                "headRefName": "some-other-branch",
                "title": "Unrelated PR",
                "body": "",
            },
        ]
        with patch.object(lib, "run_git", return_value=json.dumps(prs)):
            result = lib.fetch_open_candidate_prs()
        self.assertEqual(result, [{"title": "My Paper", "paper_id": "p1"}])

    def test_no_open_candidate_prs(self):
        with patch.object(lib, "run_git", return_value="[]"):
            self.assertEqual(lib.fetch_open_candidate_prs(), [])


class LoadPublishedPapersWithPathsTests(unittest.TestCase):
    def test_pairs_path_with_fields_and_skips_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            (papers_dir / "_index.md").write_text("---\ntitle: \"Papers\"\n---\n")
            fields = lib.build_paper_fields({"title": "A Paper", "paperId": "p1"})
            paper_path = papers_dir / "a-paper.md"
            lib.write_paper_file(paper_path, fields)

            result = lib.load_published_papers_with_paths(papers_dir)

        self.assertEqual(result, [(paper_path, fields)])

    def test_skips_file_missing_required_field_without_raising(self):
        # ticket 22: a hand-edited paper file missing a FIELD_ORDER key
        # (e.g. external_url) must not crash the whole batch load — it
        # should be skipped, while other papers in the same directory are
        # still loaded.
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            good_fields = lib.build_paper_fields({"title": "A Good Paper", "paperId": "p1"})
            good_path = papers_dir / "a-good-paper.md"
            lib.write_paper_file(good_path, good_fields)

            bad_path = papers_dir / "a-bad-paper.md"
            bad_path.write_text(
                "---\n"
                'title: "A Bad Paper"\n'
                'authors: ["Tom Siegl"]\n'
                'venue: "ECAI 2025"\n'
                "year: 2025\n"
                "doi: null\n"
                "arxiv_id: null\n"
                'source: "manual"\n'
                "selected: true\n"
                "---\n",
                encoding="utf-8",
            )

            result = lib.load_published_papers_with_paths(papers_dir)

        self.assertEqual(result, [(good_path, good_fields)])

    def test_skipped_file_is_reported_with_path_and_reason(self):
        # ticket 22: the bad file must be attributable in workflow logs
        # instead of vanishing silently.
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            bad_path = papers_dir / "a-bad-paper.md"
            bad_path.write_text(
                "---\n"
                'title: "A Bad Paper"\n'
                'authors: ["Tom Siegl"]\n'
                'venue: "ECAI 2025"\n'
                "year: 2025\n"
                "doi: null\n"
                "arxiv_id: null\n"
                'source: "manual"\n'
                "selected: true\n"
                "---\n",
                encoding="utf-8",
            )

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = lib.load_published_papers_with_paths(papers_dir)

        self.assertEqual(result, [])
        output = buf.getvalue()
        self.assertIn(str(bad_path), output)
        self.assertIn("external_url", output)


class FindPublicationUpdateTests(unittest.TestCase):
    def test_matches_by_arxiv_id_with_new_venue(self):
        paper = {"title": "Old Title", "venue": lib.PREPRINT_VENUE, "arxiv_id": "1234.5"}
        candidates = [
            {
                "title": "New Title",
                "venue": "ECAI 2026",
                "externalIds": {"ArXiv": "1234.5", "DOI": "10.1/pub"},
            }
        ]
        result = lib.find_publication_update(paper, candidates)
        self.assertEqual(result["venue"], "ECAI 2026")

    def test_matches_by_normalized_title_when_no_arxiv_id_match(self):
        paper = {"title": "My Paper", "venue": lib.PREPRINT_VENUE, "arxiv_id": None}
        candidates = [{"title": "my paper", "venue": "ECAI 2026", "externalIds": {}}]
        result = lib.find_publication_update(paper, candidates)
        self.assertIsNotNone(result)

    def test_ignores_duplicate_record_still_a_preprint(self):
        # Regression guard for the ticket 03/09 duplicate-paperId pattern:
        # a second record for the same arXiv paper must not look like a hit.
        paper = {"title": "My Paper", "venue": lib.PREPRINT_VENUE, "arxiv_id": "1234.5"}
        candidates = [
            {"title": "My Paper", "venue": lib.PREPRINT_VENUE, "externalIds": {"ArXiv": "1234.5"}}
        ]
        self.assertIsNone(lib.find_publication_update(paper, candidates))

    def test_no_match_returns_none(self):
        paper = {"title": "My Paper", "venue": lib.PREPRINT_VENUE, "arxiv_id": "1234.5"}
        candidates = [{"title": "Unrelated", "venue": "ECAI 2026", "externalIds": {}}]
        self.assertIsNone(lib.find_publication_update(paper, candidates))

    def test_ignores_arxiv_org_venue_alias(self):
        # Regression guard for PR #1: Semantic Scholar sometimes reports an
        # arXiv paper's venue as "arXiv.org" (with an arXiv DOI like
        # "10.48550/arXiv...."), not this repo's own PREPRINT_VENUE spelling
        # -- that's still a preprint, not a publication update.
        paper = {"title": "My Paper", "venue": lib.PREPRINT_VENUE, "arxiv_id": "1234.5"}
        candidates = [
            {
                "title": "My Paper",
                "venue": "arXiv.org",
                "externalIds": {"ArXiv": "1234.5", "DOI": "10.48550/arXiv.1234.5"},
            }
        ]
        self.assertIsNone(lib.find_publication_update(paper, candidates))


class ApplyPublicationUpdateTests(unittest.TestCase):
    def test_updates_venue_doi_and_url_preserving_other_fields(self):
        fields = lib.build_paper_fields(
            {"title": "T", "year": 2025, "externalIds": {"ArXiv": "1234.5"}, "paperId": "p1"}
        )
        candidate = {"venue": "ECAI 2026", "externalIds": {"ArXiv": "1234.5", "DOI": "10.1/pub"}}

        updated = lib.apply_publication_update(fields, candidate)

        self.assertEqual(updated["venue"], "ECAI 2026")
        self.assertEqual(updated["doi"], "10.1/pub")
        self.assertEqual(updated["external_url"], "https://doi.org/10.1/pub")
        self.assertEqual(updated["title"], fields["title"])
        self.assertEqual(updated["year"], fields["year"])
        self.assertEqual(updated["arxiv_id"], fields["arxiv_id"])

    def test_falls_back_to_arxiv_link_when_candidate_has_no_doi(self):
        fields = lib.build_paper_fields(
            {"title": "T", "externalIds": {"ArXiv": "1234.5"}, "paperId": "p1"}
        )
        candidate = {"venue": "ECAI 2026", "externalIds": {"ArXiv": "1234.5"}}

        updated = lib.apply_publication_update(fields, candidate)

        self.assertIsNone(updated["doi"])
        self.assertEqual(updated["external_url"], "https://arxiv.org/abs/1234.5")


class FetchOpenUpdateBranchesTests(unittest.TestCase):
    def test_filters_to_update_branches(self):
        prs = [
            {"headRefName": "paper-update/my-paper"},
            {"headRefName": "paper-candidate/other-paper"},
            {"headRefName": "some-other-branch"},
        ]
        with patch.object(lib, "run_git", return_value=json.dumps(prs)):
            result = lib.fetch_open_update_branches()
        self.assertEqual(result, {"paper-update/my-paper"})

    def test_no_open_update_prs(self):
        with patch.object(lib, "run_git", return_value="[]"):
            self.assertEqual(lib.fetch_open_update_branches(), set())


class ExclusionsFileTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exclusions.json"
            lib.save_exclusions(
                [{"title": "T", "paper_id": "p1", "rejected_at": "2026-09-27"}],
                path,
                lib.EXCLUSIONS_SCHEMA_NOTE,
            )
            loaded = lib.load_exclusions(path)
            self.assertEqual(loaded, [{"title": "T", "paper_id": "p1", "rejected_at": "2026-09-27"}])
            data = json.loads(path.read_text())
            self.assertEqual(data.get("_schema"), lib.EXCLUSIONS_SCHEMA_NOTE)

    def test_repo_exclusions_file_is_well_formed(self):
        data = json.loads(lib.EXCLUSIONS_PATH.read_text(encoding="utf-8"))
        self.assertIn("_schema", data)
        self.assertIsInstance(data.get("exclusions"), list)
        for entry in data["exclusions"]:
            self.assertIn("title", entry)
            self.assertIn("paper_id", entry)
            self.assertIn("rejected_at", entry)


class UpdateExclusionsFileTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        # Same generalized load_exclusions/save_exclusions pair as
        # ExclusionsFileTests, just pointed at the update-exclusion store's
        # own path/schema note (ticket 25).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update-exclusions.json"
            lib.save_exclusions(
                [
                    {
                        "slug": "a-paper",
                        "venue": "ECAI 2026",
                        "paper_id": "p1",
                        "rejected_at": "2026-09-27",
                    }
                ],
                path,
                lib.UPDATE_EXCLUSIONS_SCHEMA_NOTE,
            )
            loaded = lib.load_exclusions(path)
            self.assertEqual(
                loaded,
                [
                    {
                        "slug": "a-paper",
                        "venue": "ECAI 2026",
                        "paper_id": "p1",
                        "rejected_at": "2026-09-27",
                    }
                ],
            )
            data = json.loads(path.read_text())
            self.assertEqual(data.get("_schema"), lib.UPDATE_EXCLUSIONS_SCHEMA_NOTE)

    def test_repo_update_exclusions_file_is_well_formed(self):
        data = json.loads(lib.UPDATE_EXCLUSIONS_PATH.read_text(encoding="utf-8"))
        self.assertIn("_schema", data)
        self.assertIsInstance(data.get("exclusions"), list)
        for entry in data["exclusions"]:
            self.assertIn("slug", entry)
            self.assertIn("venue", entry)
            self.assertIn("paper_id", entry)
            self.assertIn("rejected_at", entry)

    def test_is_update_excluded_matches_by_slug_and_venue(self):
        exclusions = [
            {"slug": "a-paper", "venue": "ECAI 2026", "paper_id": "p1", "rejected_at": "2026-09-27"}
        ]
        self.assertTrue(lib.is_update_excluded("a-paper", "ECAI 2026", exclusions))
        self.assertFalse(lib.is_update_excluded("other-paper", "ECAI 2026", exclusions))

    def test_is_update_excluded_allows_a_different_later_venue(self):
        # A rejected venue match must not block a later, different venue for
        # the same paper from being proposed.
        exclusions = [
            {"slug": "a-paper", "venue": "arXiv.org", "paper_id": "p1", "rejected_at": "2026-09-27"}
        ]
        self.assertFalse(lib.is_update_excluded("a-paper", "ECAI 2026", exclusions))


class RecordRejectionTests(unittest.TestCase):
    """Shared retry/commit/push scaffolding (ticket 25), extracted from
    record_paper_rejection.py / record_paper_update_rejection.py. Both
    scripts resolve their own new_entry/already_excluded/commit_message
    before handing them to this one function; checkout_fresh_main and
    run_git (the only git/gh-touching calls) are mocked throughout.
    """

    def _entry(self):
        return {"title": "T", "paper_id": "p1", "rejected_at": "2026-10-02"}

    def test_appends_entry_saves_and_pushes_on_first_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exclusions.json"
            lib.save_exclusions([], path, lib.EXCLUSIONS_SCHEMA_NOTE)
            calls = []
            with patch.object(lib, "checkout_fresh_main") as mock_checkout, patch.object(
                lib, "run_git", side_effect=lambda *args, **kwargs: calls.append(args)
            ):
                lib.record_rejection(
                    path=path,
                    schema_note=lib.EXCLUSIONS_SCHEMA_NOTE,
                    new_entry=self._entry(),
                    already_excluded=lambda exclusions: False,
                    commit_message="Record rejection: T",
                )
            mock_checkout.assert_called_once()
            self.assertEqual(lib.load_exclusions(path), [self._entry()])
            self.assertEqual(
                calls,
                [
                    ("git", "add", str(path)),
                    ("git", "commit", "-m", "Record rejection: T"),
                    ("git", "push", "origin", "main"),
                ],
            )

    def test_already_excluded_short_circuits_without_commit_or_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exclusions.json"
            existing = [{"title": "Other", "paper_id": "p0", "rejected_at": "2026-09-01"}]
            lib.save_exclusions(existing, path, lib.EXCLUSIONS_SCHEMA_NOTE)
            with patch.object(lib, "checkout_fresh_main"), patch.object(lib, "run_git") as mock_run:
                lib.record_rejection(
                    path=path,
                    schema_note=lib.EXCLUSIONS_SCHEMA_NOTE,
                    new_entry=self._entry(),
                    already_excluded=lambda exclusions: True,
                    commit_message="Record rejection: T",
                )
            mock_run.assert_not_called()
            # The already-recorded guard must not append a duplicate entry.
            self.assertEqual(lib.load_exclusions(path), existing)

    def test_retries_against_fresh_main_on_non_fast_forward_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exclusions.json"
            lib.save_exclusions([], path, lib.EXCLUSIONS_SCHEMA_NOTE)
            original_content = path.read_text()
            push_attempts = {"n": 0}

            def fake_checkout():
                # Mirrors checkout_fresh_main's real effect: resetting main
                # to origin/main discards the local commit a failed-push
                # attempt made, so a retry's load_exclusions sees the file
                # as it was before that attempt, not as it appended it.
                path.write_text(original_content)

            def fake_run(*args, **kwargs):
                if args[:2] == ("git", "push"):
                    push_attempts["n"] += 1
                    if push_attempts["n"] < 2:
                        raise subprocess.CalledProcessError(1, args)
                return None

            with patch.object(
                lib, "checkout_fresh_main", side_effect=fake_checkout
            ) as mock_checkout, patch.object(lib, "run_git", side_effect=fake_run):
                lib.record_rejection(
                    path=path,
                    schema_note=lib.EXCLUSIONS_SCHEMA_NOTE,
                    new_entry=self._entry(),
                    already_excluded=lambda exclusions: False,
                    commit_message="Record rejection: T",
                )
            self.assertEqual(push_attempts["n"], 2)
            self.assertEqual(mock_checkout.call_count, 2)
            self.assertEqual(lib.load_exclusions(path), [self._entry()])

    def test_raises_after_max_push_attempts_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exclusions.json"
            lib.save_exclusions([], path, lib.EXCLUSIONS_SCHEMA_NOTE)

            def always_fail_push(*args, **kwargs):
                if args[:2] == ("git", "push"):
                    raise subprocess.CalledProcessError(1, args)
                return None

            with patch.object(lib, "checkout_fresh_main") as mock_checkout, patch.object(
                lib, "run_git", side_effect=always_fail_push
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    lib.record_rejection(
                        path=path,
                        schema_note=lib.EXCLUSIONS_SCHEMA_NOTE,
                        new_entry=self._entry(),
                        already_excluded=lambda exclusions: False,
                        commit_message="Record rejection: T",
                    )
            self.assertEqual(mock_checkout.call_count, lib.MAX_PUSH_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
