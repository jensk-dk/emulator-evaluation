#!/usr/bin/env bash
# Host setup for Linux and macOS.
#
# Checks every host dependency the emulator needs and installs the ones that
# are missing. The Windows equivalent is setup.ps1.
#
#   ./setup.sh           check, then install what is missing (asks first)
#   ./setup.sh --yes     same, without asking
#   ./setup.sh --check   check only; exit 1 if anything is missing
#   ./setup.sh --experimental-qemu
#                        macOS on ARM64: also build and install an experimental
#                        QEMU that maps a VM's graphics to the host GPU. It is
#                        third-party software built from source, not a
#                        dependency, and never installed without this option;
#                        see "Experimental: host graphics on macOS" in the README
#   ./setup.sh --uninstall
#                        remove what this script installed on this host (asks
#                        first; with --check it only lists what that is)
#
# The script keeps a record of what it installs: only of what was not there
# before. --uninstall removes what the record lists and nothing else. The
# record is ~/.local/state/emulator-evaluation/setup-installed (under
# $XDG_STATE_HOME where that is set).
#
# Host dependencies:
#   python3 >= 3.9            runs the launcher (./emu)
#   QEMU system emulators     VM mode: host-native, ARM64 and ARM32 guests
#   hardware virtualization   host-native VM mode (HVF on macOS, KVM on Linux)
#   container runtime         container mode and target image builds
#   foreign-arch emulation    building ARM32/ARM64/x86-64 target images
#
# Optional, installed where the package manager offers it:
#   QEMU OpenGL modules       VM mode maps graphics to the host GPU; without
#                             them graphics are emulated
#   audio player              plays the target's sound through the host's sound
#                             system; without one the target's sound is not heard.
#                             Linux: pacat, pw-cat or aplay. macOS: the launcher
#                             builds its own with the Command Line Tools' compiler
#
# Written for bash 3.2 (the version macOS ships).

set -u

MODE=install
ASSUME_YES=0
EXPERIMENTAL_QEMU=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    -y|--yes) ASSUME_YES=1 ;;
    --experimental-qemu) EXPERIMENTAL_QEMU=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,/^# Written for/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "setup.sh: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

OS=$(uname -s)
case "$(uname -m)" in
  arm64|aarch64) ARCH=arm64; QEMU_NATIVE=qemu-system-aarch64 ;;
  x86_64|amd64)  ARCH=x86_64; QEMU_NATIVE=qemu-system-x86_64 ;;
  *) echo "setup.sh: unsupported host CPU architecture: $(uname -m)" >&2; exit 2 ;;
esac
# A translated (Rosetta) shell on Apple Silicon still has an ARM64 host.
if [ "$OS" = Darwin ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = 1 ]; then
  ARCH=arm64; QEMU_NATIVE=qemu-system-aarch64
fi

# The experimental QEMU for macOS (--experimental-qemu) comes from a
# third-party Homebrew tap. It is built from the tap at one commit, with this
# project's changes to the tap's formulas: those pin the commit of each source
# and let the build find Xcode.
EXP_TAP=milesbuckton/qemu-virgl
EXP_TAP_COMMIT=56626e28d85569703532bc0794027b9e3205cbd9
EXP_QEMU_COMMIT=c95b8c49          # the start of QEMU's commit, which its --version shows
EXP_FORMULAE="gn libangle libepoxy-angle virglrenderer qemu-virgl"      # in build order
EXP_PATCH="$(cd "$(dirname "$0")" && pwd)/docs/macos-experimental-qemu.patch"
if [ "$EXPERIMENTAL_QEMU" = 1 ] && ! { [ "$OS" = Darwin ] && [ "$ARCH" = arm64 ]; }; then
  echo "setup.sh: --experimental-qemu is for macOS on ARM64; on Linux, host graphics comes with the distribution's QEMU" >&2
  exit 2
fi
if [ "$UNINSTALL" = 1 ] && [ "$EXPERIMENTAL_QEMU" = 1 ]; then
  echo "setup.sh: --uninstall removes all that this script installed, the experimental QEMU with it; give it alone" >&2
  exit 2
fi

# Package managers install outside a minimal PATH; look there too.
for d in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin /home/linuxbrew/.linuxbrew/bin; do
  [ -d "$d" ] && case ":$PATH:" in *":$d:"*) ;; *) PATH="$d:$PATH" ;; esac
done
export PATH

MISSING=""          # space-separated dependency keys still missing
OPTIONAL=""         # optional extras this script could install
WARNINGS=0

ok()      { printf '  [ ok ]  %s\n' "$*"; }
missing() { printf '  [MISS]  %s\n' "$2"; MISSING="$MISSING $1"; }
optional() { printf '  [opt ]  %s\n' "$2"; OPTIONAL="$OPTIONAL $1"; }
note()    { printf '  [note]  %s\n' "$*"; }
warn()    { printf '  [warn]  %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }
info()    { printf '%s\n' "$*"; }
have()    { command -v "$1" >/dev/null 2>&1; }
is_missing() { case " $MISSING " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
is_optional() { case " $OPTIONAL " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# ----------------------------------------------------------------- record ---

# What this script installed on this host: a line "KIND VALUE" for each thing
# that was not there before the script put it there. --uninstall goes by it.
RECORD="${EMU_SETUP_RECORD:-${XDG_STATE_HOME:-$HOME/.local/state}/emulator-evaluation/setup-installed}"

record() {
  local entry="$1 ${2:--}"
  if [ ! -f "$RECORD" ]; then
    mkdir -p "$(dirname "$RECORD")" 2>/dev/null &&
      printf '# What setup.sh installed on this host. ./setup.sh --uninstall removes it.\n' > "$RECORD"
  fi
  grep -qxF -- "$entry" "$RECORD" 2>/dev/null && return 0
  printf '%s\n' "$entry" >> "$RECORD" 2>/dev/null ||
    warn "could not write to $RECORD that this script installed: $entry"
}

forget() {
  grep -vxF -- "$1 ${2:--}" "$RECORD" > "$RECORD.new" 2>/dev/null
  mv "$RECORD.new" "$RECORD"
}

# Prints the recorded values of a kind, in the order they were recorded.
recorded() {
  [ -f "$RECORD" ] || return 0
  grep -v '^#' "$RECORD" | grep "^$1 " | cut -d' ' -f2-
}

# The system package manager, and whether it has a package installed.
package_manager() {
  if have apt-get; then echo apt
  elif have dnf; then echo dnf
  elif have pacman; then echo pacman
  elif have zypper; then echo zypper
  fi
}

package_installed() {
  case "$(package_manager)" in
    apt) dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed' ;;
    dnf|zypper) rpm -q "$1" >/dev/null 2>&1 ;;
    pacman) pacman -Qq "$1" >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# Prints the name of every installed system package, sorted, one to a line.
installed_packages() {
  case "$(package_manager)" in
    apt) dpkg-query -W -f='${Status} ${Package}\n' 2>/dev/null | awk '$3 == "installed" { print $4 }' ;;
    # rpm shows a repository's signing key as a package named gpg-pubkey.
    dnf|zypper) rpm -qa --qf '%{NAME}\n' 2>/dev/null | grep -vx gpg-pubkey ;;
    pacman) pacman -Qq 2>/dev/null ;;
  esac | LC_ALL=C sort -u
}

# Of two lists sorted like that: the lines of the second that the first does
# not have, and the lines that both have.
lines_new()  { LC_ALL=C comm -13 <(printf '%s\n' "$1") <(printf '%s\n' "$2"); }
lines_both() { LC_ALL=C comm -12 <(printf '%s\n' "$1") <(printf '%s\n' "$2"); }

