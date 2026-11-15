# STB Simulator Specification

## Purpose

Define the workload that simulates a set-top box: a user interface with a channel list, video playback, and an app launcher, operated with remote control keys.

## Requirements

### Requirement: Provide an STB simulator workload

The target OS image MUST provide a workload, the STB simulator, that the startup launcher can select like any other target OS workload. When it starts, it MUST show a set-top-box-like user interface on the emulator's display that simulates a device with a channel list, video playback, and an app launcher. It MUST run in container mode and in VM mode.

#### Scenario: Start the STB simulator

- WHEN a user selects the STB simulator workload through the startup launcher
- THEN the emulator starts it and its set-top-box-like user interface appears on the emulator's display

#### Scenario: Run in container mode

- WHEN the STB simulator workload is selected in container mode
- THEN its user interface appears and can be operated

#### Scenario: Run in VM mode

- WHEN the STB simulator workload is selected in VM mode
- THEN its user interface appears and can be operated

#### Scenario: Offer the functions of the simulated device

- WHEN the user interface has started
- THEN the user can reach the channel list, video playback, and the app launcher from it

### Requirement: Operate the user interface with remote control keys

The STB simulator MUST take its key input from the remote control input modes: host keyboard mapping, the on-screen remote control, and RedRat IR input. Every function of its user interface MUST be reachable with remote control keys alone.

#### Scenario: Move with the arrow keys

- WHEN the user presses an arrow key of the remote control
- THEN the selection in the user interface moves in that direction

#### Scenario: Select with ENTER

- WHEN the user presses ENTER (OK) on a selected item
- THEN the user interface opens or starts that item

#### Scenario: Go back with BACK

- WHEN the user presses BACK
- THEN the user interface returns to where the user was before

#### Scenario: Take keys from every input mode

- WHEN a remote control key is pressed through any of the three remote control input modes
- THEN the user interface acts on it in the same way

### Requirement: Present a channel list

The STB simulator MUST present a list of the simulated device's channels and let the user select a channel from it.

#### Scenario: Show the channel list

- WHEN the user opens the channel list
- THEN it lists the channels of the simulated device

#### Scenario: Select a channel

- WHEN the user selects a channel from the channel list
- THEN the STB simulator plays that channel

### Requirement: Play video

The STB simulator MUST play the video of the selected channel on the emulator's display, with its audio.

#### Scenario: Play the selected channel

- WHEN a channel is selected
- THEN its video is shown on the emulator's display and its audio is played

#### Scenario: Change the channel

- WHEN the user selects another channel while one is playing
- THEN the STB simulator plays the newly selected channel instead

### Requirement: Launch applications from an app launcher

The STB simulator MUST provide an app launcher from which the user starts applications. The app launcher MUST include a simulated video-on-demand (VOD) application that runs in the target OS's browser. The VOD application MUST offer titles that are adaptive bitrate (ABR) streams and MUST play the title that the user selects.

#### Scenario: Show the app launcher

- WHEN the user opens the app launcher
- THEN it lists the applications that can be started, the VOD application among them

#### Scenario: Start the VOD application

- WHEN the user starts the VOD application from the app launcher
- THEN the application opens in the target OS's browser and shows its titles

#### Scenario: Play an ABR title

- WHEN the user selects a title in the VOD application
- THEN the application plays that title's adaptive bitrate stream

#### Scenario: Return from an application

- WHEN the user leaves an application that was started from the app launcher
- THEN the STB simulator's user interface is shown again

### Requirement: Stream VOD titles as MPEG-DASH with dash.js

The titles of the VOD application MUST be MPEG-DASH streams, and the application MUST play them with the dash.js player library. The titles MUST be openly licensed films that are freely available as DASH streams on the internet: Big Buck Bunny, Elephants Dream, and similar open-source content.

#### Scenario: Offer the open films

- WHEN the VOD application shows its titles
- THEN Big Buck Bunny and Elephants Dream are among them, each as a link to an MPEG-DASH stream of the film on the internet

#### Scenario: Play a title with dash.js

- WHEN the user selects a title
- THEN the application plays its MPEG-DASH stream with dash.js, which chooses among the stream's representations as it plays

#### Scenario: Title cannot be reached

- WHEN the user selects a title whose stream the target cannot reach
- THEN the application says that the title cannot be played and stays usable

### Requirement: Launch the performance workloads

The STB simulator MUST let the user start each performance evaluation workload from its user interface.

#### Scenario: Offer the performance workloads

- WHEN the user interface has started
- THEN the user can find each performance evaluation workload in it

#### Scenario: Start a performance workload

- WHEN the user starts a performance evaluation workload from the user interface
- THEN that workload runs and reports its results
