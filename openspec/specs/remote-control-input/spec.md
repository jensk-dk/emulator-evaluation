# Remote Control Input Specification

## Purpose

Define how a user gives the emulator the key input of a remote control, and which keys are supported.

## Requirements

### Requirement: Deliver remote control key input to the target

The emulator MUST deliver remote control key presses to the target OS, in container mode and in VM mode. It MUST join mapped host keyboard keys and the on-screen remote control whenever the launcher's display window is active. Selecting a learned RedRat profile MUST add IR input to those sources, not replace them. Every source MUST deliver the same target key.

#### Scenario: Deliver a key in container mode

- WHEN a user presses a supported remote control key through an input source while the emulator runs in container mode
- THEN the target OS receives that key

#### Scenario: Deliver a key in VM mode

- WHEN a user presses a supported remote control key through an input source while the emulator runs in VM mode
- THEN the target OS receives that key

#### Scenario: Deliver the same key from joined input sources

- WHEN the same remote control key is pressed through the keyboard, on-screen remote, or selected RedRat profile
- THEN the target OS receives the same key each time

### Requirement: Support all HbbTV input keys

The host keyboard and on-screen remote MUST support every button that the HbbTV specification lists for user input (ETSI TS 102 796 V1.7.1, Table 12): the colour keys red, green, yellow, and blue; the arrow keys up, down, left, and right; ENTER (OK); BACK; the number keys 0 to 9; play, pause, combined play/pause, and stop; fast forward and rewind; record; and the buttons that an HbbTV terminal handles itself: TEXT, the two program selection buttons (P+ and P-), WEBTV, and EXIT. A learned RedRat profile MAY omit keys that the physical remote lacks; these keys MUST remain available through the other input sources.

#### Scenario: Press a navigation key

- WHEN a user presses an arrow key, ENTER, or BACK through an input source
- THEN the target OS receives that key

#### Scenario: Press a colour key

- WHEN a user presses the red, green, yellow, or blue key through an input source
- THEN the target OS receives that key

#### Scenario: Press a number key

- WHEN a user presses one of the number keys 0 to 9 through an input source
- THEN the target OS receives that key

#### Scenario: Press a playback key

- WHEN a user presses play, pause, play/pause, stop, fast forward, rewind, or record through an input source
- THEN the target OS receives that key

#### Scenario: Press a button that an HbbTV terminal handles itself

- WHEN a user presses TEXT, P+, P-, WEBTV, or EXIT through an input source
- THEN the target OS receives that key

#### Scenario: Cover the whole key set from every input source

- WHEN any input source is used
- THEN every key of the set can be pressed through it

### Requirement: Map host keyboard keys to remote control keys

The emulator MUST map keys of the host keyboard to remote control keys while the launcher's display window has the input focus, whenever that window is active. The arrow keys of the host keyboard MUST map to the arrow keys of the remote control and the Enter key to ENTER (OK), and every supported remote control key MUST have a host key.

#### Scenario: Navigate with the arrow keys

- WHEN the emulator's window has the input focus and the user presses an arrow key of the host keyboard
- THEN the target OS receives the remote control's arrow key of that direction

#### Scenario: Select with the Enter key

- WHEN the emulator's window has the input focus and the user presses the Enter key of the host keyboard
- THEN the target OS receives the remote control's ENTER (OK) key

#### Scenario: Reach every remote control key from the host keyboard

- WHEN a launcher display window is in use
- THEN every supported remote control key has a host key that delivers it

#### Scenario: Map keys only while the emulator's window is focused

- WHEN the emulator's window does not have the input focus
- THEN host keyboard keys are not delivered to the target as remote control keys

### Requirement: Provide an on-screen remote control

The emulator MUST offer a graphical remote control in a window of its own: a picture of a TV remote control whose buttons the user clicks with the mouse. It MUST have a button for every supported remote control key, and a click on a button MUST deliver that key to the target. The on-screen remote window MUST start hidden and MUST be toggleable with the display toolbar button or Ctrl+Alt+R hotkey. Host keyboard mapping MUST remain active while the on-screen remote is shown.

#### Scenario: Show the on-screen remote control

- WHEN the display window opens
- THEN the on-screen remote control is hidden until toggled

#### Scenario: Click a button

- WHEN the user clicks a button of the on-screen remote control with the mouse
- THEN the target OS receives that button's key

#### Scenario: Offer a button for every key

- WHEN the on-screen remote control is shown
- THEN it has a button for every supported remote control key

#### Scenario: Use the host keyboard beside the on-screen remote control

- WHEN the on-screen remote control is shown, the emulator's window has the input focus, and the user presses a mapped host key
- THEN the target OS receives that key's remote control key

### Requirement: Accept RedRat IR input

The emulator MUST accept remote control input as infrared signals received by a RedRat IR device connected to the host when a learned profile is selected, and MUST deliver the key that a received signal stands for to the target alongside keyboard and on-screen input.