# Records what an installation added. $1 is what installed_packages printed
# before it; the rest names the packages that were asked for. Of the packages
# that are installed now and were not then, those asked for are recorded under
# the package manager's name (apt), and those that came with them under that
# name with -dep (apt-dep). --uninstall removes no package but these.
record_added() {
  local before="$1" manager p
  shift
  if [ -z "$before" ]; then
    warn "could not list the installed packages, so what was installed now is not in the record"
    return 0
  fi
  manager=$(package_manager)
  for p in $(lines_new "$before" "$(installed_packages)"); do
    case " $* " in
      *" $p "*) record "$manager" "$p" ;;
      *) record "$manager-dep" "$p" ;;
    esac
  done
  return 0
}

# Prints the recorded values of a kind, sorted like installed_packages.
recorded_sorted() { recorded "$1" | LC_ALL=C sort -u; }

# Forgets the listed packages of a kind.
forget_packages() {
  [ -n "$2" ] || return 0
  grep -vxF -f <(printf '%s\n' "$2" | sed "s/^/$1 /") "$RECORD" > "$RECORD.new" 2>/dev/null
  mv "$RECORD.new" "$RECORD"
}

brew_installed() { brew list --versions "$1" >/dev/null 2>&1; }

# Prints the name of every installed Homebrew formula, sorted, one to a line.
# Fails where Homebrew does not say.
brew_formulae() {
  local out
  out=$(brew list --formula -1 2>/dev/null) || return 1
  printf '%s\n' "$out" | LC_ALL=C sort -u
}

# Prints the installed formulae that Homebrew holds to be unused: installed as
# a dependency, and needed by nothing any more.
brew_unused() {
  brew autoremove --dry-run 2>/dev/null | grep -v '^==>' | tr ' ' '\n' | sed 's|.*/||' | grep . | LC_ALL=C sort -u
}

# Records what a Homebrew installation added, as record_added does for system
# packages. $1 is what brew_formulae printed before it; the rest names the
# formulae that were asked for. Of the formulae that are installed now and
# were not then, those asked for are recorded as brew, in the order given, and
# those that came with them as brew-dep.
record_brew_added() {
  local before="$1" added f
  shift
  added=$(lines_new "$before" "$(brew_formulae)")
  for f in "$@"; do
    [ -z "$(lines_both "$added" "$f")" ] || record brew "$f"
  done
  for f in $added; do
    case " $* " in *" $f "*) ;; *) record brew-dep "$f" ;; esac
  done
  return 0
}

# ----------------------------------------------------------------- checks ---

check_python() {
  # /usr/bin/python3 on macOS is a stub that opens an install dialog unless
  # the Command Line Tools are present, so test for those first.
  if [ "$OS" = Darwin ] && ! xcode-select -p >/dev/null 2>&1 && [ "$(command -v python3)" = /usr/bin/python3 ]; then
    missing python "python3 >= 3.9 (Xcode Command Line Tools not installed)"
  elif have python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    ok "python3 $(python3 -c 'import platform; print(platform.python_version())') ($(command -v python3))"
  else
    missing python "python3 >= 3.9"
  fi
}

check_qemu() {
  local bin absent=""
  for bin in "$QEMU_NATIVE" qemu-system-aarch64 qemu-system-arm; do
    case " $absent " in *" $bin "*) continue ;; esac
    have "$bin" || absent="$absent $bin"
  done
  if [ -z "$absent" ]; then
    ok "QEMU: $("$QEMU_NATIVE" --version | head -1) (native, ARM64 and ARM32 system emulators)"
  else
    missing qemu "QEMU system emulators:$absent"
  fi
}

# Host graphics acceleration for VM mode needs a QEMU with the GPU-accelerated
# display device and a display backend that renders without a window.
qemu_has_gl() {
  have "$QEMU_NATIVE" || return 1
  "$QEMU_NATIVE" -device help 2>/dev/null | grep -q 'virtio-gpu-gl-pci' &&
    "$QEMU_NATIVE" -display help 2>/dev/null | grep -q 'egl-headless'
}

# Distribution packages that add them to an installed QEMU.
linux_gl_packages() {
  if have apt-get; then echo "qemu-system-modules-opengl"
  elif have dnf; then echo "qemu-device-display-virtio-gpu-gl qemu-ui-egl-headless qemu-ui-opengl"
  elif have pacman; then echo "qemu-hw-display-virtio-gpu-gl qemu-ui-egl-headless qemu-ui-opengl"
  fi
}

check_graphics() {
  have "$QEMU_NATIVE" || return 0
  if qemu_has_gl && [ "$OS" = Linux ] && ! ls /dev/dri/renderD* >/dev/null 2>&1; then
    # Nothing this script installs: which GPU driver fits is the host's matter.
    note "host graphics acceleration for VM mode: QEMU supports it, but the host has no GPU render node (/dev/dri/renderD*), so no GPU driver is loaded; graphics are emulated"
  elif qemu_has_gl; then
    ok "host graphics acceleration for VM mode (QEMU with virglrenderer)"
  elif [ "$OS" = Linux ] && [ -n "$(linux_gl_packages)" ]; then
    optional qemu-gl "host graphics acceleration for VM mode: QEMU's OpenGL modules are not installed; graphics are emulated without them"
  else
    note "host graphics acceleration for VM mode: this QEMU build has none; graphics are emulated"
  fi
}

# Prints the experimental QEMU's emulator, if that build is installed.
experimental_qemu() {
  have brew || return 1
  local bin; bin="$(brew --prefix)/opt/qemu-virgl/bin/qemu-system-aarch64"
  [ -x "$bin" ] && printf '%s' "$bin"
}

# Reported wherever it is installed; asked for only with --experimental-qemu.
check_experimental_qemu() {
  [ "$OS" = Darwin ] && [ "$ARCH" = arm64 ] || return 0
  local bin version
  if bin=$(experimental_qemu); then
    version=$("$bin" --version 2>/dev/null | head -1)
    case "$version" in
      *"-g$EXP_QEMU_COMMIT"*)
        ok "experimental QEMU with host graphics for VM mode: ${version#QEMU emulator version }; the launcher uses it when EMU_QEMU_DIR=$(dirname "$bin")" ;;
      *)
        note "experimental QEMU: the build in $(dirname "$bin") is not the one this project pinned (${version:-it does not run})" ;;
    esac
  elif [ "$EXPERIMENTAL_QEMU" = 1 ]; then
    optional experimental-qemu "experimental QEMU with host graphics for VM mode: not installed"
  fi
}

# The launcher plays the target's sound through one of these programs.
have_audio_player() { have pacat || have pw-cat || have aplay; }

linux_audio_packages() {
  if have apt-get; then echo "pulseaudio-utils"
  elif have dnf; then echo "pulseaudio-utils"
  elif have pacman; then echo "libpulse"
  elif have zypper; then echo "pulseaudio-utils"
  fi
}

