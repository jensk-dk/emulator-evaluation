# Evaluation Environment Specification

## Purpose

Define the Linux client OS image and workload coverage needed to evaluate the emulator.

## Requirements

### Requirement: Provide a Linux client OS image for VM simulation

The project MUST provide a suitable Linux client OS image, either by creating it or obtaining it from an identified source, to simulate the target OS in VM-based mode.

#### Scenario: Prepare the VM simulation environment

- WHEN a VM-based evaluation is prepared
- THEN a Linux client OS image is available and can be booted by the VM runtime

### Requirement: Provide sufficient evaluation functionality and workloads

The client OS image and evaluation harness MUST provide sufficient functionality and workloads to perform the project's specified functional and performance evaluations.

#### Scenario: Evaluate CPU, memory, and I/O

- WHEN resource performance is evaluated
- THEN workloads exercise CPU performance, memory allocation, memory bandwidth, and I/O performance

#### Scenario: Evaluate graphics and media

- WHEN graphics or audio/video performance is evaluated
- THEN workloads exercise Wayland, Flutter, OpenGL ES, Vulkan, and the specified media containers, fragment injection, and audio/video codecs

### Requirement: Run web performance evaluations in WPE WebKit

The Linux client OS image MUST include WPE WebKit. The evaluation harness MUST support web performance workloads in WPE WebKit, including MSE playback.

#### Scenario: Launch WPE WebKit

- WHEN the Linux client OS image is started for web evaluation
- THEN WPE WebKit is available to run

#### Scenario: Evaluate MSE playback in WPE WebKit

- WHEN a web performance workload evaluates MSE playback
- THEN the workload runs in WPE WebKit and plays the media through MSE

#### Scenario: Evaluate driver strategies

- WHEN driver behavior is evaluated in container or VM mode
- THEN workloads can exercise emulated drivers, mocked drivers, and host-side driver-feature routing

### Requirement: Identify the evaluation environment

Each performance result MUST identify the Linux client OS image used by its source or build revision and image version, along with the evaluated host, CPU architecture, emulator mode, and workload version.

#### Scenario: Reproduce a performance result

- WHEN a performance result is reviewed
- THEN its image, workload, host, CPU architecture, and emulator mode can be identified