Learning and playback MUST automatically use the first detected receiver when no receiver id is supplied, including when multiple receivers are connected. An explicit receiver id MUST override this default, and an unavailable explicit id MUST fail rather than select another receiver. The settings window MUST show the automatically detected receiver.

#### Scenario: Press a key on a remote control

- WHEN a RedRat profile is selected and the device receives the infrared signal of a supported remote control key
- THEN the target OS receives that key

### Requirement: Select and learn remote profiles

The emulator MUST support multiple learned remote profiles stored in the repository, with one selected per run. The settings window MUST offer a Create new profile action beside the profile selector; creating a profile MUST save and select it without starting the emulator. The `emu config redrat` command MUST run the same guided learning task independently of an emulator run. The selector MUST list existing profiles only. The initial repository MUST contain no fabricated learned profiles. Guided learning MUST offer a Skip key button for keys absent from the physical remote. Skipping MUST discard partial captures for that key and omit its mapping from the saved profile. Saving MUST be available after every supported key has been learned or skipped, including when all keys are skipped. Cancelled learning MUST save nothing and learning a new remote MUST NOT overwrite an existing profile.

#### Scenario: Create a profile from the settings window

- WHEN the user creates a profile beside the selector
- THEN guided learning captures the remote's buttons, saves a named profile only after every supported key is learned or skipped and the user confirms, and returns to settings without starting the emulator

#### Scenario: Skip a missing physical button

- WHEN the user selects Skip key during learning, including after a partial capture
- THEN learning advances without saving an IR mapping for that key
- AND the key remains available on the virtual remote and host keyboard
- AND Relearn previous key allows returning to the skipped key

#### Scenario: Reject ambiguous captures while learning

- WHEN a candidate capture conflicts with a different learned key under the SDK timing or toggle rules used during playback
- THEN learning rejects that capture without advancing or changing the accepted mappings and names the conflicting keys
- AND the user can retry, relearn the previous key, or skip the current key
- AND saving validates the complete mapping with the same SDK rules and leaves an invalid profile unsaved

#### Scenario: Distinguish short-pulse physical buttons

- WHEN different physical buttons produce distinct short/long pulse patterns with normal capture timing variation
- THEN decoder construction preserves the distinct patterns instead of merging them into a false ambiguity
- AND learning accepts both mappings and playback identifies each button correctly
- AND genuine cross-key signal conflicts remain rejected

#### Scenario: Configure a RedRat profile independently

- WHEN the user runs `emu config redrat`
- THEN guided learning can save a profile without building or starting the emulator

#### Scenario: Reuse a learned remote

- WHEN the user selects a previously learned profile
- THEN received signals are mapped with that profile, not another saved remote's mapping

#### Scenario: Reject an existing ambiguous profile before starting a target

- WHEN a selected profile contains conflicting mappings under the SDK playback rules
- THEN the launcher reports the conflicting mappings before building or starting the target

#### Scenario: List newly saved profiles without restarting settings

- WHEN the user opens the profile dropdown after a profile has been saved
- THEN the dropdown reloads the saved profiles and includes the new profile without restarting the settings window
- AND refreshing preserves the current selection if that profile still exists

### Requirement: Gate infrared input by window focus

RedRat signals MUST be delivered only while the emulator display window is focused. Repeated IR frames MUST keep a key held rather than generate an independent click per frame. A held key MUST be released when its repeats cease, the window loses focus, or the receiver stops.

#### Scenario: Switch away while holding a key

- WHEN an IR key is held and the emulator window loses focus
- THEN the target receives a release and further IR frames are ignored while the window remains unfocused

### Requirement: Install support independently of attached hardware

Host setup MUST install RedRat support even if no receiver is detected. The settings window MUST offer RedRat profiles only when a receiver is detected and refresh detection while open. Keyboard and on-screen input MUST always remain available, whether or not a receiver is attached. Selecting a RedRat profile without a receiver MUST fail explicitly before building or starting the emulator.

#### Scenario: Set up without a receiver

- WHEN host setup completes without any RedRat connected
- THEN the SDK bridge and host USB prerequisites are installed and keyboard/on-screen input remain usable

#### Scenario: Connect a receiver

- WHEN a RedRat receiver is detected while the settings window is open
- THEN RedRat profiles become selectable as an additional input source

### Requirement: Provide a workload that shows the keys that arrive

The target OS image MUST provide a workload, selectable through the startup launcher like any other, that shows a picture on the emulator's display and reports each remote control key that a program on the target's display receives: its key code, its symbol in the target, and whether it was pressed or released. It MUST run in container mode and in VM mode, so that remote control input can be tried and checked in each.

#### Scenario: Report a key

- WHEN the workload runs and a remote control key is pressed and released through an input source
- THEN the workload reports that key's code and symbol, once as pressed and once as released

#### Scenario: Run in both modes

- WHEN the workload is selected in container mode or in VM mode
- THEN it shows its picture and reports the keys that arrive
