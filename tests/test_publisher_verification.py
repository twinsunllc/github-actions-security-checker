import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from tests.helpers import REPO_ROOT, Router, marketplace_page, repo_page, response, verified_docker_routes

import requests
import audit_actions
from audit_actions import (
    COULD_NOT_VERIFY, DEFAULT_RETRY_DELAYS, SNAPSHOT_ENTRY_KEYS, UNVERIFIED, VERIFIED,
    ActionAuditor, load_snapshot,
)

REPO = 'https://github.com/docker/setup-buildx-action'
LISTING = 'https://github.com/marketplace/actions/docker-setup-buildx'
TODAY = date(2026, 11, 9)


class AuditorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sleeps = []
        # No snapshot unless a test writes one.
        self.snapshot_path = Path(self.tmp.name) / 'verified-publishers.json'

    def auditor(self, delays=(1, 2, 3)):
        return ActionAuditor('token', retry_delays=delays, sleep=self.sleeps.append,
                             now=lambda: TODAY, snapshot_path=str(self.snapshot_path))

    def write_snapshot(self, publishers):
        self.snapshot_path.write_text(json.dumps({'publishers': publishers}))

    def route(self, routes):
        router = Router(routes)
        patcher = mock.patch.object(audit_actions.requests, 'get', side_effect=router)
        patcher.start()
        self.addCleanup(patcher.stop)
        return router