check_audio() {
  if [ "$OS" = Darwin ]; then
    # macOS has no program that plays raw samples; the launcher builds one
    # (emulator/coreaudio_player.c) the first time it plays sound.
    if xcode-select -p >/dev/null 2>&1 && have clang; then
      ok "audio player: built by the launcher (emu-coreaudio, with the Command Line Tools' compiler)"
    else
      note "audio player: the launcher cannot build its player without the Xcode Command Line Tools; the target's sound is not heard without it"
    fi
    return 0
  fi
  [ "$OS" = Linux ] || return 0
  if have pacat; then ok "audio player: pacat (PulseAudio or PipeWire)"
  elif have pw-cat; then ok "audio player: pw-cat (PipeWire)"
  elif have aplay; then ok "audio player: aplay (ALSA)"
  elif [ -n "$(linux_audio_packages)" ]; then
    optional audio-player "audio player: none of pacat, pw-cat and aplay is installed; the target's sound is not heard without one"
  else
    note "audio player: none of pacat, pw-cat and aplay is installed; the target's sound is not heard without one"
  fi
}

check_accel() {
  if [ "$OS" = Darwin ]; then
    if [ "$(sysctl -n kern.hv_support 2>/dev/null)" = 1 ]; then
      ok "hardware virtualization: Hypervisor.framework (HVF)"
    else
      warn "Hypervisor.framework is unavailable; host-native VM mode will fall back to slow emulation"
    fi
  elif [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ok "hardware virtualization: KVM (/dev/kvm)"
  elif [ -e /dev/kvm ]; then
    missing kvm "KVM access: $(id -un) cannot open /dev/kvm"
  else
    warn "/dev/kvm does not exist (virtualization disabled in firmware, or nested virtualization unavailable); host-native VM mode will fall back to slow emulation"
  fi
}

# Sets CONTAINER_CLI to a container CLI whose engine answers, if there is one.
CONTAINER_CLI=""
check_container() {
  local cli
  CONTAINER_CLI=""
  for cli in docker podman; do
    if have "$cli" && "$cli" info >/dev/null 2>&1; then CONTAINER_CLI=$cli; break; fi
  done
  if [ -n "$CONTAINER_CLI" ]; then
    ok "container runtime: $("$CONTAINER_CLI" --version | head -1)"
    if [ "$CONTAINER_CLI" = docker ] && ! docker buildx version >/dev/null 2>&1; then
      missing buildx "docker buildx plugin (the builder the target image needs)"
    fi
  elif have docker || have podman; then
    missing engine "container engine: a container CLI is installed but no engine is running"
  else
    missing container "container runtime (docker or podman)"
  fi
}

# Building target images for other CPU architectures runs their binaries
# through user-mode emulation (binfmt_misc) in the container engine's kernel.
# Prints the target platforms that kernel cannot run, if any.
foreign_arch_gaps() {
  local need plats p reg gaps=""
  if [ "$ARCH" = arm64 ]; then need="linux/arm/v7"; else need="linux/arm64 linux/arm/v7"; fi
  # The builder's own platform list is quick to read but is not refreshed
  # when emulators are registered later, so only trust it when it says yes.
  if [ "$CONTAINER_CLI" = docker ] && docker buildx version >/dev/null 2>&1; then
    plats=$(docker buildx inspect 2>/dev/null | sed -n 's/^Platforms://p' | tr -d ' ')
    for p in $need; do
      case ",$plats," in *",$p,"*) ;; *) gaps="$gaps $p" ;; esac
    done
    [ -z "$gaps" ] && return 0
    gaps=""
  fi
  # Ask the kernel the engine runs on what it has registered.
  if [ "$OS" != Darwin ]; then
    reg=$(ls /proc/sys/fs/binfmt_misc 2>/dev/null)
  elif [ "$CONTAINER_CLI" = podman ]; then
    reg=$(podman machine ssh ls /proc/sys/fs/binfmt_misc 2>/dev/null)
  elif have colima && colima status >/dev/null 2>&1; then
    reg=$(colima ssh -- ls /proc/sys/fs/binfmt_misc 2>/dev/null)
  else
    # Docker Desktop registers every emulator itself.
    reg="qemu-aarch64 qemu-arm"
  fi
  for p in $need; do
    case "$p" in
      linux/arm64)  echo "$reg" | tr ' ' '\n' | grep -q '^qemu-aarch64' || gaps="$gaps $p" ;;
      linux/arm/v7) echo "$reg" | tr ' ' '\n' | grep -q '^qemu-arm$' || gaps="$gaps $p" ;;
    esac
  done
  printf '%s' "$gaps"
}

check_foreign_arch() {
  [ -n "$CONTAINER_CLI" ] || return 0
  is_missing buildx && return 0
  local gaps; gaps=$(foreign_arch_gaps)
  if [ -z "$gaps" ]; then
    ok "foreign-architecture emulation for target image builds"
  else
    missing binfmt "foreign-architecture emulation (binfmt) for:$gaps"
  fi
}

run_checks() {
  MISSING=""; OPTIONAL=""; WARNINGS=0
  info "Host: $OS $ARCH"
  check_python
  check_qemu
  check_graphics
  check_experimental_qemu
  check_audio
  check_accel
  check_container
  check_foreign_arch
}

# ---------------------------------------------------------------- install ---

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  if [ ! -t 0 ]; then
    info "Not running interactively; re-run with --yes to go ahead."
    return 1
  fi
  printf '%s [y/N] ' "$1"
  local reply; read -r reply
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

run() { info "  + $*"; "$@"; }

as_root() {
  if [ "$(id -u)" = 0 ]; then run "$@"; elif have sudo; then run sudo "$@"; else
    info "  ! need root to run: $*"; return 1
  fi
}

