import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from tests.helpers import Router, marketplace_page, repo_page, response, verified_docker_routes

import audit_actions
from audit_actions import COULD_NOT_VERIFY, UNVERIFIED, VERIFIED, ActionAuditor

SHA = 'a' * 40
BUILDX = 'https://github.com/docker/setup-buildx-action'


class AuditReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.snapshot_path = Path(self.tmp.name) / 'verified-publishers.json'

    def audit(self, actions, routes, allowlist=''):
        router = Router(routes)
        auditor = ActionAuditor('token', allowlist=allowlist, retry_delays=(1, 2), sleep=lambda s: None,
                                now=lambda: date(2026, 11, 9), snapshot_path=str(self.snapshot_path))
        auditor.action_references = [
            {'file': 'wf.yml', 'line': n, 'action': a, 'raw_line': f'uses: {a}'}
            for n, a in enumerate(actions, 1)
        ]
        out = io.StringIO()
        with mock.patch.object(audit_actions.requests, 'get', side_effect=router), contextlib.redirect_stdout(out):
            report, exit_code = auditor.audit_actions()
            text = auditor.generate_report(report, exit_code)
        return report, exit_code, text, router, out.getvalue()

    def test_504_on_every_retry_reports_could_not_verify_not_a_finding(self):
        report, exit_code, text, _, stdout = self.audit(
            [f'docker/setup-buildx-action@{SHA}'], {BUILDX: [response(504)]})
        entry = report[0]
        self.assertIn('could not verify (HTTP 504)', entry['issues'])
        self.assertNotIn('Not from verified publisher', entry['issues'])
        self.assertEqual(entry['verification'], COULD_NOT_VERIFY)
        self.assertEqual(exit_code, 1)
        self.assertIn('**Could not verify:** 1', text)
        self.assertNotIn('Not from verified publisher', text)
        self.assertIn('- **Verified Publisher:** ⚠️ could not verify (HTTP 504)', text)
        self.assertIn('## ⚠️ Could not verify every publisher (GitHub fetch failed)', text)
        self.assertNotIn('Security issues found', text)
        self.assertIn('::error title=Publisher check could not run::docker/setup-buildx-action', stdout)
        self.assertIn('not a security finding', stdout)

    def test_could_not_verify_beside_a_real_finding_still_says_security_issues(self):
        _, exit_code, text, _, _ = self.audit(
            ['docker/setup-buildx-action@v3'], {BUILDX: [response(504)]})
        self.assertEqual(exit_code, 1)
        self.assertIn('## ❌ Security issues found!', text)
        self.assertIn('Not pinned to commit hash', text)

    def test_verified_docker_actions_pass_and_are_cached(self):
        routes = verified_docker_routes()
        report, exit_code, text, router, _ = self.audit(
            [f'docker/build-push-action@{SHA}', f'docker/login-action@{SHA}'], routes)
        self.assertEqual([e['status'] for e in report], ['✅ PASS', '✅ PASS'])
        self.assertEqual([e['verification'] for e in report], [VERIFIED, VERIFIED])
        self.assertEqual(exit_code, 0)
        self.assertIn('**Verified publishers:** 2/2', text)
        self.assertIn('**Could not verify:** 0', text)
        self.assertEqual(len(router.calls), 2, 'the second docker action should use the cached verdict')

    def test_unverified_owner_still_fails_as_a_finding(self):
        report, exit_code, text, _, stdout = self.audit(
            [f'some-vendor/action@{SHA}'], {'https://github.com/some-vendor/action': [response(404)]})
        self.assertEqual(report[0]['issues'], ['Not from verified publisher'])
        self.assertEqual(report[0]['verification'], UNVERIFIED)
        self.assertEqual(exit_code, 1)
        self.assertIn('## ❌ Security issues found!', text)
        self.assertIn('**Could not verify:** 0', text)
        self.assertNotIn('::error', stdout)

    def test_unbadged_marketplace_listing_still_fails_as_a_finding(self):
        routes = {
            'https://github.com/some-vendor/action': [response(200, repo_page('some-action'))],
            'https://github.com/marketplace/actions/some-action': [response(200, marketplace_page('some-vendor', False))],
        }
        report, exit_code, _, _, _ = self.audit([f'some-vendor/action@{SHA}'], routes)
        self.assertEqual(report[0]['issues'], ['Not from verified publisher'])
        self.assertEqual(exit_code, 1)

    def test_second_action_of_a_failed_owner_is_fetched_again(self):
        routes = {BUILDX: [response(504)]}
        routes.update(verified_docker_routes())
        report, exit_code, text, router, _ = self.audit(
            [f'docker/setup-buildx-action@{SHA}', f'docker/build-push-action@{SHA}'], routes)
        self.assertEqual(router.count('https://github.com/docker/build-push-action'), 1)
        self.assertEqual([e['verification'] for e in report], [COULD_NOT_VERIFY, VERIFIED])
        self.assertIn('**Could not verify:** 1', text)
        self.assertEqual(exit_code, 1)

    def test_snapshot_pass_renders_the_snapshot_and_exits_0(self):
        self.snapshot_path.write_text(json.dumps({'publishers': {'docker': {'verified_at': '2026-11-01'}}}))
        report, exit_code, text, _, stdout = self.audit(
            [f'docker/setup-buildx-action@{SHA}'], {BUILDX: [response(504)]})
        message = 'verified (from the snapshot of 2026-11-01; live check could not run: HTTP 504)'
        self.assertEqual(report[0]['status'], '✅ PASS')
        self.assertEqual(report[0]['issues'], [message])
        self.assertEqual(exit_code, 0)
        self.assertIn('- **Verified Publisher:** ✅ (snapshot of 2026-11-01)', text)
        self.assertIn('**Could not verify:** 0', text)
        self.assertNotIn('::error', stdout)

    def test_allowlisted_action_keeps_its_bypass_message(self):
        report, exit_code, _, router, _ = self.audit([f'docker/setup-buildx-action@{SHA}'], {}, allowlist='docker')
        self.assertEqual(report[0]['issues'], ['Trusted - bypassing publisher verification'])
        self.assertEqual(report[0]['verification'], 'allowlisted')
        self.assertEqual(exit_code, 0)
        self.assertEqual(router.calls, [])


if __name__ == '__main__':
    unittest.main()
