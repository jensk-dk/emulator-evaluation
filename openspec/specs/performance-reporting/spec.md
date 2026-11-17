# Performance Reporting Specification

## Purpose

Define the comparative report required for emulator performance evaluations.

## Requirements

### Requirement: Produce a Slidev performance comparison

The evaluation MUST produce a Slidev presentation comparing the pros and cons of every evaluated host operating system, host CPU architecture, and emulator mode combination, including each VM guest CPU architecture. The presentation MUST include actual measured results for the required performance areas. Unavailable results MUST be identified as unavailable and MUST NOT be presented as measured or replaced with invented estimates.

#### Scenario: Compare evaluated combinations

- WHEN performance evaluation results are reported
- THEN the Slidev presentation compares the pros and cons of each evaluated combination

#### Scenario: Include measured performance results

- WHEN performance results are available for an evaluated combination
- THEN the presentation includes those measured results

#### Scenario: Identify unavailable results

- WHEN a combination or measurement has not been evaluated
- THEN the presentation marks the result as unavailable

### Requirement: Report disk space and time costs

The presentation MUST state, for every evaluated host, the disk space that the host installation takes and the disk space that each target takes individually: the container image, and the VM image of each guest CPU architecture. It MUST also state the time that installing on the host took, the time that building each target took, and the time that running the performance evaluation took. Each value MUST be an actual measurement from that host. A value that has not been measured MUST be identified as unavailable and MUST NOT be presented as measured or replaced with an invented estimate.

#### Scenario: Report the disk space of the host installation

- WHEN results are reported for an evaluated host
- THEN the presentation states the disk space that the host installation takes on that host

#### Scenario: Report the disk space of each target

- WHEN results are reported for an evaluated host
- THEN the presentation states the disk space that each target takes on that host, one value per target

#### Scenario: Report installation time

- WHEN results are reported for an evaluated host
- THEN the presentation states the time that installing on that host took

#### Scenario: Report build time

- WHEN results are reported for an evaluated host
- THEN the presentation states the time that building each target on that host took

#### Scenario: Report performance evaluation time

- WHEN results are reported for an evaluated combination
- THEN the presentation states the time that running the performance evaluation took for that combination

#### Scenario: Identify unavailable disk space and time values

- WHEN a disk space or time value has not been measured on a host
- THEN the presentation marks that value as unavailable

### Requirement: Show the recorded results on a results page

The project MUST provide a results page that shows the recorded performance results as charts. The startup launcher MUST offer a command that serves the page on the host, reachable from that host only, and opens it in the host's browser. The page MUST read the result records each time it loads, so that a newly recorded result appears after a reload and nothing has to be generated again. It MUST describe each host that results were measured on, as the records describe it; what is stated about a host's machine and is not in the records MUST be marked as stated. For each test the page MUST show every host and emulator mode combination that has results, each VM guest CPU architecture included, with the median of its runs and the single runs. It MUST let the user choose which hosts are shown, and whether values are shown as measured or relative to container mode on the same host. A result that a record marks as unavailable MUST be shown as unavailable and MUST NOT be shown as measured. A record that the page cannot read MUST be reported on the page and MUST NOT be left out silently.

#### Scenario: Open the results page

- WHEN the launcher's results command is run
- THEN the page is served on the host and opened in the host's browser

#### Scenario: Show a newly recorded result

- WHEN a result has been recorded and the page is loaded again
- THEN the page shows that result

#### Scenario: Describe the hosts

- WHEN the page is shown
- THEN it describes each host that results were measured on: its CPU, memory, GPU, operating system, and emulator software

#### Scenario: Compare the combinations of a test

- WHEN a test has results
- THEN the page shows, for each host and emulator mode combination, the median of its runs and the single runs

#### Scenario: Choose the hosts

- WHEN the user chooses which hosts are shown
- THEN the page shows the results of those hosts only

#### Scenario: Show values relative to container mode

- WHEN the user asks for relative values
- THEN each value is shown relative to container mode on the same host

#### Scenario: Identify an unavailable result

- WHEN a record marks a result as unavailable
- THEN the page shows it as unavailable, without a value

#### Scenario: A record cannot be read

- WHEN a result record cannot be read
- THEN the page says that what it shows is incomplete

### Requirement: Show platform support and known issues on the results page

The results page MUST show, for each feature that the verification checks cover and for each host and emulator mode, whether the feature was verified there, fails there, or could not be run there, as the verification records of the hosts say. It MUST show what a check found when the user asks for it. Below that it MUST list the known issues and limits, each with the hosts and emulator modes it applies to, and MUST tell apart what fails a check, what is a limit, what no check covers, and what is not implemented.

#### Scenario: Show what was verified

- WHEN the page is shown and a host has a verification record
- THEN each feature has, for that host and each emulator mode, a mark that says verified, fails, or could not be run

#### Scenario: Show what a check found

- WHEN the user asks about a mark
- THEN the page shows what the check found and when it ran

#### Scenario: Follow the last verification

- WHEN the checks have been run again on a host and the page is loaded again
- THEN the marks show the new outcomes

#### Scenario: List the known issues

- WHEN the page is shown
- THEN it lists each known issue and limit with its kind and the hosts and emulator modes it applies to

### Requirement: Show disk space and times on the results page

The results page MUST state, for every evaluated host, the disk space and time values that the report has to state: the disk space of the host installation and of each target, and the time that installing, building each target, and running the performance evaluation took, each with how it was taken. A value that has not been measured MUST be identified as not measured and MUST NOT be replaced with an estimate.

#### Scenario: Show the values of a host

- WHEN the page is shown
- THEN it states the disk space and time values of each evaluated host, each with how it was taken

#### Scenario: Identify a value that is not measured

- WHEN a disk space or time value has not been measured on a host
- THEN the page says that it is not measured

### Requirement: Provide the results page as a PDF

The results page MUST have a layout for paper, so that it can be printed to a PDF document. The project MUST keep a PDF snapshot of the page that has the hosts, the platform support with the known issues, the charts, and the disk space and times. The snapshot MUST show every result record that existed when it was made, and MUST say how many records it shows.

#### Scenario: Print the page

- WHEN the results page is printed to a PDF document
- THEN the document has the hosts, the platform support with the known issues, the charts, and the disk space and times

#### Scenario: Check that the snapshot is complete

- WHEN the snapshot is reviewed
- THEN the number of records it says it shows can be compared with the number of result records