install_macos() {
  if is_missing python && ! xcode-select -p >/dev/null 2>&1; then
    info "Installing the Xcode Command Line Tools (provides python3)..."
    [ -d /Library/Developer/CommandLineTools ] || record xcode-clt
    run xcode-select --install || true
    info "  Finish the installation dialog, then run ./setup.sh again."
    return 1
  fi

  if ! have brew; then
    info "Installing Homebrew (https://brew.sh), which asks for your password..."
    local installer=https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh
    # Homebrew's installer installs the Command Line Tools where they are
    # missing, and makes them the selected developer directory.
    local had_tools=0 selected installer_status=0
    [ -d /Library/Developer/CommandLineTools ] && had_tools=1
    selected=$(xcode-select -p 2>/dev/null)
    if [ -t 0 ]; then
      /bin/bash -c "$(curl -fsSL "$installer")" || installer_status=1
    else
      NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL "$installer")" || installer_status=2
    fi
    # Recorded also where the installer failed: it may have got this far.
    if [ "$had_tools" = 0 ] && [ -d /Library/Developer/CommandLineTools ]; then record xcode-clt; fi
    if [ -n "$selected" ] && [ "$(xcode-select -p 2>/dev/null)" != "$selected" ]; then
      record xcode-select "$selected"
    fi
    if [ "$installer_status" = 2 ]; then
      info "  Homebrew needs an interactive terminal for the password prompt."
      info "  Run ./setup.sh from a terminal."
    fi
    [ "$installer_status" = 0 ] || return 1
    for d in /opt/homebrew/bin /usr/local/bin; do
      [ -x "$d/brew" ] && eval "$("$d/brew" shellenv)"
    done
    have brew || { info "  Homebrew installation did not produce a brew command."; return 1; }
    record homebrew
  fi

  local pkgs=""
  is_missing python && pkgs="$pkgs python"
  is_missing qemu && pkgs="$pkgs qemu"
  if is_missing container; then pkgs="$pkgs colima docker docker-buildx"; fi
  if is_missing buildx; then pkgs="$pkgs docker-buildx"; fi
  if is_missing engine && ! have colima && ! [ -d /Applications/Docker.app ]; then pkgs="$pkgs colima"; fi
  if [ -n "$pkgs" ]; then
    local before="" listed=1 brew_status
    before=$(brew_formulae) || listed=0
    # shellcheck disable=SC2086
    HOMEBREW_NO_AUTO_UPDATE=1 run brew install $pkgs
    brew_status=$?
    if [ "$listed" = 1 ]; then
      # shellcheck disable=SC2086
      record_brew_added "$before" $pkgs
    else
      warn "Homebrew did not list its packages, so what was installed now is not in the record"
    fi
    [ "$brew_status" = 0 ] || return 1
  fi

  # Homebrew installs buildx as a CLI plugin outside docker's search path.
  if have docker && ! docker buildx version >/dev/null 2>&1; then
    local plugin; plugin="$(brew --prefix)/opt/docker-buildx/bin/docker-buildx"
    if [ -x "$plugin" ]; then
      local d link="$HOME/.docker/cli-plugins/docker-buildx"
      for d in "$HOME/.docker" "$HOME/.docker/cli-plugins"; do
        [ -d "$d" ] || { run mkdir "$d" && record dir "$d"; }
      done
      [ -e "$link" ] || [ -L "$link" ] || record link "$link"
      run ln -sfn "$plugin" "$link"
    fi
  fi

  # Start the container engine if a CLI is present but nothing answers.
  if ! { have docker && docker info >/dev/null 2>&1; }; then
    if have colima; then
      local cpus mem
      cpus=$(sysctl -n hw.ncpu); [ "$cpus" -gt 6 ] && cpus=6
      mem=$(( $(sysctl -n hw.memsize) / 1073741824 / 3 )); [ "$mem" -lt 4 ] && mem=4; [ "$mem" -gt 8 ] && mem=8
      if colima list 2>/dev/null | awk 'NR>1 && $1=="default"{f=1} END{exit !f}'; then
        run colima start || return 1
      else
        record colima-vm default
        run colima start --cpu "$cpus" --memory "$mem" --disk 60 --vm-type vz --mount-type virtiofs || return 1
      fi
    elif [ -d /Applications/Docker.app ]; then
      run open -ga Docker
      info "  Waiting for Docker Desktop to start..."
      local i=0; while [ $i -lt 60 ] && ! docker info >/dev/null 2>&1; do sleep 2; i=$((i + 1)); done
    fi
  fi

  # Register user-mode emulation for the other target architectures.
  if have docker && docker info >/dev/null 2>&1; then
    CONTAINER_CLI=docker
    if [ -n "$(foreign_arch_gaps)" ]; then
      # Emulators for the target architectures this host cannot run itself.
      local emulators=arm,arm64
      [ "$ARCH" = arm64 ] && emulators=arm
      docker image inspect tonistiigi/binfmt >/dev/null 2>&1 || record engine-image tonistiigi/binfmt
      run docker run --rm --privileged tonistiigi/binfmt --install "$emulators" >/dev/null || return 1
      record binfmt "$emulators"
    fi
  fi

  if is_optional experimental-qemu; then
    install_experimental_qemu || return 1
  fi
}

# Prints Xcode's developer directory, whether Xcode is the selected one or not
# (Homebrew looks for Xcode in the same places).
xcode_developer_dir() {
  local dir app
  dir=$(xcode-select -p 2>/dev/null)
  case "$dir" in
    *.app/Contents/Developer) [ -d "$dir" ] && { printf '%s' "$dir"; return 0; } ;;
  esac
  for app in /Applications/Xcode.app "$(mdfind "kMDItemCFBundleIdentifier == 'com.apple.dt.Xcode'" 2>/dev/null | head -1)"; do
    if [ -n "$app" ] && [ -d "$app/Contents/Developer" ]; then
      printf '%s' "$app/Contents/Developer"; return 0
    fi
  done
  return 1
}

# Reads a patch; prints a number for what it changes, whatever its line numbers.
patch_id() { git patch-id --stable | cut -d' ' -f1; }

# The body is a subshell, so that its Homebrew settings stay its own.
install_experimental_qemu() (
  info "Building the experimental QEMU..."
  # ANGLE's build needs the Xcode app; the Command Line Tools are not enough.
  if ! xcode=$(xcode_developer_dir); then
    info "  This needs the Xcode app, which is not installed. Install Xcode from the App"
    info "  Store, open it once, then run ./setup.sh --experimental-qemu again."
    return 1
  fi
  if ! answer=$(DEVELOPER_DIR="$xcode" /usr/bin/xcodebuild -license check 2>&1); then
    info "  Xcode ($xcode) is not ready to build with:"
    info "  ${answer:-xcodebuild -license check failed}"
    return 1
  fi
  [ -f "$EXP_PATCH" ] || { info "  $EXP_PATCH is missing."; return 1; }

  # Homebrew must not update itself in between: that moves the tap off its commit.
  export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 HOMEBREW_NO_INSTALL_CLEANUP=1
  prefix=$(brew --prefix)

  # Homebrew 7 loads formulas from a tap only once the tap is trusted.
  if brew help trust >/dev/null 2>&1; then
    trusted=$(brew trust --json=v1 2>/dev/null)
    run brew trust --tap "$EXP_TAP" || return 1
    case "$trusted" in *"\"$EXP_TAP\""*) ;; *) record brew-trust "$EXP_TAP" ;; esac
  fi
  tap_dir=$(brew --repository "$EXP_TAP")
  if [ ! -d "$tap_dir/.git" ]; then
    record brew-tap "$EXP_TAP"
    run brew tap "$EXP_TAP" || return 1
  fi

  # The formulas as this project built them: the tap at its commit, with the patch.
  head=$(git -C "$tap_dir" rev-parse HEAD 2>/dev/null)
  changes=$(git -C "$tap_dir" diff --no-ext-diff --src-prefix=a/ --dst-prefix=b/ HEAD | patch_id)
  if [ "$head" = "$EXP_TAP_COMMIT" ] && [ "$changes" = "$(patch_id < "$EXP_PATCH")" ]; then
    info "  The tap in $tap_dir has this project's changes already."
  elif [ -n "$(git -C "$tap_dir" status --porcelain)" ]; then
    info "  The tap in $tap_dir has local changes that are not this project's."
    info "  They are left alone; undo them or remove the tap, then run this again."
    return 1
  else
    if [ "$head" != "$EXP_TAP_COMMIT" ]; then
      git -C "$tap_dir" cat-file -e "$EXP_TAP_COMMIT^{commit}" 2>/dev/null ||
        run git -C "$tap_dir" fetch --quiet origin "$EXP_TAP_COMMIT" || {
          info "  The tap no longer has commit $EXP_TAP_COMMIT, which this build is made from."
          return 1
        }
      run git -C "$tap_dir" checkout --quiet --detach "$EXP_TAP_COMMIT" || return 1
    fi
    run git -C "$tap_dir" apply "$EXP_PATCH" || return 1
  fi

  # Homebrew keeps one package of a name, and its own virglrenderer has this
  # name too. Look before building anything.
  to_build=""
  for formula in $EXP_FORMULAE; do
    receipt="$prefix/opt/$formula/INSTALL_RECEIPT.json"
    if [ ! -f "$receipt" ]; then
      to_build="$to_build $formula"
    elif ! grep -Eq "\"tap\": *\"$EXP_TAP\"" "$receipt"; then
      info "  Another $formula is installed, one that is not from $EXP_TAP. The"
      info "  experimental QEMU needs its own, and that one is not replaced."
      return 1
    fi
  done
  for formula in $to_build; do
    before=$(brew_formulae) || { info "  Homebrew does not list its packages."; return 1; }
    run brew install --build-from-source "$EXP_TAP/$formula"
    build_status=$?
    # With the formula, what its build brought: also where the build failed.
    record_brew_added "$before" "$formula"
    [ "$build_status" = 0 ] || return 1
    # Keep a later `brew upgrade` from building it again from other commits.
    run brew pin "$formula" || info "  Could not pin $formula; brew upgrade may rebuild it from newer sources."
  done
  experimental_qemu >/dev/null || { info "  The build ended without a QEMU in $prefix/opt/qemu-virgl."; return 1; }
)

