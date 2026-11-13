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
