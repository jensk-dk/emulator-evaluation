# Host Setup Specification

## Purpose

Define the setup script that prepares a development host to run the emulator, and that removes again what it installed there.

## Requirements

### Requirement: Provide a setup script for all supported host operating systems

The project MUST provide a setup script for each supported host operating system: Linux, macOS, and Windows.

#### Scenario: Run setup on Linux

- WHEN a developer prepares a Linux host
- THEN a setup script is available that runs on that host

#### Scenario: Run setup on macOS

- WHEN a developer prepares a macOS host
- THEN a setup script is available that runs on that host

#### Scenario: Run setup on Windows

- WHEN a developer prepares a Windows host
- THEN a setup script is available that runs on that host

### Requirement: Check and install host dependencies

The setup script MUST check for every host dependency the emulator requires and MUST install any that are missing.

#### Scenario: Check host dependencies

- WHEN the setup script is run on a supported host
- THEN it checks whether each required host dependency is present

#### Scenario: Install missing host dependencies

- WHEN the setup script finds a required host dependency missing
- THEN it installs that dependency

#### Scenario: Dependencies already present

- WHEN the setup script is run on a host where every required dependency is present
- THEN it completes without installing anything

### Requirement: Ask before installing, and check without installing

Before it installs anything, the setup script MUST say what is missing and ask for confirmation, unless the developer has told it not to ask. Without confirmation it MUST install nothing, and MUST report failure when a required host dependency is missing. The setup script MUST also offer a way to check only: it then installs nothing, names what is missing, and reports failure when a required host dependency is missing.

#### Scenario: Ask before installing

- WHEN the setup script finds a required host dependency missing and was not told not to ask
- THEN it names what is missing and asks for confirmation before it installs anything

#### Scenario: Confirmation is not given

- WHEN a required host dependency is missing and the developer does not confirm
- THEN the setup script installs nothing and reports failure

#### Scenario: Install without asking

- WHEN the developer has told the setup script not to ask
- THEN it installs what is missing without asking

#### Scenario: Check only, with a dependency missing

- WHEN the setup script is asked to check only and a required host dependency is missing
- THEN it names that dependency, installs nothing, and reports failure

#### Scenario: Check only, with every dependency present

- WHEN the setup script is asked to check only and every required host dependency is present
- THEN it installs nothing and reports success

### Requirement: Install optional extras without requiring them

An optional extra adds to what the emulator does on a host and is not needed to run it. On a Linux host the optional extras are the VM emulator's modules for host graphics acceleration, without which graphics are emulated in VM mode, and a program that plays the target's sound, without which the sound is not heard on the host. The setup script MUST report a missing optional extra as optional and MUST NOT report it as a missing host dependency: a check finds every host dependency present when only optional extras are missing. When it installs, the setup script MUST install the optional extras as well, where the host's package manager offers them, and MUST record them like everything else it installs. When an optional extra cannot be installed, the setup script MUST say what the host then goes without.

#### Scenario: Only an optional extra is missing

- WHEN the setup script checks a host on which only optional extras are missing
- THEN it names them as optional and reports that every host dependency is present

#### Scenario: Install an optional extra

- WHEN the setup script installs on a host where an optional extra is missing and the package manager offers it
- THEN it installs that extra and its record names it

#### Scenario: An optional extra cannot be installed

- WHEN an optional extra cannot be installed
- THEN the setup script says what the host goes without

### Requirement: Use the package manager of the Linux host

On a Linux host the setup script MUST install host dependencies with the host's package manager, and MUST support apt, dnf, zypper, and pacman, for installing and for the uninstall option alike. On a Linux host that has none of these it MUST name the host dependencies that the developer has to install, and MUST report failure. Which Linux distributions the emulator has to run on is defined by the host platform support specification, not by this requirement.

#### Scenario: Install with the host's package manager

- WHEN the setup script finds a host dependency missing on a Linux host that has apt, dnf, zypper, or pacman
- THEN it installs that dependency with that package manager

#### Scenario: Uninstall with the host's package manager

- WHEN the uninstall option is given on such a host
- THEN the setup script removes the packages its record names with that package manager

#### Scenario: No supported package manager

- WHEN the setup script finds host dependencies missing on a Linux host that has none of these package managers
- THEN it names the host dependencies to install and reports failure

### Requirement: Set up the simulated ARM targets only on request

The ARM64 and ARM32 guest CPU modes run on a simulated CPU, which is slow, and not every graphics technology runs in them. What only these two modes need on a host is therefore not a host dependency: the system emulators for ARM guests, where they are separate from the one for the host's own CPU architecture, and the emulation of ARM programs in the container engine, which building the ARM target images needs. The setup script MUST install this only when the developer asks for it with an option of the script. Without that option it MUST NOT check for it, MUST NOT install it, and MUST NOT report it as a missing host dependency; it MUST say that the simulated ARM targets are not set up by default and name the option. With the option it MUST check for it, install what is missing of it, record what it installs like everything else, and report failure when something of it is still missing afterwards. The setup script MUST NOT build a target image, with or without the option.

