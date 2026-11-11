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