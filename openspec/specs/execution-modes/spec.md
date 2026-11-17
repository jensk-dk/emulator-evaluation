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

### Requirement: Build the simulated target OS container environment

The project MUST provide a Dockerfile or equivalent container build definition that constructs the simulated target OS environment, including its services, libraries, and other required runtime components.

#### Scenario: Build the container environment

- WHEN the container build definition is used
- THEN it produces an image containing the simulated target OS environment and its required services, libraries, and runtime components

### Requirement: Remove what earlier builds left in the container engine

After it has built a target image, the launcher MUST remove from the container engine the project's target images of other versions of the image definition, and the project's target images that a later build of the same version has replaced, so that repeated builds do not keep adding to the disk space the engine takes. It MUST NOT remove the target images of the current version, and MUST NOT remove an image that is not one of the project's target images. It MUST also remove the build steps that the engine keeps and that no build has used for 48 hours. The engine keeps build steps for everything it builds, so such steps of other projects are removed as well. The launcher MUST say what it removed. Its build command MUST offer an option that leaves all of it in place. Something that cannot be removed MUST NOT stop the build or make it fail.

#### Scenario: Build a new version of the image definition

- WHEN a target image has been built from a new version of the image definition
- THEN the project's target images of earlier versions are removed from the container engine, and the launcher says what it removed

#### Scenario: Build the same version again

- WHEN a target image is built again from the same version of the image definition
- THEN the image that the new build replaced is removed from the container engine

#### Scenario: Keep what earlier builds left

- WHEN the build is run with the option that keeps earlier builds
- THEN nothing is removed from the container engine

#### Scenario: Leave other images in place

- WHEN the container engine holds images that are not the project's target images
- THEN a build leaves those images in place

#### Scenario: Something cannot be removed

- WHEN an image of an earlier build cannot be removed
- THEN it stays, and the build still succeeds

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

### Requirement: Offer the simulated ARM targets where the host is set up for them

The ARM64 and ARM32 guest CPU modes need host software that the setup script installs only on request. The launcher MUST NOT build a target image for one of these modes unless that mode is asked for by name: by starting the emulator in it, by building its image, or by a verification check for it. On a host that lacks what such a mode needs, the launcher MUST NOT start a build or a VM for it; it MUST say that the simulated ARM targets are not set up on this host and name the setup option that sets them up. The command that shows what the launcher finds on the host MUST say whether each of the two modes is set up, and MUST NOT name what is missing for them as a missing host dependency. A verification check for one of these modes MUST end as could not be run on such a host, with that reason. Host-native VM mode and container mode MUST work on a host that is not set up for the simulated ARM targets.

#### Scenario: Start an ARM target on a host that is not set up for it

- WHEN the emulator is started in the ARM64 or ARM32 guest CPU mode on a host that lacks what the mode needs
- THEN the launcher starts neither a build nor a VM, says that the simulated ARM targets are not set up, and names the setup option

#### Scenario: Start an ARM target on a host that is set up for it

- WHEN the emulator is started in the ARM64 or ARM32 guest CPU mode on a host that has what the mode needs
- THEN the launcher builds the mode's target image if it is not built, and starts the VM

#### Scenario: Build without naming an ARM target

- WHEN the launcher is asked to build without naming a guest CPU architecture
- THEN it builds no ARM target image that is not the host's own

#### Scenario: Show whether the ARM targets are set up

- WHEN the command that shows what the launcher finds on the host is run on a host that is not set up for the simulated ARM targets
- THEN it says so for each of the two modes, names the setup option, and does not report failure for that

#### Scenario: Run the verification checks on a host that is not set up

- WHEN the verification checks for an ARM guest CPU mode are run on a host that lacks what the mode needs
- THEN each ends as could not be run on this host, with the reason

#### Scenario: Use the other modes without the ARM targets

- WHEN a host is set up without the option for the simulated ARM targets
- THEN container mode and host-native VM mode work on it

### Requirement: Offer a simulated x86-64 guest as a diagnostic

Beside the host-native, ARM32, and ARM64 guest CPU modes, the VM-based runtime MAY offer a guest CPU mode that simulates an x86-64 target CPU, so that the x86-64 target image can be tried on a host of another CPU architecture. Where it is offered it is a diagnostic: it MUST NOT be one of the combinations of the evaluation matrix, and the performance evaluation MUST NOT require results for it.

#### Scenario: Simulate an x86-64 target

- WHEN the VM-based runtime is started in the x86-64 guest CPU mode
- THEN it simulates an x86-64 target CPU and runs the x86-64 target image

#### Scenario: Keep the diagnostic out of the evaluation matrix

- WHEN the combinations of the evaluation matrix are listed
- THEN the x86-64 guest CPU mode is not among them

### Requirement: Driver feature strategies in both execution modes

Both container-based and VM-based modes MUST support all of the following strategies for target OS driver features: emulating the target OS driver, using a mocked driver, and mapping the feature to a host-side process that reroutes its functionality to the host OS. A driver feature MAY use one strategy or combine strategies.

#### Scenario: Provide driver features in container mode

- WHEN a target OS driver feature is needed in container-based mode
- THEN it can be provided by an emulated driver, a mocked driver, or a host-side process that reroutes the feature to the host OS

#### Scenario: Provide driver features in VM mode

- WHEN a target OS driver feature is needed in VM-based mode
- THEN it can be provided by an emulated driver, a mocked driver, or a host-side process that reroutes the feature to the host OS

### Requirement: Leave a driver feature out

Beside the three strategies, the startup launcher MUST accept for each target OS driver feature a setting that leaves the feature out, in container-based and in VM-based mode. The target then has no such driver feature, and a workload that would otherwise turn the feature on MUST NOT turn it on.

#### Scenario: Leave a feature out

- WHEN a driver feature is set to be left out
- THEN the target OS runs without that driver feature

#### Scenario: A workload that uses the feature

- WHEN a driver feature is set to be left out and the workload is one that turns the feature on by itself
- THEN the feature stays out
