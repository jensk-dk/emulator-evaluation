# Graphics Support Specification

## Purpose

Define the graphics technologies supported by the emulator and how graphics functionality is provided.

## Requirements

### Requirement: Supported graphics technologies

The emulator MUST support workloads that use Wayland, Flutter, OpenGL ES, and Vulkan.

#### Scenario: Run a Wayland workload

- WHEN a workload uses Wayland
- THEN it can run in the emulator

#### Scenario: Run a Flutter workload

- WHEN a workload uses Flutter
- THEN it can run in the emulator

#### Scenario: Run an OpenGL ES workload

- WHEN a workload uses OpenGL ES
- THEN it can run in the emulator

#### Scenario: Run a Vulkan workload

- WHEN a workload uses Vulkan
- THEN it can run in the emulator

### Requirement: Graphics execution provider

The emulator MUST provide graphics functionality through emulation or mapping to host OS graphics acceleration. When compatible host acceleration is available, the emulator SHOULD map graphics functionality to it. Emulation MUST remain available as an alternative.

#### Scenario: Use compatible host graphics acceleration

- WHEN host OS graphics acceleration is available and compatible with the workload
- THEN the emulator prefers mapping graphics functionality to that acceleration

#### Scenario: Emulate graphics functionality

- WHEN compatible host OS graphics acceleration is unavailable
- THEN the emulator can provide graphics functionality through emulation