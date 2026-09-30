#!/usr/bin/env python3
"""Offline tests for the release-notes renderers. No network, no Jira token.

Run: python3 .claude/skills/jira-release-notes/scripts/test_build_release_notes.py
"""
from __future__ import annotations

import html.parser
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_release_notes as brn
from jira_api import JiraApiError, escape_jql, resolve_credentials, search_all, whoami

BASE = "https://team-anervea.atlassian.net"
TODAY = date(2026, 9, 30)

# The constructs Outlook's Word engine ignores. If any reaches the Outlook variant, the paste
# silently loses its formatting — the one failure this skill exists to prevent.
OUTLOOK_FORBIDDEN = r"var\(--|color-mix|clamp\(|env\(|position:\s*sticky|@media|googleapis|<style"

ISSUES = [
    {"key": "STH-673", "fields": {
        "summary": "Gate the audio fork <b>on</b> caption demand & GPU",
        "status": {"name": "Deployment"},
        "customfield_10020": [{"name": "STH Sprint 11"}]}},
    {"key": "STH-1420", "fields": {
        "summary": "POST /actions: create an action",
        "status": {"name": "Deployment"},
        "customfield_10020": [{"name": "STH Sprint 11"}]}},
    {"key": "STH-97", "fields": {
        "summary": "Numeric ordering check", "status": None, "customfield_10020": None}},
]


def make_sheet(issues=None):
    issues = ISSUES if issues is None else issues
    return brn.build_sheet(brn.to_rows(issues, BASE), "SETHI", "v0.0.3",
                           "Deployment", brn.sprint_names(issues), TODAY)


class TestRows(unittest.TestCase):
    def test_ordered_by_number_not_string(self):
        keys = [row.key for row in brn.to_rows(ISSUES, BASE)]
        self.assertEqual(keys, ["STH-97", "STH-673", "STH-1420"])

    def test_missing_status_does_not_crash(self):
        rows = {row.key: row for row in brn.to_rows(ISSUES, BASE)}
        self.assertEqual(rows["STH-97"].status, brn.UNKNOWN_STATUS)

    def test_url_points_at_the_browse_page(self):
        self.assertEqual(brn.to_rows(ISSUES, BASE)[0].url, f"{BASE}/browse/STH-97")

    def test_sprints_deduped_and_none_safe(self):
        self.assertEqual(brn.sprint_names(ISSUES), ["STH Sprint 11"])


class TestSheet(unittest.TestCase):
    def test_status_column_is_always_present(self):
        self.assertIn(brn.Kind.STATUS, [c.kind for c in make_sheet().columns])

    def test_band_counts_the_rows(self):
        self.assertEqual(make_sheet().band, "SETHI — 3 tickets")

    def test_both_renderers_read_the_same_column_set(self):
        """The DRY seam: column identity lives in the sheet, not in either renderer."""
        sheet = make_sheet()
        for column in sheet.columns:
            self.assertIn(column.header, brn.render_web(sheet))
            self.assertIn(column.header, brn.render_outlook(sheet))


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.sheet = make_sheet()
        self.docs = {"web": brn.render_web(self.sheet),
                     "outlook": brn.render_outlook(self.sheet)}

    def test_both_parse(self):
        for name, doc in self.docs.items():
            with self.subTest(name):
                html.parser.HTMLParser().feed(doc)

    def test_summary_markup_is_escaped(self):
        for name, doc in self.docs.items():
            with self.subTest(name):
                self.assertIn("&lt;b&gt;", doc)
                self.assertNotIn("<b>on</b>", doc)

    def test_every_ticket_is_linked_once(self):
        for name, doc in self.docs.items():
            with self.subTest(name):
                self.assertEqual(doc.count("/browse/STH-"), len(ISSUES))

    def test_outlook_avoids_every_construct_word_ignores(self):
        hits = set(re.findall(OUTLOOK_FORBIDDEN, self.docs["outlook"]))
        self.assertEqual(hits, set(), f"Outlook variant carries {hits}")

    def test_web_defines_each_theme_token_in_all_three_places(self):
        """Bare :root, the prefers-color-scheme block, and the explicit [data-theme] block."""
        for token in ("--ink", "--page", "--link", "--band", "--sheet"):
            with self.subTest(token):
                self.assertGreaterEqual(self.docs["web"].count(f"{token}:"), 3)

    def test_web_body_sets_an_explicit_background(self):
        self.assertIn("body { margin:0; background:var(--page)", self.docs["web"])


class TestFilenameSafety(unittest.TestCase):
    def test_slug_strips_path_traversal(self):
        self.assertEqual(brn.slug("../../etc/passwd"), "etc-passwd")

    def test_slug_never_returns_empty(self):
        self.assertEqual(brn.slug("///"), "sheet")


