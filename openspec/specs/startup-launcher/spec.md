# Startup Launcher Specification

## Purpose

Define the cross-platform entry point for launching the emulator and selecting target OS workloads.

## Requirements

### Requirement: Launch from all supported host operating systems

The project MUST provide a startup launcher that can launch the emulator on Linux, macOS, and Windows.

#### Scenario: Launch on Linux

- WHEN the startup launcher is invoked on Linux
- THEN it can launch the emulator

#### Scenario: Launch on macOS

- WHEN the startup launcher is invoked on macOS
- THEN it can launch the emulator

#### Scenario: Launch on Windows

- WHEN the startup launcher is invoked on Windows
- THEN it can launch the emulator

### Requirement: Configure emulator launch parameters

The startup launcher MUST accept parameters to select the emulator mode, provide emulator options, and choose the target OS workload to run.

#### Scenario: Select mode and options

- WHEN a user invokes the launcher with a supported emulator mode and options
- THEN it launches the emulator in that mode with those options

#### Scenario: Select a target OS workload

- WHEN a user selects a target OS workload
- THEN the emulator starts that workload, such as an interactive prompt, graphics demo, or benchmark suite

### Requirement: Show a settings window when started without parameters

When the startup launcher is started without any parameters, it MUST show a graphical window in which the user chooses the launch settings and starts the emulator. The window MUST offer the emulator mode (container or VM), the VM guest CPU mode (host-native, ARM32, or ARM64), the target OS workload, the display's window mode, the emulator options, and every other setting that the launcher accepts as a parameter. Starting the emulator from the window MUST have the same effect as invoking the launcher with the corresponding parameters. The window MUST be available on Linux, macOS, and Windows. When the launcher is started with parameters, it MUST act on them without showing the window.

#### Scenario: Start without parameters

- WHEN a user starts the launcher without any parameters
- THEN a graphical settings window appears, and the emulator is not started until the user starts it from the window

#### Scenario: Choose the mode and the VM guest CPU mode

- WHEN the settings window is shown
- THEN the user can choose container or VM mode, and for VM mode the host-native, ARM32, or ARM64 guest CPU mode

#### Scenario: Choose the workload and the window mode

- WHEN the settings window is shown
- THEN the user can choose the target OS workload and the display's window mode

#### Scenario: Set options and the other launcher settings

- WHEN the settings window is shown
- THEN the user can set the emulator options and every other setting that the launcher accepts as a parameter

#### Scenario: Start the emulator from the window

- WHEN a user starts the emulator from the settings window
- THEN the emulator launches as it would for the launcher invoked with the corresponding parameters

#### Scenario: Show the window on every supported host operating system

- WHEN the launcher is started without parameters on Linux, macOS, or Windows
- THEN the settings window appears on that host

#### Scenario: Start with parameters

- WHEN a user invokes the launcher with parameters
- THEN it acts on those parameters and does not show the settings window
