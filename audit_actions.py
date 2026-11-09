#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import yaml
import requests
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple, Set

# Outcomes of the verified-publisher check. "could not verify" means the
# GitHub page could not be fetched; it is not a security finding.
VERIFIED = 'verified'
UNVERIFIED = 'unverified'
COULD_NOT_VERIFY = 'could_not_verify'

# Seconds to wait between attempts at one URL when GitHub answers 5xx/429,
# times out or refuses the connection: 135 s in total, six attempts.
DEFAULT_RETRY_DELAYS = (5, 10, 20, 40, 60)

# A snapshot entry older than this no longer stands in for a live check.
SNAPSHOT_MAX_AGE_DAYS = 90
DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parent / 'verified-publishers.json'
SNAPSHOT_ENTRY_KEYS = {'verified_at', 'checked_via'}


class PublisherResult(NamedTuple):
    status: str            # VERIFIED, UNVERIFIED or COULD_NOT_VERIFY
    detail: str = ''       # why; for COULD_NOT_VERIFY the HTTP status or error
    source: str = 'live'   # 'live', 'snapshot' or 'first_party'
    url: str = ''          # the page that decided it, or failed to load
    snapshot_date: Optional[date] = None


def read_snapshot_file(path: Path) -> Dict:
    """Return the snapshot file's raw publishers map, or {} with a warning
    when the path is not a .json file, the file is missing, or it is not
    {"publishers": {...}} JSON."""
    resolved = Path(path).resolve()
    if resolved.suffix != '.json':
        print(f"Warning: refusing verified publisher snapshot {path}: not a .json file; no snapshot fallback")
        return {}
    try:
        with open(resolved, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Warning: verified publisher snapshot not found at {path}; no snapshot fallback")
        return {}
    except (OSError, ValueError) as e:
        print(f"Warning: could not read verified publisher snapshot {path}: {e}; no snapshot fallback")
        return {}
    publishers = data.get('publishers') if isinstance(data, dict) else None
    if not isinstance(publishers, dict):
        print(f"Warning: verified publisher snapshot {path} has no 'publishers' object; no snapshot fallback")
        return {}
    return publishers


def load_snapshot(path: Path) -> Dict[str, date]:
    """Map owner -> verified_at for every well-formed, positive entry.

    An entry is kept only when it is an object whose keys are
    SNAPSHOT_ENTRY_KEYS (verified_at required) and whose verified_at is an
    ISO date. Anything else is skipped with a warning.
    """
    snapshot = {}
    for owner, entry in read_snapshot_file(path).items():
        if (not isinstance(entry, dict) or 'verified_at' not in entry
                or not set(entry) <= SNAPSHOT_ENTRY_KEYS):
            print(f"Warning: ignoring malformed snapshot entry for {owner!r}")
            continue
        try:
            snapshot[owner] = date.fromisoformat(entry['verified_at'])
        except (TypeError, ValueError):
            print(f"Warning: ignoring snapshot entry for {owner!r}: bad verified_at {entry['verified_at']!r}")
    return snapshot


class ActionAuditor:
    def __init__(self, github_token: str, whitelist: str = '', blacklist: str = '', allowlist: str = '',
                 retry_delays: Optional[Sequence[float]] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Optional[Callable[[], date]] = None,
                 snapshot_path: Optional[str] = None):
        self.github_token = github_token
        self.headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Action-Security-Auditor/1.0'
        }
        self.verified_publishers = set()
        # Maps owner -> PublisherResult. Only real verdicts (VERIFIED or
        # UNVERIFIED from a page that loaded) are stored; a fetch failure
        # never is, so the next action of that owner is fetched again.
        self.publisher_cache = {}
        self.action_references = []
        self.issues = []
        self.whitelist = self._parse_list(whitelist)
        self.blacklist = self._parse_list(blacklist)
        self.allowlist = self._parse_list(allowlist)
        self.retry_delays = tuple(DEFAULT_RETRY_DELAYS if retry_delays is None else retry_delays)
        self.sleep = sleep
        self.now = now or (lambda: datetime.now(timezone.utc).date())
        self.snapshot_path = Path(snapshot_path) if snapshot_path is not None else DEFAULT_SNAPSHOT_PATH
        self._snapshot = None  # owner -> verified_at date, loaded on first need
        
    def _parse_list(self, list_input: str) -> List[str]:
        """Parse list input which can be newline-separated or comma-separated string."""
        if not list_input or not list_input.strip():
            return []
        
        list_input = list_input.strip()
        
        # Handle newline-separated format (multiline string)
        if '\n' in list_input:
            return [line.strip() for line in list_input.split('\n') if line.strip()]
        
        # Handle comma-separated format
        return [item.strip() for item in list_input.split(',') if item.strip()]
    
    def _is_action_allowed(self, action_path: str) -> bool:
        """Check if an action is allowed based on whitelist/blacklist rules.
        
        Args:
            action_path: The action path (e.g., 'actions/checkout', 'docker/build-push-action')
            
        Returns:
            bool: True if action is allowed, False if blocked
        """
        if not action_path or '/' not in action_path:
            return True
            
        namespace = action_path.split('/')[0]
        full_repo = action_path
        
        # Blacklist takes precedence - check if action or namespace is blacklisted
        for blacklist_item in self.blacklist:
            if blacklist_item == full_repo or blacklist_item == namespace:
                return False
        
        # If no whitelist is specified, allow all non-blacklisted actions
        if not self.whitelist:
            return True
            
        # Check if action or namespace is whitelisted
        for whitelist_item in self.whitelist:
            if whitelist_item == full_repo or whitelist_item == namespace:
                return True
                
        # If whitelist is specified but action is not in it, block it
        return False
    
    def _is_action_trusted(self, action_path: str) -> bool:
        """Check if an action is in the allowlist and should bypass security checks.
        
        Args:
            action_path: The action path (e.g., 'actions/checkout', 'docker/build-push-action')
            
        Returns:
            bool: True if action is trusted and should bypass checks, False otherwise
        """
        if not action_path or '/' not in action_path or not self.allowlist:
            return False
            
        namespace = action_path.split('/')[0]
        full_repo = action_path
        
        # Check if action or namespace is in allowlist
        for allowlist_item in self.allowlist:
            if allowlist_item == full_repo or allowlist_item == namespace:
                return True
                
        return False
        
    def find_workflow_files(self, workflows_dir: str) -> List[str]:
        """Find all YAML workflow files."""
        workflow_files = []
        workflows_path = Path(workflows_dir)
        
        if not workflows_path.exists():
            print(f"Workflows directory not found: {workflows_dir}")
            return []
        
        # Find all YAML files recursively
        for pattern in ['*.yml', '*.yaml']:
            workflow_files.extend(workflows_path.rglob(pattern))
        
        return [str(f) for f in workflow_files]
    
    def parse_workflow_file(self, file_path: str) -> None:
        """Parse a workflow file and extract action references."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Parse YAML
            try:
                workflow = yaml.safe_load(content)
            except yaml.YAMLError as e:
                print(f"Warning: Could not parse YAML in {file_path}: {e}")
                return
            
            # Extract action references using regex on raw content
            # This catches actions in all contexts (jobs, steps, etc.)
            uses_pattern = r'uses:\s*([\'"]?)([^@\s\'"\#]+@[^\s\'"\#]+)\1'
            
            lines = content.split('\n')
            for line_num, line in enumerate(lines, 1):
                match = re.search(uses_pattern, line, re.MULTILINE)
                if match:
                    action_ref = match.group(2).strip()
                    # Skip local actions (starting with ./)
                    if not action_ref.startswith('./'):
                        self.action_references.append({
                            'file': file_path,
                            'line': line_num,
                            'action': action_ref,
                            'raw_line': line.strip()
                        })
        
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
    
    def is_commit_hash(self, version: str) -> bool:
        """Check if version is a commit hash (40-character hex string)."""
        return bool(re.match(r'^[a-f0-9]{40}$', version))
    
    def _fetch(self, url: str) -> Tuple[Optional[requests.Response], str]:
        """GET url, retrying transient failures on self.retry_delays.

        A 5xx, a 429, a timeout or a connection error is transient. Returns
        (response, '') once GitHub gives an answer that is not transient
        (a 200, or a 4xx other than 429), or (None, detail) naming the last
        failure when every attempt failed.
        """
        max_attempts = len(self.retry_delays) + 1
        detail = ''
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(url, timeout=15)
                if response.status_code < 500 and response.status_code != 429:
                    return response, ''
                detail = f'HTTP {response.status_code}'
            except requests.Timeout:
                detail = 'timeout'
            except requests.ConnectionError as e:
                detail = f'connection error: {type(e).__name__}'
            except requests.RequestException as e:
                detail = f'request error: {type(e).__name__}'
            print(f"Warning: Could not fetch {url}: {detail} (attempt {attempt}/{max_attempts})")
            if attempt < max_attempts:
                self.sleep(self.retry_delays[attempt - 1])
        return None, detail

    def check_publisher_live(self, owner: str, action_name: str = None) -> PublisherResult:
        """Decide verified/unverified from the repo and Marketplace pages.

        Returns COULD_NOT_VERIFY, never UNVERIFIED, when a page could not be
        fetched. Does not read or write the cache or the snapshot.
        """
        repo_url = f'https://github.com/{owner}/{action_name}' if action_name else f'https://github.com/{owner}'

        response, error = self._fetch(repo_url)
        if response is None:
            return PublisherResult(COULD_NOT_VERIFY, error, url=repo_url)
        if response.status_code == 404:
            return PublisherResult(UNVERIFIED, 'repository page not found (HTTP 404)', url=repo_url)
        if response.status_code != 200:
            return PublisherResult(COULD_NOT_VERIFY, f'HTTP {response.status_code}', url=repo_url)

        repo_content = response.text

        # Look for "View on Marketplace" link
        marketplace_link_pattern = r'href="(https://github\.com/marketplace/actions/[^"]+)"'
        match = re.search(marketplace_link_pattern, repo_content)

        if not match:
            marketplace_link_pattern = r'href="(/marketplace/actions/[^"]+)"'
            match = re.search(marketplace_link_pattern, repo_content)
            if match:
                marketplace_url = f"https://github.com{match.group(1)}"
            else:
                return PublisherResult(UNVERIFIED, 'no Marketplace listing on the repository page', url=repo_url)
        else:
            marketplace_url = match.group(1)

        marketplace_response, error = self._fetch(marketplace_url)
        if marketplace_response is None:
            return PublisherResult(COULD_NOT_VERIFY, error, url=marketplace_url)
        if marketplace_response.status_code != 200:
            return PublisherResult(COULD_NOT_VERIFY, f'HTTP {marketplace_response.status_code}', url=marketplace_url)

        if self._check_verification_elements(marketplace_response.text, owner):
            return PublisherResult(VERIFIED, 'verified creator badge on the Marketplace page', url=marketplace_url)
        return PublisherResult(UNVERIFIED, 'no verified creator badge on the Marketplace page', url=marketplace_url)

    def check_verified_publisher(self, owner: str, action_name: str = None) -> PublisherResult:
        """Check if the action owner is a verified publisher by fetching repo page and finding marketplace link."""
        # GitHub's own first-party namespaces are always verified. GitHub
        # does not badge its own org as a third-party "partner organization"
        # on the Marketplace, so the scrape-based check below cannot confirm
        # them. Both are already documented as verified publishers in README.
        if owner in ('actions', 'github'):
            return PublisherResult(VERIFIED, 'GitHub first-party namespace', source='first_party')

        # Return a cached verdict (verified or unverified; never a failure)
        if owner in self.publisher_cache:
            return self.publisher_cache[owner]

        result = self.check_publisher_live(owner, action_name)
        if result.status != COULD_NOT_VERIFY:
            self.publisher_cache[owner] = result
            if result.status == VERIFIED:
                self.verified_publishers.add(owner)
            return result

        # The live check could not run. Only now may the snapshot vouch for
        # the owner; a snapshot pass is not cached, so the next action of
        # this owner tries the live check again.
        return self._snapshot_fallback(owner, result)

    def _snapshot_fallback(self, owner: str, failed: PublisherResult) -> PublisherResult:
        verified_at = self._load_snapshot().get(owner)
        if verified_at is None:
            return failed
        age_days = (self.now() - verified_at).days
        if age_days < 0 or age_days > SNAPSHOT_MAX_AGE_DAYS:
            return failed
        detail = (f'verified (from the snapshot of {verified_at.isoformat()}; '
                  f'live check could not run: {failed.detail})')
        return PublisherResult(VERIFIED, detail, source='snapshot', url=failed.url, snapshot_date=verified_at)

    def _load_snapshot(self) -> Dict[str, date]:
        """Read verified-publishers.json once. A missing or malformed file,
        or entry, is ignored with a warning: the result is 'could not
        verify', never a crash."""
        if self._snapshot is not None:
            return self._snapshot
        self._snapshot = load_snapshot(self.snapshot_path)
        return self._snapshot

    def _check_verification_elements(self, page_content: str, owner: str) -> bool:
        """Check for verification elements in the marketplace page content."""
        # Check for "Verified" text
        if 'Verified' not in page_content:
            return False
        
        # Check for the specific verification text
        verification_text = "GitHub has manually verified the creator of the action as an official partner organization."
        if verification_text not in page_content:
            return False
        
        # Check for organization link in the about section
        # Look for various formats of GitHub links (case-insensitive)
        owner_variants = [owner, owner.lower(), owner.upper(), owner.capitalize()]
        
        link_found = False
        for owner_variant in owner_variants:
            org_link_patterns = [
                f'https://github.com/{owner_variant}',
                f'/{owner_variant}',  # Relative link format
                f'href="/{owner_variant}"',  # HTML href format
                f'[{owner_variant}](/{owner_variant})',  # Markdown link format
                f'github.com/{owner_variant}',  # Without protocol
            ]
            
            for pattern in org_link_patterns:
                if pattern in page_content:
                    link_found = True
                    break
            
            if link_found:
                break
        
        if not link_found:
            return False
        
        return True
    
    def audit_actions(self) -> Tuple[List[Dict], int]:
        """Audit all found actions."""
        report = []
        exit_code = 0
        
        print(f"\n🔍 Found {len(self.action_references)} external action references\n")
        
        for ref in self.action_references:
            action_full = ref['action']
            file_path = ref['file']
            line_num = ref['line']
            
            # Parse action owner/name and version
            if '@' not in action_full:
                continue
                
            action_path, version = action_full.rsplit('@', 1)
            if '/' not in action_path:
                continue
                
            owner = action_path.split('/')[0]
            action_name = action_path.split('/')[1] if '/' in action_path else None
            
            # Check if action is allowed based on whitelist/blacklist
            is_action_allowed = self._is_action_allowed(action_path)
            
            # Check if action is trusted (bypasses security checks)
            is_trusted = self._is_action_trusted(action_path)
            
            # Initialize security check variables
            is_pinned_to_hash = False
            is_verified = False
            verification = 'not_checked'
            verification_detail = ''
            snapshot_date = None
            
            # Determine status
            status = "✅ PASS"
            issues = []
            
            if not is_action_allowed:
                issues.append("Blocked by whitelist/blacklist rules")
                status = "❌ FAIL"
                exit_code = 1
            elif is_trusted:
                # Trusted actions bypass verified publisher check but still require commit hash pinning
                is_pinned_to_hash = self.is_commit_hash(version)
                is_verified = True  # Bypass verified publisher check for trusted actions
                verification = 'allowlisted'
                
                if not is_pinned_to_hash:
                    issues.append("Not pinned to commit hash")
                    status = "❌ FAIL"
                    exit_code = 1
                else:
                    issues.append("Trusted - bypassing publisher verification")
            else:
                # Run security checks for non-trusted actions
                # Check if commit hash
                is_pinned_to_hash = self.is_commit_hash(version)
                
                # Check if verified publisher
                result = self.check_verified_publisher(owner, action_name)
                verification = result.status
                verification_detail = result.detail
                snapshot_date = result.snapshot_date
                is_verified = result.status == VERIFIED
                
                if result.status == UNVERIFIED:
                    issues.append("Not from verified publisher")
                    status = "❌ FAIL"
                    exit_code = 1
                elif result.status == COULD_NOT_VERIFY:
                    # A GitHub fetch failure: fail honestly, without
                    # calling it a security finding.
                    issues.append(f"could not verify ({result.detail})")
                    status = "❌ FAIL"
                    exit_code = 1
                    print(f"::error title=Publisher check could not run::{action_path}: fetching "
                          f"{result.url} failed ({result.detail}) after every retry. This is a "
                          f"GitHub fetch failure, not a security finding; re-run once github.com "
                          f"is reachable.")
                elif result.source == 'snapshot':
                    issues.append(result.detail)
                
                if not is_pinned_to_hash:
                    issues.append("Not pinned to commit hash")
                    status = "❌ FAIL"
                    exit_code = 1
            
            
            # Strip the base path for cleaner output
            display_path = file_path
            for prefix in ['/home/runner/work/', '/github/workspace/', os.getcwd() + '/']:
                if display_path.startswith(prefix):
                    display_path = display_path[len(prefix):]
                    break
            
            report_entry = {
                'file': display_path,
                'line': line_num,
                'action': action_full,
                'owner': owner,
                'version': version,
                'is_verified': is_verified,
                'verification': verification,
                'verification_detail': verification_detail,
                'snapshot_date': snapshot_date,
                'is_pinned_to_hash': is_pinned_to_hash,
                'is_action_allowed': is_action_allowed,
                'status': status,
                'issues': issues
            }
            
            report.append(report_entry)
        
        return report, exit_code
    
    def generate_report(self, report: List[Dict], exit_code: int) -> str:
        """Generate a formatted report."""
        output = []
        output.append("# GitHub Actions Security Audit Report")
        output.append("")
        
        could_not_verify_count = sum(1 for r in report if r.get('verification') == COULD_NOT_VERIFY)
        # A failed entry whose only issues are fetch failures is not a finding.
        has_findings = any(
            '❌' in r['status'] and any(not i.startswith('could not verify (') for i in r['issues'])
            for r in report
        )
        
        if exit_code == 0:
            output.append("## ✅ All checks passed!")
        elif has_findings:
            output.append("## ❌ Security issues found!")
        else:
            output.append("## ⚠️ Could not verify every publisher (GitHub fetch failed)")
        
        output.append("")
        output.append(f"**Total actions audited:** {len(report)}")
        
        # Summary statistics
        verified_count = sum(1 for r in report if r['is_verified'])
        hash_pinned_count = sum(1 for r in report if r['is_pinned_to_hash'])
        allowed_count = sum(1 for r in report if r['is_action_allowed'])
        failed_count = sum(1 for r in report if '❌' in r['status'])
        
        output.append(f"**Verified publishers:** {verified_count}/{len(report)}")
        output.append(f"**Could not verify:** {could_not_verify_count}")
        output.append(f"**Commit hash pinned:** {hash_pinned_count}/{len(report)}")
        output.append(f"**Allowed by whitelist/blacklist:** {allowed_count}/{len(report)}")
        output.append(f"**Failed checks:** {failed_count}")
        output.append("")
        
        # Detailed results
        output.append("## Detailed Results")
        output.append("")
        
        for entry in report:
            output.append(f"### {entry['status']} {entry['action']}")
            output.append(f"- **File:** {entry['file']}:{entry['line']}")
            output.append(f"- **Owner:** {entry['owner']}")
            output.append(f"- **Version:** {entry['version']}")
            output.append(f"- **Verified Publisher:** {self._verification_cell(entry)}")
            output.append(f"- **Pinned to Hash:** {'✅' if entry['is_pinned_to_hash'] else '❌'}")
            output.append(f"- **Allowed by Rules:** {'✅' if entry['is_action_allowed'] else '❌'}")
            
            if entry['issues']:
                output.append(f"- **Issues:** {', '.join(entry['issues'])}")
            
            output.append("")
        
        # Recommendations
        if exit_code != 0:
            output.append("## 🔧 Recommendations")
            output.append("")
            output.append("1. **Pin to commit hashes:** Use specific commit SHA instead of tags")
            output.append("2. **Use verified publishers:** Only use actions from trusted sources")
            if could_not_verify_count:
                output.append("3. **Could not verify:** GitHub's pages could not be fetched for "
                              f"{could_not_verify_count} action(s). That is a GitHub fetch failure, "
                              "not a security finding: re-run once github.com is reachable")
            output.append("")
            output.append("Example of secure action usage:")
            output.append("```yaml")
            output.append("- name: Checkout")
            output.append("  uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1")
            output.append("```")
        
        return "\n".join(output)
    
    @staticmethod
    def _verification_cell(entry: Dict) -> str:
        if entry.get('verification') == COULD_NOT_VERIFY:
            return f"⚠️ could not verify ({entry['verification_detail']})"
        if entry.get('snapshot_date'):
            return f"✅ (snapshot of {entry['snapshot_date'].isoformat()})"
        return '✅' if entry['is_verified'] else '❌'
    
    def run_audit(self, workflows_dir: str) -> Tuple[str, int]:
        """Run the complete audit."""
        print("🔍 Starting GitHub Actions security audit...")
        
        # Show whitelist/blacklist configuration
        if self.whitelist:
            print(f"✅ Whitelist: {', '.join(self.whitelist)}")
        if self.blacklist:
            print(f"❌ Blacklist: {', '.join(self.blacklist)}")
        
        # Find workflow files
        workflow_files = self.find_workflow_files(workflows_dir)
        print(f"📁 Found {len(workflow_files)} workflow files")
        
        # Parse each file
        for file_path in workflow_files:
            self.parse_workflow_file(file_path)
        
        # Audit actions
        report, exit_code = self.audit_actions()
        
        # Generate report
        report_text = self.generate_report(report, exit_code)
        
        return report_text, exit_code

def main():
    github_token = os.environ.get('GITHUB_TOKEN', '')
    if not github_token:
        print("Error: GITHUB_TOKEN environment variable is required")
        sys.exit(1)
    
    workflows_dir = os.environ.get('WORKFLOWS_DIR', '.github/workflows')
    whitelist = os.environ.get('WHITELIST', '')
    blacklist = os.environ.get('BLACKLIST', '')
    allowlist = os.environ.get('ALLOWLIST', '')
    
    auditor = ActionAuditor(github_token, whitelist, blacklist, allowlist)
    report, exit_code = auditor.run_audit(workflows_dir)
    
    print(report)
    
    # Save report to file
    with open('action-security-report.md', 'w') as f:
        f.write(report)
    
    # Set GitHub Actions outputs using new syntax
    with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as f:
        f.write(f"report<<EOF\n{report}\nEOF\n")
        f.write(f"exit_code={exit_code}\n")
    
    sys.exit(exit_code)

if __name__ == '__main__':
    main()