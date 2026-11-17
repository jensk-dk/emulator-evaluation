# Functional Verification Specification

## Purpose

Define the checks that confirm, on a host, that the emulator does what the other specifications require, and the record of what was confirmed on each host.

## Requirements

### Requirement: Verify the emulator's features with checks on the host

The startup launcher MUST offer a command that runs verification checks on the host it is started on. Each check MUST confirm one thing that a task of the delivery plan requires and, where that depends on the emulator mode, in one emulator mode: container, host-native VM, ARM64 VM, or ARM32 VM. A check MUST go by what it observes, such as what the target reports, a capture of the display, or the sound that the host takes, and MUST say what it found. Each check MUST end with one of three outcomes: passed, failed, or could not be run on this host. A check that could not be run MUST NOT be reported as passed or as failed. The command MUST run every check unless checks are named, MUST accept the names of the checks to run, and MUST offer a list of the checks. It MUST report failure when a check failed.

#### Scenario: Run every check

- WHEN the verification command is run without naming a check
- THEN every check is run on that host, and each reports its outcome and what it found

#### Scenario: Run named checks

- WHEN the verification command is run with the names of checks
- THEN only those checks are run

#### Scenario: List the checks

- WHEN the list of checks is asked for
- THEN the command names every check with what it confirms, and runs none

#### Scenario: A check fails

- WHEN a check finds that what it looks at is not as required
- THEN the check ends as failed, says what it found, and the command reports failure

#### Scenario: A check cannot be run on this host

- WHEN a check needs something that the host does not offer
- THEN the check ends as could not be run, says why, and is counted neither as passed nor as failed

### Requirement: Keep the simulated ARM targets built and verified

The simulated ARM targets are not set up on a host by default, so nothing would show when a change breaks them. The project's instructions for automated agents, in the file AGENTS.md at the top of the project, MUST therefore direct an agent that sets up a host, builds, or verifies to include them: to run the setup script with the option for the simulated ARM targets, to build their target images, and to run the verification checks for them. They MUST direct the agent to say so when it could not do that on a host.

#### Scenario: An agent sets up a host

- WHEN an automated agent follows the project's instructions to set up a host
- THEN it runs the setup script with the option for the simulated ARM targets

#### Scenario: An agent builds and verifies

- WHEN an automated agent follows the project's instructions to build or to verify
- THEN it builds the target images of the ARM64 and ARM32 guest CPU modes as well, and runs the checks for them

#### Scenario: An agent cannot include the ARM targets

- WHEN an automated agent cannot set up, build or verify the simulated ARM targets on a host
- THEN it says so, and why

### Requirement: Record the outcome of each check per host

The verification command MUST keep a record, in the project's directory, of the last outcome of each check for each host operating system and host CPU architecture it was run on. The record MUST describe the host, and MUST state for each check its outcome, what the check found, when it ran, how long it took, the source revision and the target image definition it ran against, and the task of the delivery plan that it supports. Running some of the checks MUST replace the entries of those checks only. The record MUST NOT keep an outcome for a check that no longer exists.

#### Scenario: Record a check

- WHEN a check has ended
- THEN the record of that host states its outcome, what it found, when it ran, and the source revision and image definition it ran against

#### Scenario: Run some of the checks

- WHEN only some of the checks are run on a host
- THEN the record keeps the earlier outcomes of the other checks

#### Scenario: Review what was verified on a host

- WHEN the record of a host is read
- THEN for each check it can be identified whether it passed, failed, or could not be run there, and against which revision

#### Scenario: A check was removed

- WHEN the verification command is run after a check has been removed
- THEN the record no longer holds an outcome for that check
