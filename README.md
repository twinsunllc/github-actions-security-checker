# GitHub Actions Security Checker

[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-GitHub%20Actions%20Security%20Checker-blue?logo=github)](https://github.com/marketplace/actions/github-actions-security-checker)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A GitHub Action that audits your workflows for security best practices, ensuring all actions come from verified publishers and are pinned to specific commit hashes.

## 🛡️ Features

- **Verified Publisher Check**: Ensures actions come from trusted, verified publishers
- **Commit Hash Pinning**: Verifies actions are pinned to specific commit SHAs (not tags)
- **Whitelist/Blacklist Support**: Control which actions and namespaces are allowed or blocked
- **Typo Detection**: Catches common typos in action names that could lead to supply chain attacks
- **Comprehensive Reporting**: Generates detailed Markdown reports with actionable recommendations
- **CI/CD Integration**: Fails builds when security issues are detected

## 🚀 Quick Start

Add this to your workflow:

```yaml
name: Security Audit
on: [push, pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run GitHub Actions Security Checker
        uses: twinsunllc/github-actions-security-checker@b4959464b5cc12750f8025dc202dce73f32a7676 # v1.4.2
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

## 📥 Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `github_token` | GitHub token for API access | Yes | `${{ github.token }}` |
| `workflows_dir` | Directory containing workflow files | No | `.github/workflows` |
| `whitelist` | List of allowed namespaces or repositories | No | `''` |
| `blacklist` | List of blocked namespaces or repositories | No | `''` |
| `allowlist` | List of trusted namespaces that bypass publisher verification but still require commit hash pinning | No | `''` |

## 📤 Outputs

| Output | Description |
|--------|-------------|
| `report` | Security audit report in Markdown format |
| `exit_code` | Exit code (0 for pass, 1 for fail) |
| `passed` | Boolean indicating if all checks passed |

## 📋 Security Checks

### 1. Verified Publisher Check
GitHub's own namespaces (`actions/*`, `github/*`) are always verified. For any other owner, the checker
loads the action's repository page on github.com, follows its "View on Marketplace" link, and looks for
the Marketplace "verified creator" badge. Each action it checks (one not allowlisted or blocked) gets one of three outcomes:

| Outcome | When | Result |
|---------|------|--------|
| ✅ verified | The Marketplace page loaded and shows the badge | Pass |
| ❌ `Not from verified publisher` | A page loaded and shows no badge, the repository has no Marketplace listing, or the repository page is a 404 | Fail: a security finding |
| ⚠️ `could not verify (<HTTP status or error>)` | github.com could not be fetched: a 5xx, a 429, a timeout or a connection error, still failing after the retries; or another 4xx | Fail, counted separately as **Could not verify**. It is a GitHub fetch failure, not a security finding, and is also raised as a `::error` annotation saying so |

A 5xx, a 429, a timeout or a connection error is retried with backoff (5, 10, 20, 40 and 60 seconds:
135 seconds over six attempts) for each page before the check gives up. Only real verdicts are
cached for the rest of the run; after a fetch failure, the next action of the same owner is fetched again.

#### Snapshot fallback (`verified-publishers.json`)
The checker ships `verified-publishers.json`: the owners the live check verified when the release was
cut, each with its `verified_at` date. It is read **only** when the live check could not run:

- An owner listed there with a `verified_at` within the last 90 days passes, reported as
  `verified (from the snapshot of <date>; live check could not run: <error>)`.
- An owner that is not listed, or whose entry is older than 90 days, stays `could not verify`.
- The file is never consulted when a page loaded. A live "no badge" fails even for an owner in the snapshot.
- It holds positive entries only. Nothing ever records an owner as unverified.

Because you pin the checker by sha, the snapshot you get is the one in the release you pinned.

### 2. Commit Hash Pinning
Ensures actions use full 40-character commit SHAs instead of tags:
- ❌ `uses: actions/checkout@v4` (tag - vulnerable to tag movement)
- ✅ `uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11` (commit hash)

### 3. Typo Detection
Catches common typos that could be exploited:
- `aws-action/*` → Should be `aws-actions/*`

## 📊 Example Report

```markdown
# GitHub Actions Security Audit Report

## ❌ Security issues found!

**Total actions audited:** 5
**Verified publishers:** 3/5
**Could not verify:** 0
**Commit hash pinned:** 2/5
**Allowed by whitelist/blacklist:** 4/5
**Failed checks:** 3

## Detailed Results

### ❌ FAIL third-party/action@v1
- **File:** .github/workflows/build.yml:15
- **Owner:** third-party
- **Version:** v1
- **Verified Publisher:** ❌
- **Pinned to Hash:** ❌
- **Allowed by Rules:** ✅
- **Issues:** Not from verified publisher, Not pinned to commit hash
```

## 🔧 Best Practices

1. **Always pin to commit hashes**: Use tools like [pin-github-action](https://github.com/mheap/pin-github-action) to automatically pin your actions
2. **Review third-party actions**: Audit the source code before using actions from unverified publishers
3. **Keep actions updated**: Regularly update commit hashes to get security patches
4. **Use Dependabot**: Enable Dependabot to automatically update action versions

## 🏗️ Advanced Usage

### Whitelist/Blacklist/Allowlist Configuration

Control which actions are processed and how they're validated:

- **Whitelist**: Only specified actions are processed (restrictive filtering)
- **Blacklist**: Specified actions are blocked entirely  
- **Allowlist**: Trusted actions bypass publisher verification but still require commit hash pinning

#### Multiline Format (Recommended)
```yaml
- uses: twinsunllc/github-actions-security-checker@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    whitelist: |
      actions
      docker
      hashicorp/setup-terraform
    blacklist: |
      suspicious
      untrusted/repo
    allowlist: |
      actions
      docker
```

#### Comma-Separated Format
```yaml
- uses: twinsunllc/github-actions-security-checker@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    whitelist: "actions, docker, hashicorp/setup-terraform"
    blacklist: "suspicious, untrusted/repo"
    allowlist: "actions, docker"
```

**Important Rules:**
- **Blacklist takes precedence**: If an action is in both whitelist and blacklist, it will be blocked
- **No whitelist = allow all**: If no whitelist is specified, all non-blacklisted actions are allowed
- **Allowlist provides security convenience**: Trust certain publishers while maintaining commit hash protection
- **Namespace vs specific**: `docker` affects all `docker/*` actions, while `docker/build-push-action` targets only that specific action

#### Allowlist Use Cases

**Scenario 1: Trust GitHub's official actions**
```yaml
allowlist: "actions"
# actions/checkout@v4 → ❌ FAIL (not pinned)
# actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 → ✅ PASS (trusted + pinned)
```

**Scenario 2: Trust multiple publishers**
```yaml
allowlist: |
  actions
  docker
  hashicorp
```

### Custom Workflows Directory

```yaml
- uses: twinsunllc/github-actions-security-checker@b4959464b5cc12750f8025dc202dce73f32a7676 # v1.4.2
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    workflows_dir: '.github/custom-workflows'
```

### Upload Report as Artifact

```yaml
- uses: twinsunllc/github-actions-security-checker@b4959464b5cc12750f8025dc202dce73f32a7676 # v1.4.2
  id: security-audit
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}

- uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
  if: always()
  with:
    name: security-report
    path: action-security-report.md
```

### Conditional Failure

```yaml
- uses: twinsunllc/github-actions-security-checker@b4959464b5cc12750f8025dc202dce73f32a7676 # v1.4.2
  id: security-audit
  continue-on-error: true
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}

- name: Check audit results
  if: steps.security-audit.outputs.passed != 'true'
  run: |
    echo "::warning::Security issues found in GitHub Actions"
    cat action-security-report.md
```

## 🧪 Development

Run the unit tests (Python 3.9+, with `pyyaml` and `requests` installed):

```bash
python -m unittest discover -b -s tests -t .
```

## 📦 Releasing

1. Refresh the snapshot from the live Marketplace check. With no arguments, the script re-checks every
   owner already in the file through its recorded `checked_via` action; pass `owner/repo` arguments to
   add owners:
   ```bash
   python scripts/refresh_verified_publishers.py
   python scripts/refresh_verified_publishers.py docker/build-push-action   # add or re-check one owner
   ```
   An owner the live check verifies is written with today's date. An owner it finds unverified is
   removed. When the live check cannot run, an existing entry is left as it is and the script says it
   was not refreshed. No workflow runs this script or writes to the repository.
2. Commit `verified-publishers.json` with the release's CHANGELOG entry.
3. Tag the release (`vX.Y.Z`) on `main`.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by GitHub's security best practices
- Community feedback and contributions

## 📞 Support

- 🐛 [Report a bug](https://github.com/twinsunllc/github-actions-security-checker/issues)
- 💡 [Request a feature](https://github.com/twinsunllc/github-actions-security-checker/issues)
- 📖 [Read the docs](https://github.com/twinsunllc/github-actions-security-checker/wiki)

---

Made with ❤️ by [Twin Sun LLC](https://github.com/twinsunllc)
