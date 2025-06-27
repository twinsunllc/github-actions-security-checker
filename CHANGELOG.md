# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.1] - 2025-06-27

### Changed
- Updated copyright year to 2025 and copyright holder to "Twin Sun, LLC"

## [1.4.0] - 2025-06-27

### Added
- **Allowlist Support**: Added `allowlist` input parameter for trusted actions that bypass verified publisher checks while still enforcing commit hash pinning
  - Provides security convenience for trusted publishers (e.g., `actions`, `docker`)
  - Maintains protection against tag mutation attacks by requiring commit hash pinning
  - Supports both namespace (`actions`) and repository-level (`actions/checkout`) matching
  - Uses same input formats as whitelist/blacklist (comma-separated or multiline)
- **Enhanced Security Model**: Three-tier action control system:
  - **Whitelist**: Restrictive filtering (only specified actions processed)
  - **Blacklist**: Complete blocking of specified actions
  - **Allowlist**: Trusted publisher bypass with hash pinning enforcement
- **Comprehensive Test Coverage**: Added dedicated allowlist test workflow with isolation

### Changed
- **BREAKING CHANGE**: Allowlist security model refined to only bypass publisher verification, not commit hash requirements
- Updated action description and README documentation with allowlist use cases
- Modified audit report messages: "Trusted - bypassing publisher verification" instead of "bypassing security checks"
- Enhanced README with security explanations and practical allowlist scenarios

### Fixed
- Isolated allowlist test to prevent interference from other workflow files
- Added proper `continue-on-error` handling for tests expecting audit failures
- Fixed test expectations to match new allowlist security behavior

### Technical Details
- Added `_is_action_trusted()` method to identify allowlisted actions
- Updated audit flow to handle three-way logic: blocked, trusted, or normal validation
- Maintains backward compatibility with existing whitelist/blacklist functionality
- Comprehensive documentation updates explaining security benefits

This release significantly improves the security posture by providing a trusted publisher mechanism that maintains protection against tag mutation attacks while reducing verification friction for known-good publishers.

## [1.3.0] - 2025-06-27

### Added
- **Whitelist/Blacklist Support**: Added support for allowing and blocking specific actions and namespaces
  - Supports multiline format: `whitelist: |` with newline-separated items
  - Supports comma-separated format: `whitelist: "actions, docker"`
  - Blacklist takes precedence over whitelist rules
  - Namespace matching (e.g., `docker` blocks all `docker/*` actions)
  - Specific repository matching (e.g., `docker/build-push-action`)
- **Enhanced Reporting**: Added "Allowed by Rules" status to audit reports
- **Comprehensive Testing**: Added 5 new test jobs to validate whitelist/blacklist functionality
  - Comma-separated format testing
  - Multiline string format testing  
  - Blacklist precedence verification
  - Blacklist-only mode testing
  - Mixed whitelist/blacklist scenarios

### Changed
- Updated `action.yml` inputs to accept list formats for `whitelist` and `blacklist` parameters
- Added `_parse_list()` method to handle comma-separated and newline-separated formats
- Updated audit logic to respect whitelist/blacklist rules during security checks
- Improved debug output to show active whitelist/blacklist configuration

### Technical Details
- Added `_is_action_allowed()` method to implement whitelist/blacklist logic
- Simple and reliable parsing for two intuitive input formats
- Updated report generation to include whitelist/blacklist status
- Maintains full backward compatibility with existing configurations

## [1.2.0] - 2025-06-27

### Changed
- **Improved marketplace detection**: Updated verification logic to fetch repository pages first and extract actual marketplace links, providing more accurate detection regardless of action naming conventions
- Example: `docker/setup-buildx-action` now correctly maps to `https://github.com/marketplace/actions/docker-setup-buildx`

### Removed
- **Removed typo detection**: Eliminated hardcoded typo checks (e.g., aws-action vs aws-actions) in favor of the more robust marketplace link discovery approach

### Technical Details
- Modified `check_verified_publisher()` to fetch repository pages and parse marketplace links using regex patterns
- Supports both absolute and relative marketplace link formats
- More reliable than previous URL guessing approach

## [1.1.2] - 2025-06-27

### Fixed
- Moved insecure test workflow files to a separate `test-workflows/` directory to prevent the security checker from flagging test files
- Updated test workflow to copy test files during execution instead of generating them inline
- This ensures the security checker only validates actual workflow files, not test fixtures

## [1.1.1] - 2025-06-27

### Fixed
- Fixed regex pattern for detecting external GitHub Actions in workflow files
- The pattern was too restrictive and failed to match actions with inline comments
- Now correctly identifies all external action references regardless of trailing comments or whitespace

## [1.1.0] - 2025-06-27

### Changed
- **Enhanced verified publisher verification**: Instead of using a static list of known verified publishers, the action now fetches the GitHub Marketplace page for each action to verify publisher status
- Verification now checks for:
  - "Verified" badge/text on the marketplace page
  - Official verification text: "GitHub has manually verified the creator of the action as an official partner organization."
  - Organization link in the about section pointing to the publisher's GitHub organization
- Added support for multiple marketplace URL patterns to improve action discovery
- Improved case-insensitive matching for organization links
- Enhanced error handling and timeout management for marketplace page fetching

### Technical Details
- Modified `check_verified_publisher()` method to fetch marketplace pages instead of using hardcoded list
- Added `_check_verification_elements()` helper method to validate verification criteria
- Increased timeout to 15 seconds for marketplace page requests
- Added fallback URL patterns for better action discovery

This change provides more accurate and up-to-date verification of action publishers by checking the actual GitHub Marketplace verification status rather than relying on a potentially outdated static list.

## [1.0.0] - Initial Release

### Added
- Initial implementation of GitHub Actions Security Checker
- Checks for verified publishers using static list
- Validates commit hash pinning for actions
- Generates detailed security audit reports
- Supports custom workflows directory configuration
- Provides pass/fail exit codes for CI/CD integration