# Whether the user is in a group, as the group database has it (a session
# that is already open does not see a change).
in_group() { id -nG "$(id -un)" | tr ' ' '\n' | grep -qx "$1"; }

add_to_group() {
  local was_in=0
  in_group "$1" && was_in=1
  as_root usermod -aG "$1" "$(id -un)" || return 1
  [ "$was_in" = 1 ] || record group "$1"
  info "  Added $(id -un) to the $1 group; log out and back in for it to apply."
}

install_linux() {
  local native_pkg cli="" before="" pkgs="" status=0
  have docker && cli=docker
  have podman && cli=podman

  # Before each installation: the packages that are installed, for the record
  # of what the installation adds.
  if have apt-get; then
    is_missing python && pkgs="$pkgs python3"
    is_missing qemu && pkgs="$pkgs qemu-system-x86 qemu-system-arm qemu-utils"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-user-static binfmt-support"
    if [ -n "$pkgs" ]; then
      as_root apt-get update || return 1
      before=$(installed_packages)
      # shellcheck disable=SC2086
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $pkgs || status=1
    fi
  elif have dnf; then
    is_missing python && pkgs="$pkgs python3"
    is_missing qemu && pkgs="$pkgs qemu-system-x86 qemu-system-aarch64 qemu-system-arm qemu-img"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-user-static"
    before=$(installed_packages)
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || as_root dnf install -y $pkgs || status=1
  elif have pacman; then
    is_missing python && pkgs="$pkgs python"
    is_missing qemu && pkgs="$pkgs qemu-system-x86 qemu-system-aarch64 qemu-system-arm qemu-img"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-user-static qemu-user-static-binfmt"
    before=$(installed_packages)
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || as_root pacman -S --needed --noconfirm $pkgs || status=1
  elif have zypper; then
    is_missing python && pkgs="$pkgs python3"
    is_missing qemu && pkgs="$pkgs qemu-x86 qemu-arm qemu-tools"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-linux-user"
    before=$(installed_packages)
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || as_root zypper --non-interactive install $pkgs || status=1
  else
    info "No supported package manager found (apt-get, dnf, pacman or zypper)."
    info "Install these yourself: python3 >= 3.9, QEMU system emulators for $ARCH, aarch64 and arm,"
    info "podman or docker, and qemu-user-static with binfmt_misc."
    return 1
  fi
  # shellcheck disable=SC2086
  [ -z "$pkgs" ] || record_added "$before" $pkgs
  [ "$status" = 0 ] || return 1

  # Optional: QEMU's OpenGL modules. A failure here leaves graphics emulated.
  if ! qemu_has_gl && [ -n "$(linux_gl_packages)" ]; then
    local gl_status=0
    before=$(installed_packages)
    # shellcheck disable=SC2046
    if have apt-get; then
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $(linux_gl_packages) || gl_status=1
    elif have dnf; then
      as_root dnf install -y $(linux_gl_packages) || gl_status=1
    elif have pacman; then
      as_root pacman -S --needed --noconfirm $(linux_gl_packages) || gl_status=1
    fi
    # shellcheck disable=SC2046
    record_added "$before" $(linux_gl_packages)
    [ "$gl_status" = 0 ] || info "  Could not install QEMU's OpenGL modules; VM mode will emulate graphics."
  fi

  # Optional: a program to play the target's sound with.
  if ! have_audio_player && [ -n "$(linux_audio_packages)" ]; then
    local audio_status=0
    before=$(installed_packages)
    # shellcheck disable=SC2046
    if have apt-get; then
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $(linux_audio_packages) || audio_status=1
    elif have dnf; then
      as_root dnf install -y $(linux_audio_packages) || audio_status=1
    elif have pacman; then
      as_root pacman -S --needed --noconfirm $(linux_audio_packages) || audio_status=1
    elif have zypper; then
      as_root zypper --non-interactive install $(linux_audio_packages) || audio_status=1
    fi
    # shellcheck disable=SC2046
    record_added "$before" $(linux_audio_packages)
    [ "$audio_status" = 0 ] || info "  Could not install an audio player; the target's sound will not be heard on the host."
  fi

  if is_missing binfmt && have systemctl; then
    as_root systemctl restart systemd-binfmt.service 2>/dev/null || true
  fi
  if is_missing engine && have docker && have systemctl; then
    local was_enabled=0
    systemctl is-enabled --quiet docker 2>/dev/null && was_enabled=1
    as_root systemctl enable --now docker || true
    if [ "$was_enabled" = 0 ] && systemctl is-enabled --quiet docker 2>/dev/null; then record service docker; fi
    if ! docker info >/dev/null 2>&1; then
      add_to_group docker
    fi
  fi
  if is_missing kvm; then
    add_to_group "$(stat -c %G /dev/kvm 2>/dev/null || echo kvm)"
  fi
}

# -------------------------------------------------------------- uninstall ---

# The kinds of entry in the record that this script removes, in the order to
# remove them: what uses a thing goes before the thing. Homebrew itself is in
# the record where this script installed it; it goes with all that is
# installed with it, before the entries of that.
REMOVE_ORDER="service group binfmt engine-image colima-vm link dir homebrew brew brew-tap brew-trust apt dnf pacman zypper"
# The kinds it lists and leaves: other software on the host can have come to
# use them, and removing them takes root rights.
LEAVE_ORDER="xcode-select xcode-clt"

# Prints the name of every package installed with Homebrew, formulae and
# casks, sorted.
brew_packages() { { brew list --formula -1; brew list --cask -1; } 2>/dev/null | LC_ALL=C sort -u; }

# Whether this script installed the Homebrew that is on this host. Then all
# that is installed with Homebrew counts as this project's, also what was
# installed with it later, and goes with it.
homebrew_goes() { [ -n "$(recorded homebrew)" ] && have brew; }

# Whether removing Homebrew would stop at its password prompt: its uninstaller
# uses sudo, and without a terminal sudo cannot ask.
homebrew_needs_terminal() { homebrew_goes && [ ! -t 0 ] && ! sudo -n true 2>/dev/null; }

# Removes Homebrew with its own uninstaller, and with it all that is installed
# with Homebrew. --force: this script has asked already.
remove_homebrew() {
  local uninstaller=https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh script
  info "  Removing Homebrew with its own uninstaller (https://brew.sh), which asks for your password..."
  if ! script=$(curl -fsSL "$uninstaller"); then
    info "  ! Could not fetch Homebrew's uninstaller: $uninstaller"
    return 1
  fi
  info "  + /bin/bash -c \"\$(curl -fsSL $uninstaller)\" uninstall.sh --force"
  /bin/bash -c "$script" uninstall.sh --force
  hash -r
  if have brew; then
    info "  ! Homebrew is still installed. What is installed with it stays too."
    return 1
  fi
}

engine_answers() { have docker && docker info >/dev/null 2>&1; }

