<#
.SYNOPSIS
  Host setup for Windows.

.DESCRIPTION
  Checks every host dependency the emulator needs and installs the ones that
  are missing. The Linux and macOS equivalent is setup.sh.

    .\setup.ps1           check, then install what is missing (asks first)
    .\setup.ps1 -Yes      same, without asking
    .\setup.ps1 -Check    check only; exit 1 if anything is missing

  Host dependencies:
    Python >= 3.9             runs the launcher (emu.cmd)
    QEMU system emulators     VM mode: host-native, ARM64 and ARM32 guests
    Windows Hypervisor Platform   host-native VM mode (WHPX)
    container runtime         container mode and target image builds
    foreign-arch emulation    building ARM32/ARM64 target images

  Packages are installed with winget. Enabling Windows features needs an
  elevated (Administrator) PowerShell and a restart.
#>
[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$script:Missing = @()
$script:RestartNeeded = $false

function Write-Ok($text)      { Write-Host "  [ ok ]  $text" }
function Write-Missing($key, $text) { Write-Host "  [MISS]  $text"; $script:Missing += $key }
function Write-Warn($text)    { Write-Host "  [warn]  $text" }
function Test-Missing($key)   { $script:Missing -contains $key }
function Test-Command($name)  { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Installers do not update the PATH of a shell that is already open.
function Update-Path {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  $extra = @("$env:ProgramFiles\qemu", "$env:ProgramFiles\RedHat\Podman", "$env:ProgramFiles\Docker\Docker\resources\bin")
  $env:Path = (@($machine, $user) + ($extra | Where-Object { Test-Path $_ })) -join ';'
}

function Get-HostArch {
  switch ($env:PROCESSOR_ARCHITECTURE) {
    'AMD64' { 'x86_64' }
    'ARM64' { 'arm64' }
    default { throw "Unsupported host CPU architecture: $env:PROCESSOR_ARCHITECTURE" }
  }
}

# ----------------------------------------------------------------- checks ---

# Returns the command that runs a real Python >= 3.9, or $null. The python.exe
# that ships with Windows is a Store launcher stub, so run it to find out.
function Find-Python {
  foreach ($candidate in @(@('py', '-3'), @('python'), @('python3'))) {
    $exe = $candidate[0]
    if (-not (Test-Command $exe)) { continue }
    $rest = @($candidate | Select-Object -Skip 1)
    try {
      $version = & $exe @rest -c "import sys; print('%d.%d.%d' % sys.version_info[:3]) if sys.version_info >= (3, 9) else sys.exit(1)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $version) { return @{ Command = ($candidate -join ' '); Version = $version } }
    } catch { }
  }
  return $null
}

function Test-PythonDep {
  $python = Find-Python
  if ($python) { Write-Ok "Python $($python.Version) ($($python.Command))" }
  else { Write-Missing 'python' 'Python >= 3.9' }
}

function Test-QemuDep {
  $native = if ((Get-HostArch) -eq 'arm64') { 'qemu-system-aarch64' } else { 'qemu-system-x86_64' }
  $absent = @($native, 'qemu-system-aarch64', 'qemu-system-arm') | Select-Object -Unique | Where-Object { -not (Test-Command $_) }
  if ($absent) { Write-Missing 'qemu' "QEMU system emulators: $($absent -join ' ')" }
  else {
    $version = (& $native --version | Select-Object -First 1)
    Write-Ok "QEMU: $version (native, ARM64 and ARM32 system emulators)"
  }
}

# Host graphics acceleration for VM mode needs a QEMU with the GPU-accelerated
# display device and a display backend that renders without a window. Without
# them graphics are emulated, so this is a note, not a missing dependency.
function Test-GraphicsNote {
  $native = if ((Get-HostArch) -eq 'arm64') { 'qemu-system-aarch64' } else { 'qemu-system-x86_64' }
  if (-not (Test-Command $native)) { return }
  $devices = (& $native -device help 2>&1) -join "`n"
  $displays = (& $native -display help 2>&1) -join "`n"
  if ($devices -match 'virtio-gpu-gl-pci' -and $displays -match 'egl-headless') {
    Write-Ok 'host graphics acceleration for VM mode (QEMU with virglrenderer)'
  } else {
    Write-Host '  [note]  host graphics acceleration for VM mode: this QEMU build has none; graphics are emulated'
  }
}

function Test-AccelDep {
  # Reading optional-feature state needs elevation; fall back to a plain hint.
  if (Test-Admin) {
    $feature = Get-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -ErrorAction SilentlyContinue
    if ($feature -and $feature.State -eq 'Enabled') { Write-Ok 'hardware virtualization: Windows Hypervisor Platform (WHPX)' }
    else { Write-Missing 'whpx' 'Windows Hypervisor Platform feature (WHPX) is not enabled' }
  } else {
    $present = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
    if ($present) { Write-Warn 'a hypervisor is running, but confirming the Windows Hypervisor Platform feature needs an elevated shell' }
    else { Write-Missing 'whpx' 'Windows Hypervisor Platform feature (WHPX) is not enabled' }
  }
}

$script:ContainerCli = $null
function Test-ContainerDep {
  $script:ContainerCli = $null
  foreach ($cli in @('docker', 'podman')) {
    if (-not (Test-Command $cli)) { continue }
    & $cli info *> $null
    if ($LASTEXITCODE -eq 0) { $script:ContainerCli = $cli; break }
  }
  if ($script:ContainerCli) {
    Write-Ok "container runtime: $(& $script:ContainerCli --version | Select-Object -First 1)"
  } elseif ((Test-Command 'docker') -or (Test-Command 'podman')) {
    Write-Missing 'engine' 'container engine: a container CLI is installed but no engine is running'
  } else {
    Write-Missing 'container' 'container runtime (docker or podman)'
  }
}

# Target images for ARM are built by running ARM binaries through user-mode
# emulation registered in the container engine's Linux kernel.
function Get-ForeignArchGaps {
  $need = if ((Get-HostArch) -eq 'arm64') { @('qemu-arm') } else { @('qemu-aarch64', 'qemu-arm') }
  $registered = ''
  try {
    if ($script:ContainerCli -eq 'podman') { $registered = (& podman machine ssh ls /proc/sys/fs/binfmt_misc 2>$null) -join "`n" }
    else {
      $platforms = ((& docker buildx inspect 2>$null) | Select-String '^Platforms:').ToString()
      $registered = ''
      if ($platforms -match 'linux/arm64') { $registered += "qemu-aarch64`n" }
      if ($platforms -match 'linux/arm/v7') { $registered += "qemu-arm`n" }
    }
  } catch { }
  $need | Where-Object { $registered -notmatch "(?m)^$_\b" }
}

function Test-ForeignArchDep {
  if (-not $script:ContainerCli) { return }
  $gaps = @(Get-ForeignArchGaps)
  if ($gaps.Count -eq 0) { Write-Ok 'foreign-architecture emulation for target image builds' }
  else { Write-Missing 'binfmt' "foreign-architecture emulation (binfmt) for: $($gaps -join ' ')" }
}

function Invoke-Checks {
  $script:Missing = @()
  Update-Path
  Write-Host "Host: Windows $(Get-HostArch)"
  Test-PythonDep
  Test-QemuDep
  Test-GraphicsNote
  Test-AccelDep
  Test-ContainerDep
  Test-ForeignArchDep
}

# ---------------------------------------------------------------- install ---

function Invoke-Step {
  param([string]$Exe, [string[]]$Arguments)
  Write-Host "  + $Exe $($Arguments -join ' ')"
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Exe exited with code $LASTEXITCODE" }
}

function Install-WingetPackage($id) {
  Invoke-Step winget @('install', '--exact', '--id', $id, '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity')
}

function Install-Missing {
  if (-not (Test-Command 'winget')) {
    Write-Host 'Registering winget (App Installer)...'
    Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe
    Update-Path
    if (-not (Test-Command 'winget')) {
      throw 'winget is not available. Install "App Installer" from the Microsoft Store, then run setup.ps1 again.'
    }
  }

  if (Test-Missing 'python') { Install-WingetPackage 'Python.Python.3.13' }
  if (Test-Missing 'qemu')   { Install-WingetPackage 'SoftwareFreedomConservancy.QEMU' }

  if (Test-Missing 'whpx') {
    if (Test-Admin) {
      Write-Host '  + Enable-WindowsOptionalFeature HypervisorPlatform'
      $result = Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All -NoRestart
      if ($result.RestartNeeded) { $script:RestartNeeded = $true }
    } else {
      Write-Host '  ! Enabling the Windows Hypervisor Platform needs an elevated PowerShell; run setup.ps1 as Administrator.'
    }
  }

  if (Test-Missing 'container') {
    # Podman runs its engine in WSL 2.
    & wsl --status *> $null
    if ($LASTEXITCODE -ne 0) {
      if (Test-Admin) {
        Invoke-Step wsl @('--install', '--no-distribution')
        $script:RestartNeeded = $true
      } else {
        Write-Host '  ! Installing WSL 2 needs an elevated PowerShell; run setup.ps1 as Administrator.'
      }
    }
    Install-WingetPackage 'RedHat.Podman'
    Update-Path
  }

  if (-not $script:RestartNeeded) {
    if ((Test-Command 'podman') -and -not (Test-Command 'docker')) {
      & podman info *> $null
      if ($LASTEXITCODE -ne 0) {
        $machines = & podman machine list --format '{{.Name}}' 2>$null
        if (-not $machines) { Invoke-Step podman @('machine', 'init') }
        Invoke-Step podman @('machine', 'start')
      }
      $script:ContainerCli = 'podman'
    } elseif (Test-Command 'docker') {
      & docker info *> $null
      if ($LASTEXITCODE -ne 0) {
        $desktop = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
        if (Test-Path $desktop) {
          Write-Host '  + starting Docker Desktop'
          Start-Process $desktop
          for ($i = 0; $i -lt 60; $i++) { & docker info *> $null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 2 }
        }
      }
      & docker info *> $null
      if ($LASTEXITCODE -eq 0) { $script:ContainerCli = 'docker' }
    }

    if ($script:ContainerCli -and @(Get-ForeignArchGaps).Count -gt 0) {
      Invoke-Step $script:ContainerCli @('run', '--rm', '--privileged', 'docker.io/tonistiigi/binfmt', '--install', 'arm,arm64')
    }
  }
}

# ------------------------------------------------------------------- main ---

Write-Host 'Checking host dependencies'
Invoke-Checks

if ($script:Missing.Count -eq 0) {
  Write-Host "`nAll host dependencies are present."
  exit 0
}

if ($Check) {
  Write-Host "`nMissing: $($script:Missing -join ' '). Run .\setup.ps1 to install."
  exit 1
}

Write-Host "`nMissing: $($script:Missing -join ' ')"
Write-Host 'These are installed with winget; the container runtime is Podman unless Docker is already installed.'
if (-not $Yes) {
  if (-not [Environment]::UserInteractive) { Write-Host 'Not running interactively; re-run with -Yes to install.'; exit 1 }
  $reply = Read-Host 'Install the missing dependencies? [y/N]'
  if ($reply -notmatch '^(y|yes)$') { exit 1 }
}

Write-Host ''
$installError = $null
try { Install-Missing } catch { $installError = $_ }

Write-Host "`nRe-checking host dependencies"
Invoke-Checks
Write-Host ''
if ($script:RestartNeeded) {
  Write-Host 'Restart Windows to finish enabling the features above, then run .\setup.ps1 again.'
}
if ($script:Missing.Count -eq 0) {
  Write-Host 'All host dependencies are present.'
  exit 0
}
Write-Host "Still missing: $($script:Missing -join ' ')"
if ($installError) { Write-Host "The installation step failed: $installError" }
exit 1
