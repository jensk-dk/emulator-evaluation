# Performance Evaluation Specification

## Purpose

Define the coverage matrix and measurement areas for evaluating emulator performance.

## Requirements

### Requirement: Evaluate every supported host and emulator combination

Performance evaluation MUST cover every supported combination of host operating system, host CPU architecture, and emulator execution mode. VM-based evaluations MUST cover each supported guest CPU architecture.

#### Scenario: Evaluate a host and execution-mode combination

- WHEN performance evaluation is carried out
- THEN results are collected for every supported host OS, host CPU architecture, and emulator mode combination

#### Scenario: Evaluate VM guest architectures

- WHEN performance evaluation is carried out for VM-based mode
- THEN results cover host-native, ARM32, and ARM64 guest CPU modes

### Requirement: Measure all required performance areas

Every evaluated combination MUST measure CPU performance, memory allocation, memory bandwidth, I/O performance, graphics performance, and audio/video decoding performance.

#### Scenario: Measure CPU performance

- WHEN an emulator configuration is evaluated
- THEN CPU performance is measured

#### Scenario: Measure memory performance

- WHEN an emulator configuration is evaluated
- THEN memory allocation and memory bandwidth are measured

#### Scenario: Measure I/O performance

- WHEN an emulator configuration is evaluated
- THEN I/O performance is measured

#### Scenario: Measure graphics performance

- WHEN an emulator configuration is evaluated
- THEN graphics performance is measured

#### Scenario: Measure audio/video decoding performance

- WHEN an emulator configuration is evaluated
- THEN audio and video decoding performance are measured

### Requirement: Show the evaluation matrix

The startup launcher MUST offer a command that shows the evaluation matrix: the hosts, by operating system and CPU architecture, the emulator modes to evaluate on each, each VM guest CPU architecture included, and the performance areas to measure. On request the command MUST check that the matrix is complete, name each thing that is missing from it, and report failure when something is missing.

#### Scenario: Show the matrix

- WHEN the command is run
- THEN it shows every host with the emulator modes to evaluate on it, and the performance areas

#### Scenario: Check that the matrix is complete

- WHEN the command is asked to check and the matrix is complete
- THEN it says so and reports success

#### Scenario: The matrix is not complete

- WHEN the command is asked to check and something is missing from the matrix
- THEN it names what is missing and reports failure
