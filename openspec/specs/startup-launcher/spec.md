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

### Requirement: Show the command line of the chosen settings

The settings window MUST show the launcher command line that starts the emulator with the settings chosen in the window, and MUST keep it current as the settings change.

#### Scenario: Show the command line

- WHEN the settings window is shown
- THEN it shows the command line that starts the emulator with the settings as they are

#### Scenario: Change a setting

- WHEN the user changes a setting in the window
- THEN the command line shown changes with it

### Requirement: Show what the launcher finds on the host

The startup launcher MUST offer a command that shows what it finds on the host, without starting the emulator: the host's operating system, CPU, memory, and GPUs; the VM emulator for each guest CPU mode, with its version; the accelerator that host-native VM mode uses; the container runtime with its version and the CPUs and memory of its engine; whether host graphics acceleration is available in VM mode and in container mode, with the reason where it is not; how the target's sound is played on the host; whether the launcher's windows can be shown; and for each target image whether it is built and current. The command MUST name each host dependency it finds missing, MUST then point to the setup script, and MUST report failure.

#### Scenario: Show the host

- WHEN the command is run on a host
- THEN it shows the host's hardware and operating system, the VM emulators, the accelerator, the container runtime, the sound output, the windows, and the state of each target image

#### Scenario: Say why graphics are emulated

- WHEN host graphics acceleration is not available in an emulator mode on the host
- THEN the command says that graphics are emulated in that mode, and why

#### Scenario: A host dependency is missing

- WHEN the command finds a host dependency missing
- THEN it names that dependency, points to the setup script, and reports failure

#### Scenario: Show the state of the target images

- WHEN the command is run
- THEN it says for each target image whether it is not built, current, or out of date

### Requirement: Choose the root file system of the target

The startup launcher MUST accept a setting that names the root file system the target starts from: the Debian root file system of the evaluation, which is the default, or an RDK-E root file system. Without the setting, and with it naming Debian, the launcher MUST behave as it does without the setting existing. The settings window MUST offer the setting like every other.

The RDK-E root file system is experimental and is not part of the evaluation matrix: no result is recorded from it, and no performance or verification requirement applies to what runs in it. The launcher does not build it. Asked for it, the launcher MUST start an ARM64 virtual machine from the kernel and the root file system it finds in a directory of the checkout, or in one that an emulator option names, give the machine a display, and leave the target to start its own software, with the target's console on the launcher's output. The launcher MUST NOT start anything, and MUST say why, when the RDK-E root file system is asked for together with something only the Debian one provides: container mode, a workload other than the prompt, a driver feature, a capture directory, a RedRat profile, a rebuild, recording or repeating; with a guest CPU architecture other than ARM64; or when the directory has no kernel or no root file system, in which case it names the directory and says where building the image is described. The build command and the command that shows what the launcher finds on the host MUST say whether an RDK-E image is there, and its absence MUST NOT count as a missing host dependency.

#### Scenario: Start from the Debian root file system by default

- WHEN the emulator is started without the setting
- THEN the target starts from the Debian root file system, as it did before the setting existed

#### Scenario: Start from an RDK-E root file system

- WHEN the emulator is started in VM mode with the setting naming RDK-E, and the directory has a kernel and a root file system
- THEN an ARM64 virtual machine boots that kernel with that root file system, the target's own init runs, and its console is shown

#### Scenario: Refuse what the RDK-E root file system does not provide

- WHEN the RDK-E root file system is asked for with container mode, a workload, a driver feature, or another setting that only the Debian root file system provides
- THEN the launcher starts nothing and says why

#### Scenario: No RDK-E image

- WHEN the RDK-E root file system is asked for and the directory has no kernel or no root file system
- THEN the launcher starts nothing, names the directory, and says where building the image is described

#### Scenario: Say whether an RDK-E image is there

- WHEN the command that shows what the launcher finds on the host is run
- THEN it says whether an RDK-E image is there, and does not report failure because none is
