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

### Requirement: Measure a host with one command

The project MUST provide one command that takes a host's measurements, so that a host is measured the same way each time and by whoever does it. Run on a host, the command MUST, in this order: time the build of each of the host's targets, each alone, from a container engine that holds no image of the project and no kept build step, and then of all of them one after the other; take the disk space of each built target and of every place the host installation uses; run every implemented performance workload in every emulator mode, each VM guest CPU architecture included, the number of times the measurement procedures ask for, and record each run; and run the verification checks. Only when asked to, it MUST first remove the host installation with the setup script's uninstall option, with the downloads the installation's tools kept, and time the setup script installing it again. The measurements of a host that the report states MUST be taken with this command.

Before the command removes anything it MUST say what it removes, and ask, unless it is told not to ask; it MUST offer a run that only says what it would do. It MUST let the stages be chosen, and the simulated ARM targets be left out on a host that is not set up for them. A step that fails MUST NOT stop the steps after it: the command names what failed and reports failure at its end. It MUST keep the disk space and time values in a record per host and machine, each with when it was taken, the command that took it, and the source revision and image definition it was taken of. A value that was not taken MUST NOT be in the record, and is reported as not measured.

#### Scenario: Measure a host

- WHEN the command is run on a host that is set up, and its question is answered with yes
- THEN the targets are built and timed, their sizes and the installation's are taken, the performance workloads are run and recorded in every mode, the verification checks are run, and the host's record has the values

#### Scenario: Measure the installation only on request

- WHEN the command is run without being asked to measure the installation
- THEN it removes no host software and does not run the setup script

#### Scenario: Say what is removed first

- WHEN the command would remove images, kept build steps or the host installation
- THEN it names them and asks before it removes anything, unless it was told not to ask

#### Scenario: Say what would be done

- WHEN the command is asked only to say what it would do
- THEN it names each command it would run, and runs, removes and records nothing

#### Scenario: Go on after a failed step

- WHEN a build, a workload run or another step fails
- THEN the steps after it still run, the record says that the step failed, and the command reports failure

#### Scenario: Keep the values of different machines apart

- WHEN two machines with the same host operating system and CPU architecture are measured
- THEN each has a record of its own
