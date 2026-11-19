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

The STB simulator MUST take its key input from the joined remote control sources: host keyboard mapping and the on-screen remote control, with RedRat IR added when a profile is selected. Every function of its user interface MUST be reachable with remote control keys alone.

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

- WHEN a remote control key is pressed through any enabled remote control input source
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

### Requirement: Select a channel by its number and step through the channels

While the channel list is shown or a channel is playing, the STB simulator MUST take the number keys as a channel number of up to three digits and play the channel with that number. For a number that no channel has, it MUST say that there is no such channel and leave what is playing as it is. While a channel is playing, the Up and Down keys MUST change to the neighbouring channel.

#### Scenario: Enter a channel number

- WHEN the user presses the number keys of a channel's number
- THEN the STB simulator plays that channel

#### Scenario: Enter a number that no channel has

- WHEN the user enters a number that no channel has
- THEN the STB simulator says that there is no such channel, and a channel that was playing plays on

#### Scenario: Step to the neighbouring channel

- WHEN a channel is playing and the user presses Up or Down
- THEN the STB simulator plays the neighbouring channel

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

### Requirement: Offer a test title that needs no internet

Beside the films, the VOD application MUST offer a test title that is an MPEG-DASH stream kept in the target OS image, in three sizes, so that the application can be used and checked without the internet. It MUST offer that title a second time over a path whose speed the simulator limits, so that only the smallest size can be played. The picture of the test title MUST show which size is playing.

#### Scenario: Play the test title without the internet

- WHEN the user selects the test title and the target cannot reach the internet
- THEN the application plays it with dash.js

#### Scenario: Play the test title over the limited path

- WHEN the user selects the test title over the limited path
- THEN the application plays it and stays at its smallest size

#### Scenario: Show the size that is playing

- WHEN the test title is playing
- THEN its picture shows which of its sizes is playing

### Requirement: Launch the performance workloads

The STB simulator MUST let the user start each performance evaluation workload from its user interface.

#### Scenario: Offer the performance workloads

- WHEN the user interface has started
- THEN the user can find each performance evaluation workload in it

#### Scenario: Start a performance workload

- WHEN the user starts a performance evaluation workload from the user interface
- THEN that workload runs and reports its results

### Requirement: Switch the simulator off from its user interface

The home screen of the STB simulator MUST have an entry that ends the simulator. It MUST be reachable with remote control keys alone, like every other function.

#### Scenario: Switch off

- WHEN the user selects the entry that switches off and presses ENTER (OK)
- THEN the STB simulator workload ends

### Requirement: Report what the user interface does

The STB simulator MUST report on the launcher's output what its user interface does, as it happens: the screen that is shown, the selection, the key it took, the channel that plays, the application that is started, the VOD title and the representation that plays, a performance workload that starts and finishes, and a failure. The reports MUST be enough to follow and to check the user interface without looking at the display.

#### Scenario: Report a screen

- WHEN the user interface shows another screen
- THEN a report on the launcher's output names that screen

#### Scenario: Report a channel

- WHEN a channel starts to play
- THEN a report on the launcher's output names that channel

#### Scenario: Report a representation

- WHEN the player of a VOD title changes to another representation
- THEN a report on the launcher's output names the title and the representation

### Requirement: Time the STB simulator from the host

The project MUST provide a means to measure, on a host and in one emulator mode at a time, how fast the STB simulator starts and answers. It MUST operate the simulator with remote control keys through the emulator's window and take every time on the host's clock. It MUST measure the time from launch to the home screen, from a key to the user interface's answer and to the changed picture in the emulator's window, from a channel change to the new channel's picture, the number of pictures of a channel that reach the window each second, and the time until a VOD title plays. It MUST also run each performance evaluation workload from the simulator's user interface and, beside that, as the launcher runs it under the same conditions, so that what the two report can be compared. Each value MUST be an actual measurement from that host in that emulator mode. These values are findings about the simulator: they MUST be kept apart from the recorded performance results and MUST NOT be presented as results of the performance evaluation.

#### Scenario: Time an emulator mode

- WHEN the measurement is run on a host for an emulator mode
- THEN the times of the simulator in that mode are kept for that host, as taken on the host's clock

#### Scenario: Compare the performance workloads

- WHEN the measurement has run the performance evaluation workloads
- THEN what each reported when started from the user interface is set beside what it reported when the launcher ran it under the same conditions

#### Scenario: Keep the findings apart from the results

- WHEN the measurement has been run
- THEN nothing has been added to the recorded performance results
