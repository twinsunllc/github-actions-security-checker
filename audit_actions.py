#!/usr/bin/env python3
import os
import re
import sys
import json
import yaml
import requests
from pathlib import Path
from typing import Dict, List, Tuple, Set

class ActionAuditor:
    def __init__(self, github_token: str, whitelist: str = '', blacklist: str = ''):
        self.github_token = github_token
        self.headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Action-Security-Auditor/1.0'
        }
        self.verified_publishers = set()
        self.action_references = []
        self.issues = []
        self.whitelist = self._parse_list(whitelist)
        self.blacklist = self._parse_list(blacklist)
        
    def _parse_list(self, list_input: str) -> List[str]:
        """Parse list input which can be JSON array, YAML array, multiline string, space-separated, or comma-separated string."""
        if not list_input or not list_input.strip():
            return []
        
        list_input = list_input.strip()
        
        # Try to parse as JSON array first
        if list_input.startswith('[') and list_input.endswith(']'):
            try:
                parsed = json.loads(list_input)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
        
        # Handle Python list string representation (e.g., "['item1', 'item2']")
        if list_input.startswith("['") and list_input.endswith("']"):
            try:
                # Use eval safely for simple list strings
                parsed = eval(list_input)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except (SyntaxError, NameError, ValueError):
                pass
        
        # Handle multiline string (each line is an item) - GitHub Actions YAML array format
        if '\n' in list_input:
            return [line.strip() for line in list_input.split('\n') if line.strip()]
        
        # Handle space-separated strings (another possible GitHub Actions format)
        if ' ' in list_input and ',' not in list_input:
            return [item.strip() for item in list_input.split(' ') if item.strip()]
        
        # Fall back to comma-separated string for backward compatibility
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
    
    def check_verified_publisher(self, owner: str, action_name: str = None) -> bool:
        """Check if the action owner is a verified publisher by fetching repo page and finding marketplace link."""
        if owner in self.verified_publishers:
            return True
        
        # First, fetch the repository page to find the marketplace link
        repo_url = f'https://github.com/{owner}/{action_name}' if action_name else f'https://github.com/{owner}'
        
        try:
            # Fetch repository page
            response = requests.get(repo_url, timeout=15)
            
            if response.status_code != 200:
                print(f"Warning: Could not fetch repository page {repo_url}: HTTP {response.status_code}")
                return False
            
            repo_content = response.text
            
            # Look for "View on Marketplace" link
            marketplace_link_pattern = r'href="(https://github\.com/marketplace/actions/[^"]+)"'
            match = re.search(marketplace_link_pattern, repo_content)
            
            if not match:
                # Try alternative pattern for marketplace links
                marketplace_link_pattern = r'href="(/marketplace/actions/[^"]+)"'
                match = re.search(marketplace_link_pattern, repo_content)
                if match:
                    marketplace_url = f"https://github.com{match.group(1)}"
                else:
                    return False
            else:
                marketplace_url = match.group(1)
            
            # Now fetch the marketplace page
            marketplace_response = requests.get(marketplace_url, timeout=15)
            
            if marketplace_response.status_code == 200:
                marketplace_content = marketplace_response.text
                
                # Check for verification elements
                is_verified = self._check_verification_elements(marketplace_content, owner)
                
                # Cache the result
                if is_verified:
                    self.verified_publishers.add(owner)
                
                return is_verified
            else:
                print(f"Warning: Could not fetch marketplace page {marketplace_url}: HTTP {marketplace_response.status_code}")
                return False
                
        except Exception as e:
            print(f"Warning: Error checking verification for {owner}/{action_name}: {e}")
            return False
    
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
            
            # Check if commit hash
            is_pinned_to_hash = self.is_commit_hash(version)
            
            # Check if verified publisher
            is_verified = self.check_verified_publisher(owner, action_name)
            
            # Determine status
            status = "✅ PASS"
            issues = []
            
            if not is_action_allowed:
                issues.append("Blocked by whitelist/blacklist rules")
                status = "❌ FAIL"
                exit_code = 1
            
            if not is_verified:
                issues.append("Not from verified publisher")
                status = "❌ FAIL"
                exit_code = 1
            
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
        
        if exit_code == 0:
            output.append("## ✅ All checks passed!")
        else:
            output.append("## ❌ Security issues found!")
        
        output.append("")
        output.append(f"**Total actions audited:** {len(report)}")
        
        # Summary statistics
        verified_count = sum(1 for r in report if r['is_verified'])
        hash_pinned_count = sum(1 for r in report if r['is_pinned_to_hash'])
        allowed_count = sum(1 for r in report if r['is_action_allowed'])
        failed_count = sum(1 for r in report if '❌' in r['status'])
        
        output.append(f"**Verified publishers:** {verified_count}/{len(report)}")
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
            output.append(f"- **Verified Publisher:** {'✅' if entry['is_verified'] else '❌'}")
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
            output.append("")
            output.append("Example of secure action usage:")
            output.append("```yaml")
            output.append("- name: Checkout")
            output.append("  uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1")
            output.append("```")
        
        return "\n".join(output)
    
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
    
    auditor = ActionAuditor(github_token, whitelist, blacklist)
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