# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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