class TestJqlSafety(unittest.TestCase):
    def test_quotes_in_a_status_cannot_break_out_of_the_literal(self):
        self.assertEqual(escape_jql('Code "Review"'), 'Code \\"Review\\"')

    def test_backslashes_are_escaped_before_quotes(self):
        self.assertEqual(escape_jql('a\\b'), 'a\\\\b')
        self.assertEqual(escape_jql('a\\"b'), 'a\\\\\\"b')


class TestCensus(unittest.TestCase):
    def test_a_truncated_read_is_refused_not_returned(self):
        class Truncated:
            def post(self, path, body):
                return {"issues": [{"key": "A-1"}], "isLast": False}

        with self.assertRaises(JiraApiError):
            search_all(Truncated(), "project = X", ["summary"])

    def test_pages_to_exhaustion(self):
        class Paged:
            def __init__(self):
                self.calls = 0

            def post(self, path, body):
                self.calls += 1
                if self.calls == 1:
                    return {"issues": [{"key": "A-1"}], "isLast": False, "nextPageToken": "t"}
                return {"issues": [{"key": "A-2"}], "isLast": True}

        self.assertEqual([i["key"] for i in search_all(Paged(), "p = X", ["summary"])],
                         ["A-1", "A-2"])



class TestCredentialResolution(unittest.TestCase):
    """A pair is taken WHOLE from one source — mixing sources names an account nobody holds."""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
        handle.write("JIRA_BASE_URL=https://file.example\n"
                     "JIRA_EMAIL=file@example.com\n"
                     "JIRA_API_TOKEN=file-token\n")
        handle.close()
        self.env_file = Path(handle.name)
        self.addCleanup(self.env_file.unlink)

    @mock.patch.dict(os.environ, {"ATLASSIAN_EMAIL": "atl@example.com",
                                  "ATLASSIAN_API_TOKEN": "atl-token",
                                  "JIRA_BASE_URL": "https://env.example"}, clear=True)
    def test_atlassian_pair_wins_over_the_file(self):
        env = resolve_credentials(self.env_file)
        self.assertEqual(env["JIRA_EMAIL"], "atl@example.com")
        self.assertEqual(env["JIRA_API_TOKEN"], "atl-token")

    @mock.patch.dict(os.environ, {"JIRA_EMAIL": "jira@example.com",
                                  "JIRA_API_TOKEN": "jira-token"}, clear=True)
    def test_jira_pair_is_used_and_borrows_the_files_base_url(self):
        env = resolve_credentials(self.env_file)
        self.assertEqual(env["JIRA_EMAIL"], "jira@example.com")
        self.assertEqual(env["JIRA_BASE_URL"], "https://file.example")

    @mock.patch.dict(os.environ, {"ATLASSIAN_EMAIL": "atl@example.com"}, clear=True)
    def test_an_incomplete_pair_is_ignored_not_half_used(self):
        """The email alone must not combine with the file's token."""
        env = resolve_credentials(self.env_file)
        self.assertEqual(env["JIRA_EMAIL"], "file@example.com")
        self.assertEqual(env["JIRA_API_TOKEN"], "file-token")

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_falls_back_to_the_file_when_the_environment_is_empty(self):
        self.assertEqual(resolve_credentials(self.env_file)["JIRA_EMAIL"], "file@example.com")


class TestIdentityCheck(unittest.TestCase):
    def test_a_run_that_cannot_name_its_account_refuses_to_continue(self):
        class Anonymous:
            def get(self, path, params=None):
                return {}

        with self.assertRaises(JiraApiError):
            whoami(Anonymous())

    def test_the_display_name_is_returned_when_present(self):
        class Named:
            def get(self, path, params=None):
                return {"displayName": "rhidzkhan ahmad"}

        self.assertEqual(whoami(Named()), "rhidzkhan ahmad")


class TestCssContract(unittest.TestCase):
    def test_every_kind_value_has_a_matching_selector_in_the_web_css(self):
        """Renaming a Kind would otherwise silently orphan the stylesheet's selectors."""
        for kind in brn.Kind:
            with self.subTest(kind.value):
                self.assertIn(f".{kind.value} {{", brn.WEB_CSS)

    def test_every_kind_has_an_outlook_style(self):
        for kind in brn.Kind:
            with self.subTest(kind.value):
                self.assertIn(kind, brn.OL_CELL_STYLE)


class TestWording(unittest.TestCase):
    def test_a_single_ticket_is_not_pluralised(self):
        sheet = make_sheet([ISSUES[0]])
        self.assertEqual(sheet.band, "SETHI — 1 ticket")

    def test_the_meta_names_the_status_actually_queried(self):
        self.assertTrue(make_sheet().meta.startswith("Deployment column"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
