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
        uses: twinsunllc/github-actions-security-checker@3431967fb16dd3d0e96fcf823ba33609c2df31ee # v1.4.1
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
The action maintains a list of verified publishers including:
- Official GitHub actions (`actions/*`, `github/*`)
- Major cloud providers (`aws-actions/*`, `azure/*`, `google-github-actions/*`)
- Popular community actions from verified maintainers

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
- uses: twinsunllc/github-actions-security-checker@3431967fb16dd3d0e96fcf823ba33609c2df31ee # v1.4.1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    workflows_dir: '.github/custom-workflows'
```

### Upload Report as Artifact

```yaml
- uses: twinsunllc/github-actions-security-checker@3431967fb16dd3d0e96fcf823ba33609c2df31ee # v1.4.1
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
- uses: twinsunllc/github-actions-security-checker@3431967fb16dd3d0e96fcf823ba33609c2df31ee # v1.4.1
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
