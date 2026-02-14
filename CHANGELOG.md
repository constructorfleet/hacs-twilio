# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.8.0] - 2026-02-14

### Changed
- Version bump via PR #22

## [2.7.0] - 2026-02-14

### Changed
- Version bump via PR #21

## [2.6.0] - 2026-02-14

### Changed
- Version bump via PR #20

## [2.5.0] - 2026-02-14

### Changed
- Version bump via PR #19

## [2.4.0] - 2026-02-14

### Changed
- Version bump via PR #18

## [2.3.0] - 2026-02-14

### Changed
- Version bump via PR #17

## [2.2.0] - 2026-02-14

### Changed
- Version bump via PR #16

## [2.1.0] - 2026-02-14

### Changed
- Version bump via PR #15

## [2.0.0] - 2026-02-14

### Changed
- Version bump via PR #14

## [1.18.0] - 2026-02-14

### Changed
- Version bump via PR #13

## [1.17.0] - 2026-02-14

### Changed
- Version bump via PR #12

## [1.16.0] - 2026-02-14

### Changed
- Version bump via PR #11

## [1.15.0] - 2026-02-14

### Changed
- Version bump via PR #10

## [1.14.0] - 2026-02-14

### Changed
- Version bump via PR #9

## [1.13.0] - 2026-02-14

### Changed
- Version bump via PR #8

## [1.12.0] - 2026-02-14

### Changed
- Version bump via PR #8

## [1.11.0] - 2026-02-14

### Changed
- Version bump via PR #8

## [1.10.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.9.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.8.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.7.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.6.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.5.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.4.0] - 2026-02-14

### Changed
- Version bump via PR #4

## [1.3.0] - 2026-02-14

### Changed
- Version bump via PR #2

## [1.2.0] - 2026-02-14

### Changed
- Version bump via PR #2

## [1.1.0] - 2026-02-14

### Changed
- Version bump via PR #1

## [1.0.0] - 2024-02-14

### Added
- Initial release of Twilio integration for Home Assistant
- SMS notification support with plain text messages
- MMS notification support with media URLs
- Voice call notification with three call types:
  - Simple text-to-speech calls
  - Custom TwiML URL calls
  - Interactive calls with DTMF gathering and recording
- Event system for incoming messages and calls:
  - `twilio_sms_received` event
  - `twilio_call_received` event
  - `twilio_call_ended` event
  - `twilio_dtmf_received` event
  - `twilio_transcription_received` event
- Webhook support for real-time Twilio updates
- UI configuration flow for easy setup
- Three automation blueprints:
  - Emergency Alert system
  - Interactive Phone Menu
  - SMS Command Handler
- Comprehensive documentation:
  - README with installation and usage instructions
  - Example configurations
  - Implementation details
  - HACS info page
- HACS compatibility with proper metadata
- Security features:
  - HTTPS for all external communications
  - No vulnerabilities in dependencies
  - CodeQL security analysis passed

### Dependencies
- twilio==9.10.1
- Home Assistant 2023.1.0 or newer

### Notes
- Based on Home Assistant Core Twilio Integration with significant enhancements
- Uses Twilio Twimlets for basic TwiML generation (suitable for simple use cases)
- For production deployments with advanced features, consider hosting custom TwiML endpoints