# Whether what an entry of the record names is still there.
entry_present() {
  case "$1" in
    service) systemctl is-enabled --quiet "$2" 2>/dev/null ;;
    group) in_group "$2" ;;
    binfmt|engine-image)
      # Both are inside the container engine. They go with its virtual machine
      # where this script created that; a stopped engine cannot be asked.
      [ -z "$(recorded colima-vm)" ] || return 1
      have docker || return 1
      engine_answers || return 0
      [ "$1" = binfmt ] || docker image inspect "$2" >/dev/null 2>&1 ;;
    colima-vm) have colima && colima list 2>/dev/null | awk -v p="$2" 'NR > 1 && $1 == p { f = 1 } END { exit !f }' ;;
    link) [ -L "$2" ] ;;
    dir) [ -d "$2" ] ;;
    brew) have brew && brew_installed "$2" ;;
    brew-tap) have brew && [ -d "$(brew --repository "$2" 2>/dev/null)" ] ;;
    brew-trust) have brew && brew trust --json=v1 2>/dev/null | grep -q "\"$2\"" ;;
    apt|dnf|pacman|zypper) [ "$1" = "$(package_manager)" ] && package_installed "$2" ;;
    homebrew) have brew ;;
    xcode-select) [ -d "$2" ] && [ "$(xcode-select -p 2>/dev/null)" != "$2" ] ;;
    xcode-clt) [ -d /Library/Developer/CommandLineTools ] ;;
    *) return 1 ;;
  esac
}

entry_text() {
  case "$1" in
    service) echo "the start of the $2 service at boot (the service is stopped and disabled)" ;;
    group) echo "the membership of $(id -un) in the group $2" ;;
    binfmt) echo "the emulation of other CPU architectures registered in the container engine ($2)" ;;
    engine-image) echo "the container image $2" ;;
    colima-vm) echo "the Colima virtual machine \"$2\", with every container, image and volume in it" ;;
    link) echo "the link $2" ;;
    dir) echo "the directory $2, if it is empty" ;;
    homebrew) echo "Homebrew itself, which this script installed, with every package installed with it: $(brew_packages | grep -c .) now" ;;
    brew) echo "the Homebrew package $2" ;;
    brew-tap) echo "the Homebrew tap $2" ;;
    brew-trust) echo "Homebrew's trust in the tap $2" ;;
    apt|dnf|pacman|zypper)
      if [ "$2" = podman ]; then
        echo "the package podman, and Podman's storage: every container, image and volume of $(id -un)"
      else
        echo "the package $2"
      fi ;;
  esac
}

# Calls a function with the kind and the value of each entry of the kinds named.
each_entry() {
  local call="$1" kind value lines
  shift
  for kind in "$@"; do
    lines=$(recorded "$kind")
    # Of packages and directories, the one recorded last goes first.
    case "$kind" in brew|dir) lines=$(printf '%s\n' "$lines" | sed '1!G;h;$!d') ;; esac
    # Read on descriptor 3: what is called may ask the user something.
    while IFS= read -r value <&3; do
      [ -z "$value" ] || "$call" "$kind" "$value"
    done 3<<EOF
$lines
EOF
  done
}

list_entry() {
  local others
  # What is inside a virtual machine that goes is not listed beside it, nor
  # what is installed with a Homebrew that goes.
  case "$1" in
    binfmt|engine-image) [ -z "$(recorded colima-vm)" ] || return 0 ;;
    brew|brew-tap|brew-trust) ! homebrew_goes || return 0 ;;
  esac
  if entry_present "$1" "$2"; then
    info "  - $(entry_text "$1" "$2")"
    TO_REMOVE=$((TO_REMOVE + 1))
    if [ "$1" = homebrew ]; then
      others=$(lines_new "$({ recorded brew; recorded brew-dep; } | LC_ALL=C sort -u)" "$(brew_packages)")
      # shellcheck disable=SC2086
      [ -z "$others" ] || info "    Of those, this script did not install:" $others
    fi
  else
    info "  - $(entry_text "$1" "$2"): gone already"
  fi
}

remove_entry() {
  local kind="$1" value="$2" status=0 names
  # What is installed with a Homebrew that goes is not removed on its own. A
  # Homebrew that was to go and is still there could not be removed, and then
  # all of it stays.
  case "$kind" in brew|brew-tap|brew-trust) ! homebrew_goes || return 0 ;; esac
  if ! entry_present "$kind" "$value"; then forget "$kind" "$value"; return 0; fi
  case "$kind" in
    homebrew) remove_homebrew || status=1 ;;
    service) as_root systemctl disable --now "$value" || status=1 ;;
    group) as_root gpasswd -d "$(id -un)" "$value" || status=1 ;;
    binfmt|engine-image)
      if ! engine_answers; then
        info "  ! The container engine does not answer, so this stays: $(entry_text "$kind" "$value")."
        status=1
      elif [ "$kind" = binfmt ]; then
        # "arm,arm64" was registered under the names qemu-arm and qemu-aarch64.
        names=$(printf '%s' "$value" | sed -e 's/arm64/aarch64/' -e 's/[^,][^,]*/qemu-&/g')
        run docker run --rm --privileged tonistiigi/binfmt --uninstall "$names" >/dev/null || status=1
      else
        run docker rmi "$value" >/dev/null || status=1
      fi ;;
    colima-vm)
      # --data removes the disk with the images too; Colima before 0.9 has no
      # such disk and no such option.
      run colima delete --profile "$value" --force --data ||
        run colima delete --profile "$value" --force || status=1 ;;
    link) run rm "$value" || status=1 ;;
    dir) rmdir "$value" 2>/dev/null || info "  $value is not empty and stays." ;;
    brew)
      brew unpin "$value" >/dev/null 2>&1    # Homebrew does not uninstall a pinned package
      # This formula only: HOMEBREW_NO_AUTOREMOVE is set, and what came with it
      # goes by the record (remove_brew_dependencies).
      run brew uninstall "$value" || status=1 ;;
    brew-tap) run brew untap "$value" || status=1 ;;
    brew-trust) run brew untrust --tap "$value" || status=1 ;;
    *) return 0 ;;    # system packages go in one command: remove_packages
  esac
  if [ "$status" = 0 ]; then forget "$kind" "$value"; else NOT_REMOVED=$((NOT_REMOVED + 1)); fi
}

# Lists, in one line each, the Homebrew packages and the system packages that
# came with the packages asked for.
list_dependencies() {
  local manager
  if have brew && [ -n "$(recorded brew-dep)" ] && ! homebrew_goes; then
    list_dependency_count "$(lines_both "$(recorded_sorted brew-dep)" "$(brew_formulae)" | grep -c .)" "Homebrew package"
  fi
  manager=$(package_manager)
  [ -n "$manager" ] || return 0
  list_dependency_count "$(lines_both "$(recorded_sorted "$manager-dep")" "$(installed_packages)" | grep -c .)" package
}

list_dependency_count() {
  case "$1" in
    0) return 0 ;;
    1) info "  - 1 $2 that came with those as a dependency, if nothing else needs it" ;;
    *) info "  - $1 ${2}s that came with those as dependencies: each that nothing else needs" ;;
  esac
  TO_REMOVE=$((TO_REMOVE + 1))
}

