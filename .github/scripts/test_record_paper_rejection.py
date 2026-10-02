import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import record_paper_rejection as rpr


PAPER_PATH = "content/papers/some-paper.md"
PR_TITLE = f"{rpr.CANDIDATE_PR_TITLE_PREFIX}Some Paper"
HEAD_SHA = "deadbeef"
PR_NUMBER = "42"

FRONT_MATTER = (
    '---\n'
    'title: "Some Paper"\n'
    'authors: ["Tom Siegl"]\n'
    'venue: "ECAI 2025"\n'
    'year: 2025\n'
    'doi: null\n'
    'arxiv_id: null\n'
    'external_url: "#"\n'
    'source: "semantic_scholar"\n'
    'selected: false\n'
    '---\n'
)


def pr_view_json(*, files=None, title=PR_TITLE):
    files = files if files is not None else [{"path": PAPER_PATH}]
    return json.dumps({"files": files, "title": title})


class FindCandidatePaperPathTests(unittest.TestCase):
    def test_returns_path_and_title(self):
        with patch.object(rpr, "run", return_value=pr_view_json()):
            path, title = rpr.find_candidate_paper_path(PR_NUMBER)
        self.assertEqual(path, PAPER_PATH)
        self.assertEqual(title, PR_TITLE)

    def test_returns_none_path_when_no_candidate_file(self):
        with patch.object(rpr, "run", return_value=pr_view_json(files=[{"path": "README.md"}])):
            path, title = rpr.find_candidate_paper_path(PR_NUMBER)
        self.assertIsNone(path)
        self.assertEqual(title, PR_TITLE)


class ReadCandidateTitleTests(unittest.TestCase):
    def test_reads_title_from_head_commit_when_fetch_succeeds(self):
        def fake_run(*args, **kwargs):
            if args[:2] == ("git", "fetch"):
                return None
            if args[:2] == ("git", "show"):
                return FRONT_MATTER
            raise AssertionError(f"unexpected run() call: {args}")

        with patch.object(rpr, "run", side_effect=fake_run):
            title = rpr.read_candidate_title(PR_NUMBER, HEAD_SHA, PAPER_PATH, PR_TITLE)

        self.assertEqual(title, "Some Paper")

    def test_falls_back_to_pr_title_when_git_fetch_fails(self):
        # Reproduces ticket 23: the PR head branch/commit is unreachable
        # (e.g. auto-deleted around the same time the pull_request:closed
        # webhook fires), so `git fetch` raises CalledProcessError. Before
        # the fix this propagated straight out of read_candidate_title (and
        # out of main()), crashing the script before anything was recorded.
        def fake_run(*args, **kwargs):
            if args[:2] == ("git", "fetch"):
                raise subprocess.CalledProcessError(1, args)
            raise AssertionError(f"unexpected run() call: {args}")

        with patch.object(rpr, "run", side_effect=fake_run):
            title = rpr.read_candidate_title(PR_NUMBER, HEAD_SHA, PAPER_PATH, PR_TITLE)

        self.assertEqual(title, "Some Paper")

    def test_falls_back_to_pr_title_when_git_show_fails(self):
        def fake_run(*args, **kwargs):
            if args[:2] == ("git", "fetch"):
                return None
            if args[:2] == ("git", "show"):
                raise subprocess.CalledProcessError(1, args)
            raise AssertionError(f"unexpected run() call: {args}")

        with patch.object(rpr, "run", side_effect=fake_run):
            title = rpr.read_candidate_title(PR_NUMBER, HEAD_SHA, PAPER_PATH, PR_TITLE)

        self.assertEqual(title, "Some Paper")

    def test_prints_clear_warning_naming_pr_and_sha_on_fallback(self):
        def fake_run(*args, **kwargs):
            if args[:2] == ("git", "fetch"):
                raise subprocess.CalledProcessError(1, args)
            raise AssertionError(f"unexpected run() call: {args}")

        with patch.object(rpr, "run", side_effect=fake_run):
            with patch("builtins.print") as mock_print:
                rpr.read_candidate_title(PR_NUMBER, HEAD_SHA, PAPER_PATH, PR_TITLE)

        printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn(PR_NUMBER, printed)
        self.assertIn(HEAD_SHA, printed)
        self.assertIn("could not", printed.lower())


class MainTests(unittest.TestCase):
    # record_paper_rejection.main() is a thin wrapper around the shared
    # papers_lib.record_rejection scaffolding (ticket 25): these tests patch
    # record_rejection itself and assert on what it was called with, rather
    # than the retry/push mechanics record_rejection owns (covered by
    # papers_lib's own tests). What's still specific to this script -- and
    # what ticket 23 is actually about -- is that main() resolves the right
    # title before handing it off.
    def _run_main(self, fake_run, *, pr_body="<!-- semantic-scholar-paper-id: p1 -->"):
        env = {
            "PR_NUMBER": PR_NUMBER,
            "PR_HEAD_SHA": HEAD_SHA,
            "PR_BODY": pr_body,
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            rpr, "run", side_effect=fake_run
        ), patch.object(rpr, "configure_bot_identity"), patch.object(
            rpr, "record_rejection"
        ) as mock_record:
            rpr.main()
        return mock_record

    def test_main_records_rejection_using_fallback_title_when_head_commit_unreachable(self):
        # End-to-end: before the fix, this scenario raised CalledProcessError
        # out of main() and the rejection was never recorded.
        def fake_run(*args, **kwargs):
            if args[:3] == ("gh", "pr", "view"):
                return pr_view_json()
            if args[:2] == ("git", "fetch") and args[2] == "origin" and args[3] == HEAD_SHA:
                raise subprocess.CalledProcessError(1, args)
            raise AssertionError(f"unexpected run() call: {args}")

        mock_record = self._run_main(fake_run)

        mock_record.assert_called_once()
        new_entry = mock_record.call_args.kwargs["new_entry"]
        self.assertEqual(new_entry["title"], "Some Paper")
        self.assertEqual(new_entry["paper_id"], "p1")

    def test_main_still_uses_file_content_title_when_fetch_succeeds(self):
        def fake_run(*args, **kwargs):
            if args[:3] == ("gh", "pr", "view"):
                return pr_view_json()
            if args[:2] == ("git", "fetch"):
                return None
            if args[:2] == ("git", "show"):
                return FRONT_MATTER
            raise AssertionError(f"unexpected run() call: {args}")

        mock_record = self._run_main(fake_run)

        new_entry = mock_record.call_args.kwargs["new_entry"]
        self.assertEqual(new_entry["title"], "Some Paper")


if __name__ == "__main__":
    unittest.main()
