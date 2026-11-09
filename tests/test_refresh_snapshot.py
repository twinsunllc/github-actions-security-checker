import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests.helpers  # noqa: F401  (puts scripts/ on sys.path)

import refresh_verified_publishers as refresh_script
from audit_actions import COULD_NOT_VERIFY, UNVERIFIED, VERIFIED, PublisherResult

OLD = {'verified_at': '2026-08-01', 'checked_via': 'docker/build-push-action'}


def stub(results):
    return lambda owner, repo: results[owner]


class RefreshTest(unittest.TestCase):
    def test_live_verified_owner_gets_todays_date(self):
        updated, _ = refresh_script.refresh(
            {}, ['docker/build-push-action'], stub({'docker': PublisherResult(VERIFIED)}), '2026-11-09')
        self.assertEqual(updated, {'docker': {'verified_at': '2026-11-09', 'checked_via': 'docker/build-push-action'}})

    def test_could_not_verify_keeps_the_existing_entry_unchanged(self):
        updated, notes = refresh_script.refresh(
            {'docker': OLD}, ['docker/build-push-action'],
            stub({'docker': PublisherResult(COULD_NOT_VERIFY, 'HTTP 504')}), '2026-11-09')
        self.assertEqual(updated, {'docker': OLD})
        self.assertIn('NOT refreshed', notes[0])

    def test_could_not_verify_does_not_add_a_new_entry(self):
        updated, _ = refresh_script.refresh(
            {}, ['docker/build-push-action'],
            stub({'docker': PublisherResult(COULD_NOT_VERIFY, 'timeout')}), '2026-11-09')
        self.assertEqual(updated, {})

    def test_unverified_owner_is_removed_and_never_recorded(self):
        updated, notes = refresh_script.refresh(
            {'docker': OLD, 'other': OLD}, ['docker/build-push-action', 'newco/action'],
            stub({'docker': PublisherResult(UNVERIFIED, 'no badge'), 'newco': PublisherResult(UNVERIFIED)}),
            '2026-11-09')
        self.assertEqual(updated, {'other': OLD})
        self.assertIn('REMOVED', notes[0])

    def test_a_snapshot_backed_pass_is_not_a_live_verification(self):
        updated, _ = refresh_script.refresh(
            {}, ['docker/build-push-action'],
            stub({'docker': PublisherResult(VERIFIED, source='snapshot')}), '2026-11-09')
        self.assertEqual(updated, {})

    def test_main_rewrites_the_file_with_positive_entries_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'verified-publishers.json'
            path.write_text(json.dumps({'publishers': {
                'docker': OLD,
                'gone': {'verified_at': '2026-08-01', 'checked_via': 'gone/action'},
                'flaky': {'verified_at': '2026-08-01', 'checked_via': 'flaky/action'},
            }}))
            results = {
                'docker': PublisherResult(VERIFIED),
                'gone': PublisherResult(UNVERIFIED, 'no badge'),
                'flaky': PublisherResult(COULD_NOT_VERIFY, 'HTTP 504'),
            }
            with mock.patch.object(refresh_script.ActionAuditor, 'check_publisher_live',
                                   side_effect=lambda owner, repo: results[owner]), \
                    mock.patch('sys.stdout'):
                self.assertEqual(refresh_script.main(['--snapshot', str(path)]), 0)
            publishers = json.loads(path.read_text())['publishers']
        self.assertEqual(set(publishers), {'docker', 'flaky'})
        self.assertEqual(publishers['flaky']['verified_at'], '2026-08-01')
        self.assertNotEqual(publishers['docker']['verified_at'], '2026-08-01')
        for entry in publishers.values():
            self.assertEqual(set(entry), {'verified_at', 'checked_via'})

    def test_no_workflow_runs_the_refresh_script(self):
        workflows = Path(tests.helpers.REPO_ROOT, '.github', 'workflows')
        for wf in list(workflows.glob('*.yml')) + [Path(tests.helpers.REPO_ROOT, 'action.yml')]:
            self.assertNotIn('refresh_verified_publishers', wf.read_text(), wf)


if __name__ == '__main__':
    unittest.main()
