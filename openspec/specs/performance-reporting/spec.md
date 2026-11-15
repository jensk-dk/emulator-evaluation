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

### Requirement: Report disk space and time costs

The presentation MUST state, for every evaluated host, the disk space that the host installation takes and the disk space that each target takes individually: the container image, and the VM image of each guest CPU architecture. It MUST also state the time that installing on the host took, the time that building each target took, and the time that running the performance evaluation took. Each value MUST be an actual measurement from that host. A value that has not been measured MUST be identified as unavailable and MUST NOT be presented as measured or replaced with an invented estimate.

#### Scenario: Report the disk space of the host installation

- WHEN results are reported for an evaluated host
- THEN the presentation states the disk space that the host installation takes on that host

#### Scenario: Report the disk space of each target

- WHEN results are reported for an evaluated host
- THEN the presentation states the disk space that each target takes on that host, one value per target

#### Scenario: Report installation time

- WHEN results are reported for an evaluated host
- THEN the presentation states the time that installing on that host took

#### Scenario: Report build time

- WHEN results are reported for an evaluated host
- THEN the presentation states the time that building each target on that host took

#### Scenario: Report performance evaluation time

- WHEN results are reported for an evaluated combination
- THEN the presentation states the time that running the performance evaluation took for that combination

#### Scenario: Identify unavailable disk space and time values

- WHEN a disk space or time value has not been measured on a host
- THEN the presentation marks that value as unavailable
