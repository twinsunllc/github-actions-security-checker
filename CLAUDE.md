# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GitHub Actions Security Checker is a composite GitHub Action that audits workflow files for security best practices. The implementation consists of two main files:
- `action.yml`: The GitHub Action definition file
- `audit_actions.py`: The Python script containing all audit logic

## Common Development Tasks

### Testing the Action

To test the security checker:
```bash
# Unit tests (requests.get is mocked; nothing sleeps or touches the network)
python -m unittest discover -b -s tests -t .

# The action includes test workflows that intentionally contain security issues
# Review test-workflows/insecure.yml for examples of what the checker catches

# To manually test the Python logic, run the script directly with appropriate environment variables:
export GITHUB_TOKEN="your-github-token"
export WORKFLOWS_DIR=".github/workflows"
python3 audit_actions.py
```

### Making Changes

When modifying the action:
1. All code changes should be made to the `audit_actions.py` file
2. The `action.yml` file references this script and copies it at runtime
3. Key classes and methods in `audit_actions.py`:
   - `ActionAuditor`: Main class containing all security check logic
   - `check_verified_publisher()`: Verifies actions against GitHub Marketplace. Returns a `PublisherResult`
     whose `status` is `verified`, `unverified` or `could_not_verify` (a GitHub fetch failure, never a finding).
     Only real verdicts go into `publisher_cache`. `verified-publishers.json` is read only after a
     `could_not_verify`, via `_snapshot_fallback()`.
   - `check_publisher_live()`: The live repo-page + Marketplace scrape, with `_fetch()` retrying 5xx/429/timeouts/connection errors
     on `retry_delays` (injectable, with `sleep` and `now`, so tests never sleep)
   - `is_commit_hash()`: Validates SHA pinning
   - `generate_report()`: Creates Markdown output

### Security Checks Implemented

1. **Verified Publisher Check**: Dynamically fetches GitHub Marketplace pages to verify publisher status
2. **Commit Hash Pinning**: Ensures actions use 40-character SHA hashes instead of tags
3. **Typo Detection**: Identifies common typos in action names (e.g., `aws-action` vs `aws-actions`)

## Architecture Notes

- **Modular Design**: Logic is separated into `audit_actions.py` for easier maintenance and testing
- **No Build Process**: As a GitHub Action, it self-installs dependencies at runtime
- **Regex-based Parsing**: Uses regex patterns to extract action references from YAML files
- **Dynamic Verification**: Avoids maintaining static allow-lists by checking GitHub Marketplace in real-time.
  The only static list is `verified-publishers.json`, a positive-only snapshot used when the live check cannot
  run, refreshed at release by `scripts/refresh_verified_publishers.py`

## Key Implementation Details

- Action references are extracted using the pattern: `r'uses:\s*([^@\s]+)@([^\s]+)'`
- GitHub Marketplace verification uses the URL: `https://github.com/marketplace/actions/{action_name}`
- Exit codes: 0 for pass, 1 for security issues found
- Outputs include detailed Markdown reports and summary statistics