#### Scenario: Run setup without the option

- WHEN the setup script is run without the option for the simulated ARM targets
- THEN it installs nothing that only those targets need, does not report any of it as missing, and names the option

#### Scenario: Run setup with the option

- WHEN the setup script is run with the option on a host that lacks what the simulated ARM targets need
- THEN it installs that as well, and its record names what it installed

#### Scenario: Check with the option

- WHEN the setup script is asked to check only, with the option, on a host that lacks what the simulated ARM targets need
- THEN it names what is missing of it, installs nothing, and reports failure

#### Scenario: The host has it already

- WHEN the setup script is run without the option on a host that has what the simulated ARM targets need
- THEN it leaves that in place

#### Scenario: Something for the ARM targets cannot be installed

- WHEN the option is given and something that the simulated ARM targets need cannot be installed
- THEN the setup script reports the failure

#### Scenario: Uninstall what was installed for the ARM targets

- WHEN the uninstall option is given on a host where the setup script installed something for the simulated ARM targets
- THEN it lists and removes that with everything else its record names

### Requirement: Install experimental host software only on request

Experimental host software adds a capability to the emulator on a host and is not a host dependency. The setup script MUST install experimental host software only when the developer asks for it with an option of the script, and MUST NOT report it as a missing host dependency. On a macOS host with an ARM64 CPU, the setup script MUST offer such an option for a build of the VM emulator that maps OpenGL ES graphics in VM mode to host OS graphics acceleration.

#### Scenario: Install the experimental VM emulator build on request

- WHEN the setup script is run with the experimental option on a macOS host with an ARM64 CPU
- THEN it installs the experimental VM emulator build

#### Scenario: Run setup without the experimental option

- WHEN the setup script is run without the experimental option
- THEN it installs no experimental host software and does not report any as a missing host dependency

#### Scenario: Experimental option on a host that has none

- WHEN the experimental option is given on a host for which the setup script offers no experimental host software
- THEN the setup script installs nothing

#### Scenario: Experimental host software cannot be installed

- WHEN the experimental option is given and the experimental host software cannot be installed
- THEN the setup script reports the failure

### Requirement: Record what the setup script installs

The setup script MUST keep a record on the host of what it installs or creates there. The record MUST name only what was not present on the host before the script installed or created it.

#### Scenario: Record an installed dependency

- WHEN the setup script installs a host dependency that was not present on the host
- THEN its record on that host names that dependency

#### Scenario: Leave out what was already present

- WHEN a host dependency is present on the host before the setup script runs
- THEN the record does not name that dependency

### Requirement: Remove what the setup script installed

The setup script MUST offer an uninstall option that removes what its record names, experimental host software included, together with the dependencies installed with those things that nothing else on the host needs. It MUST NOT remove anything the script did not install, and MUST NOT remove anything in the project's own directory. A package manager that the setup script installed is treated differently: everything installed with that package manager counts as installed for the project, so the uninstall option MUST remove that package manager together with every package installed with it. A package manager that was on the host before stays, and of its packages only those the record names go. Before removing anything, the script MUST list what it will remove, say where removing a thing also deletes data kept in it, and ask for confirmation unless the developer has told it not to ask. It MUST offer a way to list what the uninstall option would remove without removing anything. The script MAY leave in place a system-wide component or setting that other software on the host can depend on; it MUST then name that component or setting and show how to remove it.

#### Scenario: Uninstall what setup installed

- WHEN the setup script is run with the uninstall option on a host where it installed host dependencies
- THEN it lists what its record names, asks for confirmation, and removes those things

#### Scenario: List without removing

- WHEN the developer asks only for the list of what the uninstall option would remove
- THEN the setup script shows that list and removes nothing

#### Scenario: Keep what setup did not install

- WHEN a host dependency was present on the host before the setup script ran
- THEN the uninstall option leaves that dependency in place

#### Scenario: Remove a package manager that setup installed

- WHEN the record names a package manager that the setup script installed
- THEN the uninstall option lists that package manager with the packages installed with it, and removes it with all of them, including packages installed with it after setup

#### Scenario: Keep a package manager that was present before setup

- WHEN the setup script installed packages with a package manager that was on the host before
- THEN the uninstall option leaves that package manager in place and removes only the packages the record names

#### Scenario: Removal deletes data

- WHEN removing something the record names also deletes data kept in it
- THEN the list says so before the setup script asks for confirmation

#### Scenario: Nothing recorded

- WHEN the uninstall option is given on a host where the setup script has recorded nothing
- THEN the setup script reports that there is nothing to remove and removes nothing

#### Scenario: Leave a system-wide component in place

- WHEN the record names a system-wide component or setting that the setup script leaves in place
- THEN the setup script names it and shows how to remove it

#### Scenario: Something recorded cannot be removed

- WHEN the uninstall option cannot remove something the record names
- THEN the setup script reports that, keeps it in the record, and reports failure
