# Media Playback Specification

## Purpose

Define supported media containers and codecs, video presentation, and audio output behavior.

## Requirements

### Requirement: Accept media containers and fragment injection

The emulator MUST accept media in MPEG-2 Transport Stream (MP2TS) and MP4 containers, and MUST support MSE-style fragment injection.

#### Scenario: Accept MP2TS media

- WHEN media is provided in an MP2TS container
- THEN the emulator accepts the media for decoding

#### Scenario: Accept MP4 media

- WHEN media is provided in an MP4 container
- THEN the emulator accepts the media for decoding

#### Scenario: Inject media fragments

- WHEN media is supplied through MSE-style fragment injection
- THEN the emulator accepts the fragments for decoding

### Requirement: Decode video codecs

The emulator MUST decode MPEG-2 video, AVC, and HEVC.

#### Scenario: Decode MPEG-2 video

- WHEN an MPEG-2 video stream is supplied
- THEN the emulator decodes the video

#### Scenario: Decode AVC video

- WHEN an AVC video stream is supplied
- THEN the emulator decodes the video

#### Scenario: Decode HEVC video

- WHEN an HEVC video stream is supplied
- THEN the emulator decodes the video

### Requirement: Decode audio codecs

The emulator MUST decode MP2, AC-3, AAC, and HE-AAC audio.

#### Scenario: Decode MP2 audio

- WHEN an MP2 audio stream is supplied
- THEN the emulator decodes the audio

#### Scenario: Decode AC-3 audio

- WHEN an AC-3 audio stream is supplied
- THEN the emulator decodes the audio

#### Scenario: Decode AAC audio

- WHEN an AAC audio stream is supplied
- THEN the emulator decodes the audio

#### Scenario: Decode HE-AAC audio

- WHEN an HE-AAC audio stream is supplied
- THEN the emulator decodes the audio

### Requirement: Render decoded video through supported graphics technologies

The emulator MUST render decoded video in workloads using the supported graphics technologies: Wayland, Flutter, OpenGL ES, and Vulkan.

#### Scenario: Present decoded video

- WHEN a workload presents decoded video using a supported graphics technology
- THEN the emulator renders the video through that technology

### Requirement: Route decoded audio through the host OS

The emulator MUST render decoded audio through the host OS audio path.

#### Scenario: Play decoded audio

- WHEN decoded audio is played
- THEN it is rendered through the host OS audio path

### Requirement: Mute audio output at runtime

The emulator MUST allow audio output to be muted and unmuted while running.

#### Scenario: Mute and unmute playback

- WHEN audio is playing
- THEN the audio output can be muted and subsequently unmuted

### Requirement: Start muted, and switch and ask for the audio state from the launcher

The startup launcher MUST accept a setting that starts the emulator with its audio output muted. It MUST offer a command that mutes, unmutes, or toggles the audio output of a running emulator, and that reports its state: whether it is muted, and how many seconds of sound it has received, played, and muted. The command MUST act on every running emulator that was started from the same copy of the project and whose audio is routed through the host, or on the one run that is named. When there is none, it MUST say so and report failure. While audio output is muted the target MUST go on playing unchanged, and the host gets silence in place of the sound.

#### Scenario: Start muted

- WHEN the emulator is started with the setting that mutes it
- THEN its audio output is muted from the start and can be unmuted while it runs

#### Scenario: Toggle the audio output

- WHEN the command is asked to toggle a running emulator's audio output
- THEN the audio output is muted, or unmuted if it was muted

#### Scenario: Ask for the audio state

- WHEN the command is asked for the state
- THEN it says for each such emulator whether it is muted and how much sound it has received, played, and muted

#### Scenario: Name one run

- WHEN the command names a run
- THEN it acts on that run only

#### Scenario: No emulator with audio is running

- WHEN the command is given and no running emulator has audio routed through the host
- THEN it says so and reports failure

#### Scenario: Play on while muted

- WHEN audio output is muted while target software plays sound
- THEN the target software plays on unchanged and the host gets silence

### Requirement: Choose how the host plays the target's sound

The startup launcher MUST accept emulator options that choose the host output device on which the target's sound is played, and that take the sound in without playing it on the host. On macOS and Windows hosts it MUST also accept an option that sets the volume to play at, from 0 to 100, and an option that writes the samples that the host's audio output takes to a file as well.

#### Scenario: Choose the output device

- WHEN an output device of the host is named
- THEN the target's sound is played on that device

#### Scenario: Take the sound in without playing it

- WHEN the option that plays nowhere is given
- THEN the target's sound is taken in by the host and not played

#### Scenario: Set the volume

- WHEN a volume is given on a macOS or Windows host
- THEN the target's sound is played at that volume

#### Scenario: Write what the host's audio output takes

- WHEN a file for the samples is named on a macOS or Windows host
- THEN the samples that the host's audio output takes are written to that file while they are played