class RetryTest(AuditorCase):
    def test_repo_page_504_on_every_attempt_is_could_not_verify(self):
        router = self.route({REPO: [response(504)]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual(result.status, COULD_NOT_VERIFY)
        self.assertEqual(result.detail, 'HTTP 504')
        self.assertEqual(result.url, REPO)
        self.assertEqual(router.count(REPO), 4)
        self.assertEqual(self.sleeps, [1, 2, 3])

    def test_marketplace_page_504_on_every_attempt_is_could_not_verify(self):
        router = self.route({
            REPO: [response(200, repo_page('docker-setup-buildx'))],
            LISTING: [response(504)],
        })
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual((result.status, result.detail, result.url), (COULD_NOT_VERIFY, 'HTTP 504', LISTING))
        self.assertEqual(router.count(LISTING), 4)
        self.assertEqual(self.sleeps, [1, 2, 3])

    def test_timeout_is_could_not_verify_and_named(self):
        self.route({REPO: [requests.Timeout('read timed out')]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual((result.status, result.detail), (COULD_NOT_VERIFY, 'timeout'))
        self.assertEqual(self.sleeps, [1, 2, 3])

    def test_connection_error_is_could_not_verify_and_named(self):
        self.route({REPO: [requests.ConnectionError('refused')]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual((result.status, result.detail), (COULD_NOT_VERIFY, 'connection error: ConnectionError'))
        self.assertEqual(self.sleeps, [1, 2, 3])

    def test_429_is_retried(self):
        self.route({REPO: [response(429)]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual((result.status, result.detail), (COULD_NOT_VERIFY, 'HTTP 429'))
        self.assertEqual(self.sleeps, [1, 2, 3])

    def test_504_then_200_recovers_after_one_sleep(self):
        self.route({
            REPO: [response(504), response(200, repo_page('docker-setup-buildx'))],
            LISTING: [response(200, marketplace_page('docker'))],
        })
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual(result.status, VERIFIED)
        self.assertEqual(self.sleeps, [1])

    def test_other_4xx_is_could_not_verify_without_retry(self):
        router = self.route({REPO: [response(403)]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual((result.status, result.detail), (COULD_NOT_VERIFY, 'HTTP 403'))
        self.assertEqual(router.count(REPO), 1)
        self.assertEqual(self.sleeps, [])

    def test_404_repo_page_is_unverified_without_retry(self):
        router = self.route({'https://github.com/some-vendor/action': [response(404)]})
        result = self.auditor().check_verified_publisher('some-vendor', 'action')
        self.assertEqual(result.status, UNVERIFIED)
        self.assertEqual(router.count('https://github.com/some-vendor/action'), 1)

    def test_repo_page_without_marketplace_link_is_unverified(self):
        self.route({'https://github.com/some-vendor/action': [response(200, '<html>no listing</html>')]})
        result = self.auditor().check_verified_publisher('some-vendor', 'action')
        self.assertEqual(result.status, UNVERIFIED)

    def test_default_schedule_is_at_least_two_minutes_and_used_by_default(self):
        self.assertGreaterEqual(sum(DEFAULT_RETRY_DELAYS), 120)
        self.assertEqual(ActionAuditor('token').retry_delays, tuple(DEFAULT_RETRY_DELAYS))

    def test_default_schedule_is_handed_to_the_injected_sleep(self):
        self.route({REPO: [response(504)]})
        auditor = ActionAuditor('token', sleep=self.sleeps.append, snapshot_path=str(self.snapshot_path))
        auditor.check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual(self.sleeps, list(DEFAULT_RETRY_DELAYS))

    def test_first_party_owner_is_verified_without_fetching(self):
        router = self.route({})
        self.assertEqual(self.auditor().check_verified_publisher('actions', 'checkout').status, VERIFIED)
        self.assertEqual(router.calls, [])


class CacheTest(AuditorCase):
    def test_a_failed_fetch_is_not_cached(self):
        routes = {REPO: [response(504)]}
        routes.update(verified_docker_routes())
        router = self.route(routes)
        auditor = self.auditor()
        self.assertEqual(auditor.check_verified_publisher('docker', 'setup-buildx-action').status, COULD_NOT_VERIFY)
        self.assertNotIn('docker', auditor.publisher_cache)
        self.assertEqual(auditor.check_verified_publisher('docker', 'build-push-action').status, VERIFIED)
        self.assertEqual(router.count('https://github.com/docker/build-push-action'), 1)

    def test_a_failed_fetch_is_refetched_for_the_same_action(self):
        router = self.route({REPO: [response(504)]})
        auditor = self.auditor()
        auditor.check_verified_publisher('docker', 'setup-buildx-action')
        auditor.check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual(router.count(REPO), 8)

    def test_a_verified_verdict_is_cached_per_owner(self):
        router = self.route(verified_docker_routes())
        auditor = self.auditor()
        auditor.check_verified_publisher('docker', 'build-push-action')
        result = auditor.check_verified_publisher('docker', 'some-other-action')
        self.assertEqual(result.status, VERIFIED)
        self.assertEqual(len(router.calls), 2)

    def test_an_unverified_verdict_is_cached_per_owner(self):
        router = self.route({'https://github.com/some-vendor/action': [response(404)]})
        auditor = self.auditor()
        auditor.check_verified_publisher('some-vendor', 'action')
        self.assertEqual(auditor.check_verified_publisher('some-vendor', 'other').status, UNVERIFIED)
        self.assertEqual(len(router.calls), 1)


class SnapshotTest(AuditorCase):
    def snapshot_at(self, days_ago):
        self.write_snapshot({'docker': {'verified_at': (TODAY - timedelta(days=days_ago)).isoformat()}})

    def test_recent_entry_passes_when_the_fetch_fails(self):
        self.snapshot_at(10)
        self.route({REPO: [response(504)]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual(result.status, VERIFIED)
        self.assertEqual(result.source, 'snapshot')
        self.assertEqual(result.detail,
                         'verified (from the snapshot of 2026-10-30; live check could not run: HTTP 504)')

    def test_entry_exactly_90_days_old_still_passes(self):
        self.snapshot_at(90)
        self.route({REPO: [response(504)]})
        self.assertEqual(self.auditor().check_verified_publisher('docker', 'setup-buildx-action').status, VERIFIED)

    def test_entry_older_than_90_days_stays_could_not_verify(self):
        self.snapshot_at(91)
        self.route({REPO: [response(504)]})
        result = self.auditor().check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual((result.status, result.detail), (COULD_NOT_VERIFY, 'HTTP 504'))

    def test_entry_dated_in_the_future_stays_could_not_verify(self):
        self.snapshot_at(-1)
        self.route({REPO: [response(504)]})
        self.assertEqual(self.auditor().check_verified_publisher('docker', 'setup-buildx-action').status,
                         COULD_NOT_VERIFY)

    def test_absent_owner_stays_could_not_verify(self):
        self.write_snapshot({'hashicorp': {'verified_at': TODAY.isoformat()}})
        self.route({REPO: [response(504)]})
        self.assertEqual(self.auditor().check_verified_publisher('docker', 'setup-buildx-action').status,
                         COULD_NOT_VERIFY)

    def test_live_no_badge_wins_over_the_snapshot(self):
        self.snapshot_at(1)
        self.route({
            REPO: [response(200, repo_page('docker-setup-buildx'))],
            LISTING: [response(200, marketplace_page('docker', verified=False))],
        })
        auditor = self.auditor()
        self.assertEqual(auditor.check_verified_publisher('docker', 'setup-buildx-action').status, UNVERIFIED)
        self.assertIsNone(auditor._snapshot, 'the snapshot must not be read when the live check answered')

    def test_live_404_wins_over_the_snapshot(self):
        self.write_snapshot({'some-vendor': {'verified_at': TODAY.isoformat()}})
        self.route({'https://github.com/some-vendor/action': [response(404)]})
        self.assertEqual(self.auditor().check_verified_publisher('some-vendor', 'action').status, UNVERIFIED)

    def test_snapshot_pass_is_not_cached(self):
        self.snapshot_at(1)
        router = self.route({REPO: [response(504)]})
        auditor = self.auditor()
        auditor.check_verified_publisher('docker', 'setup-buildx-action')
        self.assertNotIn('docker', auditor.publisher_cache)
        auditor.check_verified_publisher('docker', 'setup-buildx-action')
        self.assertEqual(router.count(REPO), 8)

    def test_missing_snapshot_file_degrades_to_could_not_verify(self):
        self.route({REPO: [response(504)]})
        self.assertFalse(self.snapshot_path.exists())
        self.assertEqual(self.auditor().check_verified_publisher('docker', 'setup-buildx-action').status,
                         COULD_NOT_VERIFY)

    def test_malformed_snapshot_file_degrades_to_could_not_verify(self):
        for content in ('{not json', '[]', '{"publishers": []}', '{}'):
            with self.subTest(content=content):
                self.snapshot_path.write_text(content)
                self.route({REPO: [response(504)]})
                self.assertEqual(self.auditor().check_verified_publisher('docker', 'setup-buildx-action').status,
                                 COULD_NOT_VERIFY)

    def test_malformed_or_negative_entries_are_ignored(self):
        self.write_snapshot({
            'docker': {'verified_at': TODAY.isoformat(), 'verified': False},
            'neg': {'verified': False},
            'baddate': {'verified_at': 'last tuesday'},
            'notadict': '2026-11-09',
            'good': {'verified_at': TODAY.isoformat()},
        })
        self.assertEqual(load_snapshot(self.snapshot_path), {'good': TODAY})

    def test_checked_in_snapshot_is_positive_entries_only(self):
        path = REPO_ROOT / 'verified-publishers.json'
        raw = json.loads(path.read_text())['publishers']
        self.assertTrue(raw, 'the checked-in snapshot should not be empty')
        for owner, entry in raw.items():
            with self.subTest(owner=owner):
                self.assertLessEqual(set(entry), SNAPSHOT_ENTRY_KEYS)
                self.assertIn('verified_at', entry)
                date.fromisoformat(entry['verified_at'])
        self.assertEqual(set(load_snapshot(path)), set(raw))

    def test_default_snapshot_path_is_the_checked_in_file(self):
        self.assertEqual(ActionAuditor('token').snapshot_path, REPO_ROOT / 'verified-publishers.json')


if __name__ == '__main__':
    unittest.main()
