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

### Requirement: Support common display resolutions

The emulator MUST support 720p, 1080p, and 4K display resolutions.

#### Scenario: Display at 720p

- WHEN 720p resolution is selected
- THEN the emulator renders at 720p

#### Scenario: Display at 1080p

- WHEN 1080p resolution is selected
- THEN the emulator renders at 1080p

#### Scenario: Display at 4K

- WHEN 4K resolution is selected
- THEN the emulator renders at 4K

### Requirement: Support windowed and full-screen display modes

The emulator MUST support both windowed and full-screen display modes.

#### Scenario: Run windowed

- WHEN windowed mode is selected
- THEN the emulator display runs in a window

#### Scenario: Run full screen

- WHEN full-screen mode is selected
- THEN the emulator display uses the full screen

### Requirement: Toggle display mode with a hotkey

The emulator MUST provide a hotkey that switches between windowed and full-screen modes while it is running.

#### Scenario: Switch display mode with a hotkey

- WHEN the display-mode hotkey is pressed
- THEN the emulator switches between windowed and full-screen modes

### Requirement: Scale the display in windowed mode

The emulator MUST allow the rendered display to be scaled in windowed mode as the window size changes.

#### Scenario: Resize the window

- WHEN the user resizes the emulator window
- THEN the rendered display scales within the window

### Requirement: Provide a compact window toolbar

Windowed mode MUST provide a compact toolbar with icon controls for muting audio and restoring 1:1 pixel-density scaling.

#### Scenario: Mute audio from the toolbar

- WHEN the audio mute icon is activated
- THEN audio output is muted, or unmuted if it was already muted

#### Scenario: Restore 1:1 pixel-density scaling

- WHEN the 1:1 scaling icon is activated
- THEN the display uses one guest pixel per host display pixel