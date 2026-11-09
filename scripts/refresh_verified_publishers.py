#!/usr/bin/env python3
"""Refresh verified-publishers.json from the live Marketplace check.

Run by a person at release time (see README, "Releasing"); no workflow runs
it. Each argument is an action, owner/repo, whose repository page links to
its Marketplace listing. With no arguments, every entry already in the
snapshot is re-checked through its recorded checked_via action.

For each owner:
- verified by the live check: the entry is written with today's date;
- the live check could not run: an existing entry is left untouched;
- unverified by the live check: the entry is removed.

The file only ever holds positive entries. Nothing here writes "unverified".
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit_actions import (  # noqa: E402
    COULD_NOT_VERIFY,
    DEFAULT_SNAPSHOT_PATH,
    UNVERIFIED,
    VERIFIED,
    ActionAuditor,
    PublisherResult,
    read_snapshot_file,
)

DESCRIPTION = ('Positive entries only: owners the live Marketplace check verified at release. '
               'Read by audit_actions.py only when the live check could not run. '
               'Regenerate with scripts/refresh_verified_publishers.py.')


def refresh(publishers: Dict[str, Dict], actions: List[str],
            check: Callable[[str, str], PublisherResult], today: str) -> Tuple[Dict[str, Dict], List[str]]:
    """Return the new publishers map and one note per action checked."""
    updated = {owner: dict(entry) for owner, entry in publishers.items() if isinstance(entry, dict)}
    notes = []
    for action in actions:
        owner, _, repo = action.partition('/')
        if not owner or not repo:
            notes.append(f'{action}: skipped, expected owner/repo')
            continue
        result = check(owner, repo)
        if result.status == VERIFIED and result.source == 'live':
            updated[owner] = {'verified_at': today, 'checked_via': action}
            notes.append(f'{owner}: verified via {action} ({result.url})')
        elif result.status == UNVERIFIED:
            if owner in updated:
                del updated[owner]
                notes.append(f'{owner}: REMOVED, the live check says unverified ({result.detail})')
            else:
                notes.append(f'{owner}: not added, the live check says unverified ({result.detail})')
        else:
            kept = 'existing entry kept' if owner in updated else 'not added'
            reason = result.detail if result.status == COULD_NOT_VERIFY else f'{result.status} from {result.source}'
            notes.append(f'{owner}: NOT refreshed, live check could not run ({reason}); {kept}')
    return updated, notes


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('actions', nargs='*', metavar='owner/repo',
                        help='actions to check (default: every entry\'s checked_via)')
    parser.add_argument('--snapshot', default=str(DEFAULT_SNAPSHOT_PATH), help='snapshot file to rewrite')
    args = parser.parse_args(argv)

    # Rewrite only an existing .json file: a mistyped --snapshot must not create
    # a new file or overwrite a non-JSON one.
    path = Path(args.snapshot).resolve()
    if path.suffix != '.json' or not path.is_file():
        print(f'Refusing --snapshot {args.snapshot}: it must name an existing .json snapshot file')
        return 2
    publishers = read_snapshot_file(path)
    actions = args.actions or [e['checked_via'] for e in publishers.values()
                               if isinstance(e, dict) and e.get('checked_via')]
    if not actions:
        print('Nothing to check: pass owner/repo arguments.')
        return 1

    auditor = ActionAuditor('')
    today = datetime.now(timezone.utc).date().isoformat()
    updated, notes = refresh(publishers, actions, auditor.check_publisher_live, today)
    for note in notes:
        print(note)

    with open(path, 'w') as f:
        json.dump({'description': DESCRIPTION, 'publishers': dict(sorted(updated.items()))},
                  f, indent=2, sort_keys=True)
        f.write('\n')
    print(f'Wrote {len(updated)} entr{"y" if len(updated) == 1 else "ies"} to {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
