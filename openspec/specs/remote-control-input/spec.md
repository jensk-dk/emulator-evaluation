# Remote Control Input Specification

## Purpose

Define how a user gives the emulator the key input of a remote control, and which keys are supported.

## Requirements

### Requirement: Deliver remote control key input to the target

The emulator MUST deliver remote control key presses to the target OS, in container mode and in VM mode. It MUST provide three input modes for them: host keyboard keys mapped to remote control keys, an on-screen remote control, and RedRat IR input. A remote control key MUST reach the target as the same key whichever input mode it was pressed through.

#### Scenario: Deliver a key in container mode

- WHEN a user presses a supported remote control key through an input mode while the emulator runs in container mode
- THEN the target OS receives that key

#### Scenario: Deliver a key in VM mode

- WHEN a user presses a supported remote control key through an input mode while the emulator runs in VM mode
- THEN the target OS receives that key

#### Scenario: Deliver the same key from every input mode

- WHEN the same remote control key is pressed through different input modes
- THEN the target OS receives the same key each time

### Requirement: Support all HbbTV input keys

Every input mode MUST support every button that the HbbTV specification lists for user input (ETSI TS 102 796 V1.7.1, Table 12): the colour keys red, green, yellow, and blue; the arrow keys up, down, left, and right; ENTER (OK); BACK; the number keys 0 to 9; play, pause, combined play/pause, and stop; fast forward and rewind; record; and the buttons that an HbbTV terminal handles itself: TEXT, the two program selection buttons (P+ and P-), WEBTV, and EXIT.

#### Scenario: Press a navigation key

- WHEN a user presses an arrow key, ENTER, or BACK through an input mode
- THEN the target OS receives that key

#### Scenario: Press a colour key

- WHEN a user presses the red, green, yellow, or blue key through an input mode
- THEN the target OS receives that key

#### Scenario: Press a number key

- WHEN a user presses one of the number keys 0 to 9 through an input mode
- THEN the target OS receives that key

#### Scenario: Press a playback key

- WHEN a user presses play, pause, play/pause, stop, fast forward, rewind, or record through an input mode
- THEN the target OS receives that key

#### Scenario: Press a button that an HbbTV terminal handles itself

- WHEN a user presses TEXT, P+, P-, WEBTV, or EXIT through an input mode
- THEN the target OS receives that key

#### Scenario: Cover the whole key set in every input mode

- WHEN any one of the three input modes is in use
- THEN every key of the set can be pressed through it

### Requirement: Map host keyboard keys to remote control keys

The emulator MUST map keys of the host keyboard to remote control keys while the emulator's window has the input focus. The arrow keys of the host keyboard MUST map to the arrow keys of the remote control and the Enter key to ENTER (OK), and every supported remote control key MUST have a host key.

#### Scenario: Navigate with the arrow keys

- WHEN the emulator's window has the input focus and the user presses an arrow key of the host keyboard
- THEN the target OS receives the remote control's arrow key of that direction

#### Scenario: Select with the Enter key

- WHEN the emulator's window has the input focus and the user presses the Enter key of the host keyboard
- THEN the target OS receives the remote control's ENTER (OK) key

#### Scenario: Reach every remote control key from the host keyboard

- WHEN host keyboard mapping is in use
- THEN every supported remote control key has a host key that delivers it

#### Scenario: Map keys only while the emulator's window is focused

- WHEN the emulator's window does not have the input focus
- THEN host keyboard keys are not delivered to the target as remote control keys

### Requirement: Provide an on-screen remote control

The emulator MUST offer a graphical remote control in a window of its own: a picture of a TV remote control whose buttons the user clicks with the mouse. It MUST have a button for every supported remote control key, and a click on a button MUST deliver that key to the target. While the on-screen remote control is in use, the host keyboard mapping MUST still apply when the emulator's window has the input focus.

#### Scenario: Show the on-screen remote control

- WHEN the on-screen remote control input mode is selected
- THEN a window showing a TV remote control appears

#### Scenario: Click a button

- WHEN the user clicks a button of the on-screen remote control with the mouse
- THEN the target OS receives that button's key

#### Scenario: Offer a button for every key

- WHEN the on-screen remote control is shown
- THEN it has a button for every supported remote control key

#### Scenario: Use the host keyboard beside the on-screen remote control

- WHEN the on-screen remote control is in use, the emulator's window has the input focus, and the user presses a mapped host key
- THEN the target OS receives that key's remote control key

### Requirement: Accept RedRat IR input

The emulator MUST accept remote control input as infrared signals received by a RedRat IR device connected to the host, and MUST deliver the key that a received signal stands for to the target.

#### Scenario: Press a key on a remote control

- WHEN RedRat IR input is selected and the RedRat device receives the infrared signal of a supported remote control key
- THEN the target OS receives that key

### Requirement: Select the remote control input mode

The startup launcher MUST accept a setting that selects the remote control input mode: host keyboard mapping, the on-screen remote control, or RedRat IR input.

#### Scenario: Select host keyboard mapping

- WHEN a user selects host keyboard mapping
- THEN the emulator takes remote control input from mapped host keyboard keys

#### Scenario: Select the on-screen remote control

- WHEN a user selects the on-screen remote control
- THEN the emulator shows the on-screen remote control and takes remote control input from it and from mapped host keyboard keys

#### Scenario: Select RedRat IR input

- WHEN a user selects RedRat IR input
- THEN the emulator takes remote control input from a RedRat IR device

### Requirement: Provide a workload that shows the keys that arrive

The target OS image MUST provide a workload, selectable through the startup launcher like any other, that shows a picture on the emulator's display and reports each remote control key that a program on the target's display receives: its key code, its symbol in the target, and whether it was pressed or released. It MUST run in container mode and in VM mode, so that remote control input can be tried and checked in each.

#### Scenario: Report a key

- WHEN the workload runs and a remote control key is pressed and released through an input mode
- THEN the workload reports that key's code and symbol, once as pressed and once as released

#### Scenario: Run in both modes

- WHEN the workload is selected in container mode or in VM mode
- THEN it shows its picture and reports the keys that arrive
