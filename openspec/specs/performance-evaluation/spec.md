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