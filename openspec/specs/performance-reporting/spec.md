# Performance Reporting Specification

## Purpose

Define the comparative report required for emulator performance evaluations.

## Requirements

### Requirement: Produce a Slidev performance comparison

The evaluation MUST produce a Slidev presentation comparing the pros and cons of every evaluated host operating system, host CPU architecture, and emulator mode combination, including each VM guest CPU architecture. The presentation MUST include actual measured results for the required performance areas. Unavailable results MUST be identified as unavailable and MUST NOT be presented as measured or replaced with invented estimates.

#### Scenario: Compare evaluated combinations

- WHEN performance evaluation results are reported
- THEN the Slidev presentation compares the pros and cons of each evaluated combination

#### Scenario: Include measured performance results

- WHEN performance results are available for an evaluated combination
- THEN the presentation includes those measured results

#### Scenario: Identify unavailable results

- WHEN a combination or measurement has not been evaluated
- THEN the presentation marks the result as unavailable