# Removes, of the Homebrew formulae that came with the formulae this script
# asked for, each that nothing needs any more. Homebrew says which formulae
# nothing needs; none that is not in the record goes.
remove_brew_dependencies() {
  local installed unused="" round count
  [ -n "$(recorded brew-dep)" ] || return 0
  # With Homebrew gone they are gone. With a Homebrew that was to go and is
  # still there, they stay as they are.
  if ! have brew; then forget_packages brew-dep "$(recorded_sorted brew-dep)"; return 0; fi
  ! homebrew_goes || return 0
  for round in 1 2 3; do
    # What is gone already is forgotten.
    installed=$(brew_formulae) || return 0
    forget_packages brew-dep "$(lines_new "$installed" "$(recorded_sorted brew-dep)")"
    unused=$(lines_both "$(recorded_sorted brew-dep)" "$(brew_unused)")
    [ -n "$unused" ] || break
    # shellcheck disable=SC2086
    run brew uninstall $unused || break
  done
  if [ -n "$unused" ]; then
    installed=$(brew_formulae) || return 0
    forget_packages brew-dep "$(lines_new "$installed" "$(recorded_sorted brew-dep)")"
    unused=$(lines_both "$(recorded_sorted brew-dep)" "$(brew_unused)")
  fi
  if [ -n "$unused" ]; then
    # shellcheck disable=SC2086
    info "  ! Still installed:" $unused
    NOT_REMOVED=$((NOT_REMOVED + 1))
  elif [ -z "$(recorded brew)" ]; then
    # What is still there belongs to the software that uses it now.
    count=$(recorded brew-dep | grep -c .)
    if [ "$count" != 0 ]; then
      info "  $count of the Homebrew packages that came with them stay: other software on this host uses them now."
      forget_packages brew-dep "$(recorded_sorted brew-dep)"
    fi
  fi
}

# What apt would remove on the command it is given, as sorted package names.
apt_would_remove() {
  LC_ALL=C apt-get -s "$@" 2>/dev/null | awk '$1 == "Purg" || $1 == "Remv" { print $2 }' | LC_ALL=C sort -u
}

# The words of the apt command that removes the packages named, with their
# configuration files, and what nothing needs any more. APT_KEEP has the
# options that make apt keep packages nothing needs.
apt_removal() {
  # shellcheck disable=SC2086
  if [ $# = 0 ]; then echo autoremove --purge $APT_KEEP; else echo purge --auto-remove $APT_KEEP "$@"; fi
}

# Sets PKG_GOES to the recorded packages that apt can remove without removing
# any other package, and APT_KEEP with it. $1 has the packages this script
# asked for, $2 all it installed. Fails where it finds no such set.
plan_apt_removal() {
  local names="$1" ours="$2" plan others="" p stay pass
  # shellcheck disable=SC2046,SC2086
  if ! LC_ALL=C apt-get -s $(apt_removal $names) >/dev/null 2>&1; then
    info "  ! apt does not say what it would remove (apt-get -s fails)."
    return 1
  fi
  for pass in 1 2; do
    # apt removes every package that was installed as a dependency and that
    # nothing needs. Those this script did not install stay: apt is told to
    # keep them, by name. (A package of another architecture shows as
    # name:architecture.)
    APT_KEEP=""
    # shellcheck disable=SC2046,SC2086
    others=$(lines_new "$ours" "$(apt_would_remove $(apt_removal $names))")
    for p in $others; do
      APT_KEEP="$APT_KEEP -o APT::NeverAutoRemove::=^$(printf '%s' "${p%%:*}" | sed 's/[.+]/\\&/g')\$"
    done
    # shellcheck disable=SC2046,SC2086
    plan=$(apt_would_remove $(apt_removal $names))
    others=$(lines_new "$ours" "$plan")
    if [ -z "$others" ]; then PKG_GOES=$plan; return 0; fi
    [ "$pass" = 1 ] || break
    # What apt would still remove needs a package this script asked for. That
    # package stays, and with it what it needs.
    stay=""
    for p in $names; do
      [ -z "$(lines_new "$ours" "$(apt_would_remove purge "$p")")" ] || stay="$stay $p"
    done
    [ -n "$stay" ] || break
    # shellcheck disable=SC2086
    names=$(lines_new "$(printf '%s\n' $stay | LC_ALL=C sort -u)" "$names")
  done
  # shellcheck disable=SC2086
  info "  ! apt would also remove packages that this script did not install:" $others
  return 1
}

# Sets PKG_GOES to those of the packages in $1 that rpm can remove without
# breaking a package that stays. Fails where it finds no such set.
plan_rpm_removal() {
  local set="$1" out stay cap p
  while [ -n "$set" ]; do
    # shellcheck disable=SC2086
    out=$(LC_ALL=C rpm -e --test $set 2>&1) && break
    # "	libonig.so.5()(64bit) is needed by (installed) jq-1.8.2-5.fc45.aarch64":
    # the package that provides it stays, and then what that package needs.
    stay=$(printf '%s\n' "$out" |
      sed -n 's/^[[:space:]]*\([^[:space:]]*\).* is needed by (installed) .*/\1/p' | LC_ALL=C sort -u |
      while IFS= read -r cap; do
        p=$(rpm -q --whatprovides "$cap" --qf '%{NAME}\n' 2>/dev/null) && printf '%s\n' "$p"
      done | LC_ALL=C sort -u)
    stay=$(lines_both "$set" "$stay")
    if [ -z "$stay" ]; then
      info "  ! rpm does not say which of the packages other software needs:"
      printf '%s\n' "$out" | sed -e 's/^[[:space:]]*/      /' -e 5q
      return 1
    fi
    set=$(lines_new "$stay" "$set")
  done
  PKG_GOES=$set
}

# Sets PKG_GOES to those of the packages in $1 that pacman removes when it is
# told to leave out what a package that stays needs (--unneeded). Fails where
# pacman does not say.
plan_pacman_removal() {
  local out
  # shellcheck disable=SC2086
  if ! out=$(pacman -Ru --print --print-format '%n' $1 2>/dev/null); then
    info "  ! pacman does not say what it would remove (pacman -Ru --print fails)."
    return 1
  fi
  # Where nothing can go it prints a sentence, not names.
  PKG_GOES=$(lines_both "$1" "$(printf '%s\n' "$out" | LC_ALL=C sort -u)")
}

# Removes the recorded system packages: those this script asked for, and of
# those that came with them each that nothing else on the host needs. No
# package that is not in the record goes. The package manager gets them in one
# command; without --yes it shows what goes and asks.
remove_packages() {
  local manager all names ours p targets yes="" left count
  manager=$(package_manager)
  [ -n "$manager" ] || return 0
  # What is gone already is forgotten.
  all=$(installed_packages)
  forget_packages "$manager" "$(lines_new "$all" "$(recorded_sorted "$manager")")"
  forget_packages "$manager-dep" "$(lines_new "$all" "$(recorded_sorted "$manager-dep")")"
  names=$(recorded_sorted "$manager")
  ours=$({ recorded "$manager"; recorded "$manager-dep"; } | LC_ALL=C sort -u)
  [ -n "$ours" ] || return 0

  # Which of them can go: the package manager is asked, and nothing changes yet.
  PKG_GOES=""; APT_KEEP=""
  case "$manager" in
    apt) plan_apt_removal "$names" "$ours" ;;
    dnf|zypper) plan_rpm_removal "$ours" ;;
    pacman) plan_pacman_removal "$ours" ;;
  esac || {
    info "    No package was removed."
    NOT_REMOVED=$((NOT_REMOVED + 1))
    return 0
  }
  for p in $(lines_new "$PKG_GOES" "$names"); do
    info "  ! The package $p stays: a package that this script did not install needs it."
    NOT_REMOVED=$((NOT_REMOVED + 1))
  done

  if [ -n "$PKG_GOES" ]; then
    # Podman's storage is not in a package, and only Podman can remove it.
    if [ -n "$(lines_both "$PKG_GOES" podman)" ]; then
      run podman system reset --force ||
        info "  Podman's storage could not be removed; it stays (~/.local/share/containers)."
    fi
    # Configuration files go too: nothing of these packages was there before.
    # shellcheck disable=SC2046,SC2086
    case "$manager" in
      apt)    [ "$ASSUME_YES" = 0 ] || yes=-y
              as_root apt-get $yes $(apt_removal $(lines_both "$names" "$PKG_GOES")) ;;
      dnf)    [ "$ASSUME_YES" = 0 ] || yes=-y
              as_root dnf remove $yes --setopt=clean_requirements_on_remove=False $PKG_GOES ;;
      pacman) [ "$ASSUME_YES" = 0 ] || yes=--noconfirm
              as_root pacman -Rn $yes $PKG_GOES ;;
      zypper) [ "$ASSUME_YES" = 0 ] || yes=--non-interactive
              as_root zypper $yes remove $PKG_GOES ;;
    esac
  fi

  all=$(installed_packages)
  forget_packages "$manager" "$(lines_new "$all" "$(recorded_sorted "$manager")")"
  forget_packages "$manager-dep" "$(lines_new "$all" "$(recorded_sorted "$manager-dep")")"
  left=$(lines_both "$PKG_GOES" "$all")
  if [ -n "$left" ]; then
    # shellcheck disable=SC2086
    info "  ! Still installed:" $left
    NOT_REMOVED=$((NOT_REMOVED + 1))
  elif [ -z "$(recorded "$manager")" ]; then
    # Of what came with the packages asked for, what is still there belongs to
    # the software that uses it now. (apt also keeps what an installed package
    # recommends.)
    count=$(recorded "$manager-dep" | grep -c .)
    if [ "$count" != 0 ]; then
      info "  $count of the packages that came with them stay: other software on this host uses them now."
      forget_packages "$manager-dep" "$(recorded_sorted "$manager-dep")"
    fi
  fi
}

