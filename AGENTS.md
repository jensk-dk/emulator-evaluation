# Instructions for agents

The requirements are in `openspec/specs/`. `openspec/config.yaml` has their
summary and the project's rules, and
`openspec/changes/staged-emulator-delivery/tasks.md` says what is done and
what is verified, on which host.

## Build and verify the simulated ARM targets too

The ARM64 and ARM32 guest CPU modes run on a simulated CPU. They are slow, and
not every graphics technology runs in them, so the setup script does not set a
host up for them by default, and a developer may never build them. An agent
does all the same, so that a change that breaks them is noticed:

- **Set up with the option.** `./setup.sh --arm-targets`, or
  `setup.cmd -ArmTargets` on Windows. Without the option the setup script
  neither checks for nor installs what these targets need.
- **Build their images with the others.** `./emu build --mode all --arch all`.
  Without `--arch` only the image of the host's own CPU architecture is built.
- **Run their checks with the others.** `./emu verify` runs every check. The
  checks for these targets are `vm-arm64` and `vm-arm32` and those whose names
  end in `-vm-arm64` and `-vm-arm32`. On a host that is not set up for the
  targets they end as "unavailable", which is not a pass.
- **Say so when you could not.** If you cannot set up, build or verify the
  simulated ARM targets on a host, say that in your report, and why.

The requirements behind this: "Set up the simulated ARM targets only on
request" (host-setup), "Offer the simulated ARM targets where the host is set
up for them" (execution-modes), and "Keep the simulated ARM targets built and
verified" (functional-verification).

## Measure a host with the script

A host's disk space, install time, build times and performance results are
taken with `python3 evaluation/measure.py run`, not with commands typed one
by one, so that every host is measured the same way
(performance-evaluation: "Measure a host with one command";
`evaluation/procedures.md`, "One command for a host").

- **Look first.** `python3 evaluation/measure.py run --dry-run` says what it
  would run and remove.
- **Ask before the stages that remove.** The build stages empty the container
  engine's build cache, and `--install` removes the host installation and
  needs someone at the host for a password. Run those only when the user has
  asked for them; `--stages sizes,performance,verify` removes nothing.
- **Keep the simulated ARM targets in.** Use `--no-arm-targets` only on a host
  that cannot be set up for them, and say so.
- **Enter no value by hand.** The script writes
  `evaluation/footprint/HOST_MACHINE.json`, and
  `python3 evaluation/measure.py table` prints the rows for
  `evaluation/footprint.md`.
