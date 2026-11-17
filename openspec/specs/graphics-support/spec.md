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

### Requirement: Offer full screen and the on-screen remote control from the toolbar

Beside the controls for muting audio and for 1:1 pixel-density scaling, the compact toolbar of windowed mode MUST have an icon control that switches to full-screen mode and, while remote control input is on, an icon control that shows or hides the on-screen remote control. The toolbar MUST NOT be shown in full-screen mode. The control for muting audio MUST be disabled for a run that plays no sound through the host.

#### Scenario: Switch to full screen from the toolbar

- WHEN the full-screen icon is activated
- THEN the emulator display uses the full screen, without the toolbar

#### Scenario: Show the on-screen remote control from the toolbar

- WHEN remote control input is on and the remote control icon is activated
- THEN the on-screen remote control is shown, or hidden if it was shown

#### Scenario: A run without sound

- WHEN the run plays no sound through the host
- THEN the control for muting audio cannot be activated

### Requirement: Provide hotkeys for the window's controls

While the emulator's window has the input focus, the emulator MUST provide hotkeys for what the toolbar offers: Ctrl+Alt+F and F11 switch between windowed and full-screen modes, Ctrl+Alt+M mutes and unmutes audio, Ctrl+Alt+1 restores 1:1 pixel-density scaling, and Ctrl+Alt+R shows or hides the on-screen remote control. On a macOS host the Command key MUST work in place of the Control key. A hotkey MUST NOT be delivered to the target as a remote control key.

#### Scenario: Switch display mode with either hotkey

- WHEN Ctrl+Alt+F or F11 is pressed
- THEN the emulator switches between windowed and full-screen modes

#### Scenario: Mute with a hotkey

- WHEN Ctrl+Alt+M is pressed in a run that plays sound through the host
- THEN audio output is muted, or unmuted if it was already muted

#### Scenario: Restore 1:1 scaling with a hotkey

- WHEN Ctrl+Alt+1 is pressed
- THEN the display uses one guest pixel per host display pixel

#### Scenario: Show the on-screen remote control with a hotkey

- WHEN remote control input is on and Ctrl+Alt+R is pressed
- THEN the on-screen remote control is shown, or hidden if it was shown

#### Scenario: Keep hotkeys from the target

- WHEN a hotkey is pressed
- THEN the target OS receives no remote control key for it

### Requirement: Capture the emulator's display

The startup launcher MUST accept a setting that names a directory for captures of the emulator's display. With it, the emulator MUST save a picture of the display, as the target has rendered it at the selected resolution, each time a workload reports that a finished frame is on the display. This MUST work in container mode and in VM mode. Where a display cannot be captured, the emulator MUST say so and why, and MUST NOT save a picture that is not the display's. Where a capture holds only a part of the display, the emulator MUST say so.

#### Scenario: Capture in container mode

- WHEN a workload reports a finished frame in container mode and a directory for captures is set
- THEN a picture of the display is saved to that directory

#### Scenario: Capture in VM mode

- WHEN a workload reports a finished frame in VM mode and a directory for captures is set
- THEN a picture of the display is saved to that directory

#### Scenario: The display cannot be captured

- WHEN a directory for captures is set and the display cannot be captured
- THEN the emulator says so and why, and saves no picture

#### Scenario: A capture holds a part of the display

- WHEN a capture holds only a part of the display
- THEN the emulator says which part it holds