list_left() {
  local kind="$1" value="$2" count
  if ! entry_present "$kind" "$value"; then
    [ "$MODE" = check ] || forget "$kind" "$value"
    return 0
  fi
  if [ "$LEFT" = 0 ]; then
    info ""
    info "Left in place, for you to remove: other software can have come to use it, and removing it takes root rights."
  fi
  LEFT=$((LEFT + 1))
  case "$kind" in
    xcode-select)
      info "  - The selected developer directory. It was $value before Homebrew's installer"
      info "    selected $(xcode-select -p 2>/dev/null). To select it again:"
      info "      sudo xcode-select --switch $value" ;;
    xcode-clt)
      info "  - The Xcode Command Line Tools, installed for this script. To remove them:"
      info "      sudo rm -rf /Library/Developer/CommandLineTools" ;;
  esac
}

uninstall() {
  if [ -z "$(grep -v '^#' "$RECORD" 2>/dev/null)" ]; then
    info "Nothing to remove: this script has no record of installing anything on this host."
    info "(It keeps the record in $RECORD.)"
    exit 0
  fi
  # Homebrew is not to remove on its own what it holds to be unused: that
  # could be a formula this script did not install.
  export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 HOMEBREW_NO_AUTOREMOVE=1
  TO_REMOVE=0; NOT_REMOVED=0; LEFT=0

  info "By its record ($RECORD), this script installed:"
  # shellcheck disable=SC2086
  each_entry list_entry $REMOVE_ORDER
  list_dependencies
  if [ "$MODE" = check ]; then
    # shellcheck disable=SC2086
    each_entry list_left $LEAVE_ORDER
    info ""
    info "Nothing was removed. ./setup.sh --uninstall removes it."
    exit 0
  fi

  if homebrew_needs_terminal; then
    info ""
    info "Homebrew's uninstaller asks for an administrator's password, and there is no terminal to"
    info "ask in. Run ./setup.sh --uninstall from a terminal. Nothing was removed."
    exit 1
  fi
  if [ "$TO_REMOVE" != 0 ]; then
    info ""
    confirm "Remove all of this?" || exit 1
  fi
  # shellcheck disable=SC2086
  each_entry remove_entry $REMOVE_ORDER
  remove_brew_dependencies
  remove_packages
  # shellcheck disable=SC2086
  each_entry list_left $LEAVE_ORDER

  # A record with nothing left in it goes too.
  if [ -z "$(grep -v '^#' "$RECORD" 2>/dev/null)" ]; then
    rm -f "$RECORD"
    rmdir "$(dirname "$RECORD")" 2>/dev/null
  fi
  info ""
  if [ "$NOT_REMOVED" != 0 ]; then
    info "Not everything could be removed; see above. What is left stays in the record."
    exit 1
  fi
  info "Removed what this script installed. This repository is untouched, with what the"
  info "launcher built in it (build/)."
  exit 0
}

# ------------------------------------------------------------------- main ---

[ "$UNINSTALL" = 0 ] || uninstall

info "Checking host dependencies"
run_checks

if [ -z "$MISSING" ] && [ -z "$OPTIONAL" ]; then
  info ""
  info "All host dependencies are present."
  exit 0
fi

RERUN="./setup.sh"
[ "$EXPERIMENTAL_QEMU" = 0 ] || RERUN="./setup.sh --experimental-qemu"

if [ "$MODE" = check ]; then
  info ""
  if [ -z "$MISSING" ]; then
    info "All host dependencies are present. Optional extras not installed:$OPTIONAL. Run $RERUN to install."
    exit 0
  fi
  info "Missing:$MISSING. Run $RERUN to install."
  exit 1
fi

info ""
[ -z "$MISSING" ] || info "Missing:$MISSING"
[ -z "$OPTIONAL" ] || info "Optional:$OPTIONAL"
if [ "$OS" = Darwin ]; then
  if [ -n "$MISSING" ]; then
    info "These are installed with Homebrew (installed first if absent); the container"
    info "engine is Colima unless Docker is already installed."
  fi
  if is_optional experimental-qemu; then
    info "The experimental QEMU is third-party software. Homebrew is told to trust the tap"
    info "$EXP_TAP and builds QEMU, ANGLE, virglrenderer and libepoxy from"
    info "source, which needs the Xcode app and takes some minutes. The build is installed"
    info "beside Homebrew's QEMU, and the launcher uses it only when EMU_QEMU_DIR names it."
  fi
else
  info "These are installed with the system package manager and need root (sudo)."
fi
if is_optional experimental-qemu; then
  # Asked for by name, so not installing it is not a success.
  if [ -n "$MISSING" ]; then
    confirm "Install the missing dependencies and the experimental QEMU?" || exit 1
  else
    confirm "Build and install the experimental QEMU?" || exit 1
  fi
elif [ -n "$MISSING" ]; then
  confirm "Install the missing dependencies?" || exit 1
else
  confirm "Install the optional extras?" || exit 0
fi

info ""
if [ "$OS" = Darwin ]; then install_macos; else install_linux; fi
install_status=$?

info ""
info "Re-checking host dependencies"
run_checks
info ""
if [ -z "$MISSING" ]; then
  info "All host dependencies are present."
  [ -z "$OPTIONAL" ] || info "Optional extras still not installed:$OPTIONAL."
  if is_optional experimental-qemu; then
    info "The experimental QEMU was asked for and is not installed; see the output above."
    exit 1
  fi
  exit 0
fi
info "Still missing:$MISSING"
[ "$install_status" = 0 ] || info "The installation step reported an error; see the output above."
exit 1
