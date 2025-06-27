# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2025-06-27

### Added
- **Whitelist/Blacklist Support**: Added comprehensive support for allowing and blocking specific actions and namespaces
  - Supports YAML array format: `whitelist: [- actions, - docker]`
  - Supports multiline string format: `whitelist: |` with newline-separated items
  - Supports JSON array format: `whitelist: '["actions", "docker"]'`
  - Supports comma-separated format for backward compatibility
  - Blacklist takes precedence over whitelist rules
  - Namespace matching (e.g., `docker` blocks all `docker/*` actions)
  - Specific repository matching (e.g., `docker/build-push-action`)
- **Enhanced Reporting**: Added "Allowed by Rules" status to audit reports
- **Comprehensive Testing**: Added 5 new test jobs to validate whitelist/blacklist functionality
  - YAML array format testing
  - Multiline string format testing  
  - Blacklist precedence verification
  - Blacklist-only mode testing
  - Mixed whitelist/blacklist scenarios

### Changed
- Updated `action.yml` inputs to accept array formats for `whitelist` and `blacklist` parameters
- Enhanced `_parse_list()` method to handle multiple input formats automatically
- Updated audit logic to respect whitelist/blacklist rules during security checks
- Improved debug output to show active whitelist/blacklist configuration

### Technical Details
- Added `_is_action_allowed()` method to implement whitelist/blacklist logic
- Enhanced environment variable parsing for array inputs
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