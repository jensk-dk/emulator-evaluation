# Execution Modes Specification

## Purpose

Define the emulator's execution modes and how target OS driver features are provided.

## Requirements

### Requirement: Container-based execution

The emulator MUST provide a container-based execution mode for quick development and CI.

#### Scenario: Use container mode for development

- WHEN a developer uses the emulator for development
- THEN the emulator can run in container-based mode

#### Scenario: Use container mode in CI

- WHEN a CI job runs the emulator
- THEN the emulator can run in container-based mode

### Requirement: VM-based execution

The emulator MUST provide a VM-based execution mode that emulates the target OS kernel and drivers.

#### Scenario: Run the target OS in VM mode

- WHEN the emulator runs in VM-based mode
- THEN the target OS kernel and drivers are emulated

### Requirement: Select the VM guest CPU architecture

The VM-based runtime MUST support host-native machine-code execution using the host processor architecture. It MUST also support ARM32 and ARM64 guest architectures to simulate target CPU architectures.

#### Scenario: Run in host-native mode

- WHEN the VM-based runtime is started in host-native mode
- THEN it runs machine code for the host processor architecture

#### Scenario: Simulate an ARM32 target

- WHEN the VM-based runtime is started in ARM32 mode
- THEN it simulates a 32-bit ARM target CPU architecture

#### Scenario: Simulate an ARM64 target

- WHEN the VM-based runtime is started in ARM64 mode
- THEN it simulates a 64-bit ARM target CPU architecture

### Requirement: Driver feature strategies in both execution modes

Both container-based and VM-based modes MUST support all of the following strategies for target OS driver features: emulating the target OS driver, using a mocked driver, and mapping the feature to a host-side process that reroutes its functionality to the host OS. A driver feature MAY use one strategy or combine strategies.

#### Scenario: Provide driver features in container mode

- WHEN a target OS driver feature is needed in container-based mode
- THEN it can be provided by an emulated driver, a mocked driver, or a host-side process that reroutes the feature to the host OS

#### Scenario: Provide driver features in VM mode

- WHEN a target OS driver feature is needed in VM-based mode
- THEN it can be provided by an emulated driver, a mocked driver, or a host-side process that reroutes the feature to the host OS