# Host Setup Specification

## Purpose

Define the setup script that prepares a development host to run the emulator.

## Requirements

### Requirement: Provide a setup script for all supported host operating systems

The project MUST provide a setup script for each supported host operating system: Linux, macOS, and Windows.

#### Scenario: Run setup on Linux

- WHEN a developer prepares a Linux host
- THEN a setup script is available that runs on that host

#### Scenario: Run setup on macOS

- WHEN a developer prepares a macOS host
- THEN a setup script is available that runs on that host

#### Scenario: Run setup on Windows

- WHEN a developer prepares a Windows host
- THEN a setup script is available that runs on that host

### Requirement: Check and install host dependencies

The setup script MUST check for every host dependency the emulator requires and MUST install any that are missing.

#### Scenario: Check host dependencies

- WHEN the setup script is run on a supported host
- THEN it checks whether each required host dependency is present

#### Scenario: Install missing host dependencies

- WHEN the setup script finds a required host dependency missing
- THEN it installs that dependency

#### Scenario: Dependencies already present

- WHEN the setup script is run on a host where every required dependency is present
- THEN it completes without installing anything
