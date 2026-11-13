#!/usr/bin/env bash
# Host setup for Linux and macOS.
#
# Checks every host dependency the emulator needs and installs the ones that
# are missing. The Windows equivalent is setup.ps1.
#
#   ./setup.sh           check, then install what is missing (asks first)
#   ./setup.sh --yes     same, without asking
#   ./setup.sh --check   check only; exit 1 if anything is missing
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
for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    -y|--yes) ASSUME_YES=1 ;;
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
  check_audio
  check_accel
  check_container
  check_foreign_arch
}

# ---------------------------------------------------------------- install ---

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  if [ ! -t 0 ]; then
    info "Not running interactively; re-run with --yes to install."
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
    run xcode-select --install || true
    info "  Finish the installation dialog, then run ./setup.sh again."
    return 1
  fi

  if ! have brew; then
    info "Installing Homebrew (https://brew.sh), which asks for your password..."
    local installer=https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh
    if [ -t 0 ]; then
      /bin/bash -c "$(curl -fsSL "$installer")" || return 1
    else
      NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL "$installer")" || {
        info "  Homebrew needs an interactive terminal for the password prompt."
        info "  Run ./setup.sh from a terminal."
        return 1
      }
    fi
    for d in /opt/homebrew/bin /usr/local/bin; do
      [ -x "$d/brew" ] && eval "$("$d/brew" shellenv)"
    done
    have brew || { info "  Homebrew installation did not produce a brew command."; return 1; }
  fi

  local pkgs=""
  is_missing python && pkgs="$pkgs python"
  is_missing qemu && pkgs="$pkgs qemu"
  if is_missing container; then pkgs="$pkgs colima docker docker-buildx"; fi
  if is_missing buildx; then pkgs="$pkgs docker-buildx"; fi
  if is_missing engine && ! have colima && ! [ -d /Applications/Docker.app ]; then pkgs="$pkgs colima"; fi
  if [ -n "$pkgs" ]; then
    # shellcheck disable=SC2086
    HOMEBREW_NO_AUTO_UPDATE=1 run brew install $pkgs || return 1
  fi

  # Homebrew installs buildx as a CLI plugin outside docker's search path.
  if have docker && ! docker buildx version >/dev/null 2>&1; then
    local plugin; plugin="$(brew --prefix)/opt/docker-buildx/bin/docker-buildx"
    if [ -x "$plugin" ]; then
      run mkdir -p "$HOME/.docker/cli-plugins"
      run ln -sfn "$plugin" "$HOME/.docker/cli-plugins/docker-buildx"
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
      run docker run --rm --privileged tonistiigi/binfmt --install "$emulators" >/dev/null || return 1
    fi
  fi
}

install_linux() {
  local native_pkg cli=""
  have docker && cli=docker
  have podman && cli=podman

  if have apt-get; then
    local pkgs=""
    is_missing python && pkgs="$pkgs python3"
    is_missing qemu && pkgs="$pkgs qemu-system-x86 qemu-system-arm qemu-utils"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-user-static binfmt-support"
    if [ -n "$pkgs" ]; then
      as_root apt-get update || return 1
      # shellcheck disable=SC2086
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $pkgs || return 1
    fi
  elif have dnf; then
    local pkgs=""
    is_missing python && pkgs="$pkgs python3"
    is_missing qemu && pkgs="$pkgs qemu-system-x86 qemu-system-aarch64 qemu-system-arm qemu-img"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-user-static"
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || as_root dnf install -y $pkgs || return 1
  elif have pacman; then
    local pkgs=""
    is_missing python && pkgs="$pkgs python"
    is_missing qemu && pkgs="$pkgs qemu-system-x86 qemu-system-aarch64 qemu-system-arm qemu-img"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-user-static qemu-user-static-binfmt"
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || as_root pacman -S --needed --noconfirm $pkgs || return 1
  elif have zypper; then
    local pkgs=""
    is_missing python && pkgs="$pkgs python3"
    is_missing qemu && pkgs="$pkgs qemu-x86 qemu-arm qemu-tools"
    is_missing container && pkgs="$pkgs podman"
    is_missing binfmt && pkgs="$pkgs qemu-linux-user"
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || as_root zypper --non-interactive install $pkgs || return 1
  else
    info "No supported package manager found (apt-get, dnf, pacman or zypper)."
    info "Install these yourself: python3 >= 3.9, QEMU system emulators for $ARCH, aarch64 and arm,"
    info "podman or docker, and qemu-user-static with binfmt_misc."
    return 1
  fi

  # Optional: QEMU's OpenGL modules. A failure here leaves graphics emulated.
  if ! qemu_has_gl && [ -n "$(linux_gl_packages)" ]; then
    local gl_status=0
    # shellcheck disable=SC2046
    if have apt-get; then
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $(linux_gl_packages) || gl_status=1
    elif have dnf; then
      as_root dnf install -y $(linux_gl_packages) || gl_status=1
    elif have pacman; then
      as_root pacman -S --needed --noconfirm $(linux_gl_packages) || gl_status=1
    fi
    [ "$gl_status" = 0 ] || info "  Could not install QEMU's OpenGL modules; VM mode will emulate graphics."
  fi

  # Optional: a program to play the target's sound with.
  if ! have_audio_player && [ -n "$(linux_audio_packages)" ]; then
    local audio_status=0
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
    [ "$audio_status" = 0 ] || info "  Could not install an audio player; the target's sound will not be heard on the host."
  fi

  if is_missing binfmt && have systemctl; then
    as_root systemctl restart systemd-binfmt.service 2>/dev/null || true
  fi
  if is_missing engine && have docker && have systemctl; then
    as_root systemctl enable --now docker || true
    if ! docker info >/dev/null 2>&1; then
      as_root usermod -aG docker "$(id -un)" && info "  Added $(id -un) to the docker group; log out and back in for it to apply."
    fi
  fi
  if is_missing kvm; then
    local group; group=$(stat -c %G /dev/kvm 2>/dev/null || echo kvm)
    as_root usermod -aG "$group" "$(id -un)" && info "  Added $(id -un) to the $group group; log out and back in for it to apply."
  fi
}

# ------------------------------------------------------------------- main ---

info "Checking host dependencies"
run_checks

if [ -z "$MISSING" ] && [ -z "$OPTIONAL" ]; then
  info ""
  info "All host dependencies are present."
  exit 0
fi

if [ "$MODE" = check ]; then
  info ""
  if [ -z "$MISSING" ]; then
    info "All host dependencies are present. Optional extras not installed:$OPTIONAL. Run ./setup.sh to install."
    exit 0
  fi
  info "Missing:$MISSING. Run ./setup.sh to install."
  exit 1
fi

info ""
[ -z "$MISSING" ] || info "Missing:$MISSING"
[ -z "$OPTIONAL" ] || info "Optional:$OPTIONAL"
if [ "$OS" = Darwin ]; then
  info "These are installed with Homebrew (installed first if absent); the container"
  info "engine is Colima unless Docker is already installed."
else
  info "These are installed with the system package manager and need root (sudo)."
fi
if [ -n "$MISSING" ]; then
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
  exit 0
fi
info "Still missing:$MISSING"
[ "$install_status" = 0 ] || info "The installation step reported an error; see the output above."
exit 1
