<#
.SYNOPSIS
  Host setup for Windows.

.DESCRIPTION
  Checks every host dependency the emulator needs and installs the ones that
  are missing. The Linux and macOS equivalent is setup.sh.

    .\setup.ps1           check, then install what is missing (asks first)
    .\setup.ps1 -Yes      same, without asking
    .\setup.ps1 -Check    check only; exit 1 if anything is missing
    .\setup.ps1 -Uninstall
                          remove what this script installed on this host (asks
                          first; with -Check it only lists what that is)

  The script keeps a record of what it installs: only of what was not there
  before. -Uninstall removes what the record lists and nothing else. The
  record is %LOCALAPPDATA%\emulator-evaluation\setup-installed.

  setup.cmd runs this script where the PowerShell execution policy does not
  allow scripts, which is the default on Windows: setup.cmd -Check

  Host dependencies:
    Python >= 3.9             runs the launcher (emu.cmd)
    QEMU system emulators     VM mode: host-native, ARM64 and ARM32 guests
    Windows Hypervisor Platform   host-native VM mode (WHPX)
    container runtime         container mode and target image builds
    foreign-arch emulation    building ARM32/ARM64 target images

  The container runtime is Podman unless Docker is installed already. Where
  both are, Docker is used when its engine answers; set the environment
  variable EMU_CONTAINER_RUNTIME to podman or docker to choose. A Podman
  machine this script creates is rootful: a rootless one can neither register
  the foreign-architecture emulation nor give a container CPUs of its own.

  Packages are installed with winget; an installer may ask for elevation.
  Enabling a Windows feature needs an elevated (Administrator) PowerShell and
  a restart. That is only needed when the Windows Hypervisor Platform cannot
  run a VM yet; where WSL 2 is installed it usually can.

  Runs in Windows PowerShell 5.1 and in PowerShell 7.
#>
[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Yes,
  [switch]$Uninstall
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

# Running other programs. Windows PowerShell turns what a program writes to
# stderr into error records once that stream is redirected, and the 'Stop'
# preference above would make the first of them fatal. These run a program
# with the preference relaxed; its exit code is in $LASTEXITCODE afterwards.

# What the program wrote to stdout, as one string.
function Get-Output {
  param([string]$Exe, [string[]]$Arguments = @())
  $ErrorActionPreference = 'Continue'
  (& $Exe @Arguments 2>$null | ForEach-Object { "$_" }) -join "`n"
}

# What the program wrote to stdout and stderr, as one string.
function Get-AllOutput {
  param([string]$Exe, [string[]]$Arguments = @())
  $ErrorActionPreference = 'Continue'
  (& $Exe @Arguments 2>&1 | ForEach-Object { "$_" }) -join "`n"
}

# Whether the program runs and exits with 0. Its output is discarded.
function Test-Run {
  param([string]$Exe, [string[]]$Arguments = @())
  $ErrorActionPreference = 'Continue'
  try { & $Exe @Arguments *> $null } catch { return $false }
  $LASTEXITCODE -eq 0
}

# Whether a container engine answers its CLI. A broken engine can leave the
# CLI waiting forever, so this gives up after a while, as the launcher does.
function Test-Engine {
  param([string]$Cli, [int]$Seconds = 60)
  $start = New-Object System.Diagnostics.ProcessStartInfo
  $start.FileName = (Get-Command $Cli).Source
  $start.Arguments = 'info'
  $start.UseShellExecute = $false
  $start.CreateNoWindow = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  $process = [System.Diagnostics.Process]::Start($start)
  # Take in what it prints, so that a full pipe cannot hold it up.
  $null = $process.StandardOutput.ReadToEndAsync()
  $null = $process.StandardError.ReadToEndAsync()
  if (-not $process.WaitForExit($Seconds * 1000)) {
    try { $process.Kill() } catch { }
    return $false
  }
  $process.ExitCode -eq 0
}

function Get-FirstLine($text) { @("$text" -split "`n")[0].Trim() }

# Installers do not update the PATH of a shell that is already open, and
# QEMU's installer does not put it on the PATH at all. The launcher looks in
# the same directories.
function Update-Path {
  $known = @("$env:ProgramFiles\qemu", "$env:ProgramFiles\RedHat\Podman", "$env:ProgramFiles\Docker\Docker\resources\bin") |
    Where-Object { Test-Path $_ }
  $registered = @([Environment]::GetEnvironmentVariable('Path', 'Machine'), [Environment]::GetEnvironmentVariable('Path', 'User')) -split ';'
  $current = @($env:Path -split ';')
  foreach ($directory in @($registered) + @($known)) {
    if ($directory -and $current -notcontains $directory) { $current += $directory }
  }
  $env:Path = $current -join ';'
}

function Get-HostArch {
  switch ($env:PROCESSOR_ARCHITECTURE) {
    'AMD64' { 'x86_64' }
    'ARM64' { 'arm64' }
    default { throw "Unsupported host CPU architecture: $env:PROCESSOR_ARCHITECTURE" }
  }
}

function Get-NativeQemu {
  if ((Get-HostArch) -eq 'arm64') { 'qemu-system-aarch64' } else { 'qemu-system-x86_64' }
}

# ----------------------------------------------------------------- record ---

# What this script installed on this host: a line "KIND VALUE" for each thing
# that was not there before the script put it there. -Uninstall goes by it.
$script:Record = $env:EMU_SETUP_RECORD
if (-not $script:Record) { $script:Record = Join-Path "$env:LOCALAPPDATA" 'emulator-evaluation\setup-installed' }

# The entries of the record, in the order they were recorded.
function Get-Recorded {
  if (-not (Test-Path $script:Record)) { return @() }
  @(Get-Content $script:Record | Where-Object { $_ -and $_ -notmatch '^#' })
}

function Add-Record {
  param([string]$Kind, [string]$Value = '-')
  $entry = "$Kind $Value"
  try {
    if (-not (Test-Path $script:Record)) {
      $null = New-Item -ItemType Directory -Force -Path (Split-Path $script:Record)
      Set-Content -Path $script:Record -Encoding ASCII -Value '# What setup.ps1 installed on this host. setup.cmd -Uninstall removes it.'
    }
    if (@(Get-Recorded) -notcontains $entry) { Add-Content -Path $script:Record -Encoding ASCII -Value $entry }
  } catch {
    Write-Warn "could not write to $($script:Record) that this script installed: $entry"
  }
}

function Remove-Record {
  param([string]$Kind, [string]$Value = '-')
  $rest = @(Get-Content $script:Record | Where-Object { $_ -ne "$Kind $Value" })
  Set-Content -Path $script:Record -Encoding ASCII -Value $rest
}

# Whether winget has a package installed.
function Test-WingetPackage($id) {
  Test-Run winget @('list', '--exact', '--id', $id, '--accept-source-agreements', '--disable-interactivity')
}

# ----------------------------------------------------------------- checks ---

# Returns the command that runs a real Python >= 3.9, or $null. These are the
# commands emu.cmd tries. The python.exe that ships with Windows is a Store
# launcher stub, so run it to find out.
function Find-Python {
  $script = "import sys; print('%d.%d.%d' % sys.version_info[:3]) if sys.version_info >= (3, 9) else sys.exit(1)"
  foreach ($candidate in @(@('py', '-3'), @('python'))) {
    $exe = $candidate[0]
    if (-not (Test-Command $exe)) { continue }
    $rest = @($candidate | Select-Object -Skip 1)
    try {
      $version = Get-Output $exe ($rest + @('-c', $script))
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
  $native = Get-NativeQemu
  $absent = @($native, 'qemu-system-aarch64', 'qemu-system-arm') | Select-Object -Unique | Where-Object { -not (Test-Command $_) }
  if ($absent) { Write-Missing 'qemu' "QEMU system emulators: $($absent -join ' ')" }
  else {
    $version = Get-FirstLine (Get-Output $native @('--version'))
    Write-Ok "QEMU: $version (native, ARM64 and ARM32 system emulators)"
  }
}

# Host graphics acceleration for VM mode needs a QEMU with the GPU-accelerated
# display device and a display backend that renders without a window. Without
# them graphics are emulated, so this is a note, not a missing dependency.
# QEMU for Windows has both, but that display stays black (seen with QEMU
# 11.1.0). The launcher therefore uses host acceleration on Windows only when
# the display is shown in a window (emu run --window).
function Test-GraphicsNote {
  $native = Get-NativeQemu
  if (-not (Test-Command $native)) { return }
  $devices = Get-AllOutput $native @('-device', 'help')
  $displays = Get-AllOutput $native @('-display', 'help')
  if ($devices -match 'virtio-gpu-gl-pci' -and $displays -match 'egl-headless') {
    Write-Host '  [note]  host graphics acceleration for VM mode: available when the display is shown in a window (emu run --window); without a window graphics are emulated'
  } else {
    Write-Host '  [note]  host graphics acceleration for VM mode: this QEMU build has none; graphics are emulated'
  }
}

# Whether the Windows Hypervisor Platform can run a VM right now: $true,
# $false, or $null when the platform's API could not be asked. This is the
# question QEMU asks. The state of the optional Windows feature does not
# answer it: the API also works when the feature WSL 2 uses keeps the
# hypervisor running, and does not work yet while a newly enabled feature
# waits for a restart.
function Test-Whpx {
  try {
    if (-not ('EmuSetup.Whp' -as [type])) {
      Add-Type -Namespace EmuSetup -Name Whp -MemberDefinition '[DllImport("WinHvPlatform.dll")] public static extern int WHvGetCapability(int code, byte[] buffer, uint size, out uint written);'
    }
    $buffer = New-Object byte[] 256
    $written = [uint32]0
    $result = [EmuSetup.Whp]::WHvGetCapability(0, $buffer, 256, [ref]$written)    # 0: is a hypervisor present
    return ($result -eq 0 -and [BitConverter]::ToInt32($buffer, 0) -ne 0)
  } catch {
    $missing = $_.Exception -is [System.DllNotFoundException] -or $_.Exception.InnerException -is [System.DllNotFoundException]
    if ($missing) { return $false }
    return $null
  }
}

# Whether an optional Windows feature is enabled; readable without elevation.
function Test-Feature($name) {
  $feature = Get-CimInstance Win32_OptionalFeature -Filter "Name='$name'" -ErrorAction SilentlyContinue
  [bool]($feature -and $feature.InstallState -eq 1)
}

function Test-AccelDep {
  $usable = Test-Whpx
  if ($null -eq $usable) {
    # The API could not be asked; go by the feature and the running hypervisor.
    $usable = (Test-Feature 'HypervisorPlatform') -and (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
  }
  if ($usable) {
    Write-Ok 'hardware virtualization: Windows Hypervisor Platform (WHPX)'
  } elseif (Test-Feature 'HypervisorPlatform') {
    Write-Missing 'whpx-restart' 'Windows Hypervisor Platform (WHPX) is enabled but not running: restart Windows (if it still is not, enable virtualization in the firmware setup)'
  } else {
    Write-Missing 'whpx' 'Windows Hypervisor Platform (WHPX) is not enabled'
  }
}

# The container CLIs to look for, in order of preference. The environment
# variable EMU_CONTAINER_RUNTIME names the one to use where more than one is
# installed; the launcher reads it too.
function Get-ContainerClis {
  $chosen = "$env:EMU_CONTAINER_RUNTIME".Trim().ToLower()
  if (-not $chosen) { return @('docker', 'podman') }
  if (@('docker', 'podman') -notcontains $chosen) {
    Write-Host "EMU_CONTAINER_RUNTIME is '$chosen'; it must be docker or podman."
    exit 1
  }
  return @($chosen)
}

$script:ContainerCli = $null
function Test-ContainerDep {
  $script:ContainerCli = $null
  $clis = @(Get-ContainerClis)
  foreach ($cli in $clis) {
    if ((Test-Command $cli) -and (Test-Engine $cli)) { $script:ContainerCli = $cli; break }
  }
  if ($script:ContainerCli) {
    $version = Get-FirstLine (Get-Output $script:ContainerCli @('--version'))
    Write-Ok "container runtime: $version"
  } elseif (@($clis | Where-Object { Test-Command $_ }).Count -gt 0) {
    Write-Missing 'engine' 'container engine: a container CLI is installed but no engine is running'
  } else {
    Write-Missing 'container' "container runtime ($($clis -join ' or '))"
  }
}

# Target images for ARM are built by running ARM programs through user-mode
# emulation registered in the container engine's Linux kernel. Whether that
# works is found out by running one, in the image the target is built from: a
# registration can be listed and still be dead. That happens when a Podman
# machine is removed and created again, because WSL's distributions share one
# kernel, which keeps the registrations of the machine that is gone.
function Get-ForeignArchGaps {
  $platforms = if ((Get-HostArch) -eq 'arm64') { @('linux/arm/v7') } else { @('linux/arm64', 'linux/arm/v7') }
  $source = (Get-Content (Join-Path $PSScriptRoot 'target\image.json') -Raw | ConvertFrom-Json).source
  $image = "$($source.base_image)@$($source.base_image_digest)"
  $platforms | Where-Object { -not (Test-Run $script:ContainerCli @('run', '--rm', '--platform', $_, $image, 'true')) }
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
  $had = Test-WingetPackage $id
  try {
    Invoke-Step winget @('install', '--exact', '--id', $id, '--source', 'winget', '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity')
  } finally {
    if (-not $had -and (Test-WingetPackage $id)) { Add-Record 'winget' $id }
  }
}

function Install-Missing {
  if (((Test-Missing 'python') -or (Test-Missing 'qemu') -or (Test-Missing 'container')) -and -not (Test-Command 'winget')) {
    Write-Host 'Registering winget (App Installer)...'
    Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe
    Update-Path
    if (-not (Test-Command 'winget')) {
      throw 'winget is not available. Install "App Installer" from the Microsoft Store, then run setup again.'
    }
  }

  if (Test-Missing 'python') { Install-WingetPackage 'Python.Python.3.13' }
  if (Test-Missing 'qemu')   { Install-WingetPackage 'SoftwareFreedomConservancy.QEMU' }

  if (Test-Missing 'whpx') {
    if (Test-Admin) {
      Write-Host '  + Enable-WindowsOptionalFeature HypervisorPlatform'
      $result = Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All -NoRestart
      Add-Record 'feature' 'HypervisorPlatform'
      if ($result.RestartNeeded) { $script:RestartNeeded = $true }
    } else {
      Write-Host '  ! Enabling the Windows Hypervisor Platform needs an elevated PowerShell; run setup as Administrator.'
    }
  }

  if (Test-Missing 'container') {
    if (@(Get-ContainerClis) -notcontains 'podman') {
      throw 'EMU_CONTAINER_RUNTIME asks for Docker, which this script does not install. Install Docker, or clear the variable to use Podman.'
    }
    # Podman runs its engine in WSL 2.
    if (-not (Test-Run wsl @('--status'))) {
      if (Test-Admin) {
        Invoke-Step wsl @('--install', '--no-distribution')
        Add-Record 'wsl'
        $script:RestartNeeded = $true
      } else {
        Write-Host '  ! Installing WSL 2 needs an elevated PowerShell; run setup as Administrator.'
      }
    }
    Install-WingetPackage 'RedHat.Podman'
  }
  Update-Path

  if (-not $script:RestartNeeded) {
    $installed = @(Get-ContainerClis | Where-Object { Test-Command $_ }) | Select-Object -First 1
    if ($installed -eq 'podman') {
      if (-not (Test-Engine podman)) {
        $machines = Get-Output podman @('machine', 'list', '--format', '{{.Name}}')
        # A rootful engine, as Docker's is: it can pin a container to whole
        # CPUs, which the launcher does so the target sees the CPUs it is given.
        if (-not $machines) {
          Add-Record 'podman-machine' 'podman-machine-default'
          Invoke-Step podman @('machine', 'init', '--rootful')
        }
        Invoke-Step podman @('machine', 'start')
      }
      $script:ContainerCli = 'podman'
    } elseif ($installed -eq 'docker') {
      if (-not (Test-Engine docker)) {
        # Docker Desktop's own command (4.37 and later) waits for the engine.
        Write-Host '  + docker desktop start'
        if (-not (Test-Run docker @('desktop', 'start'))) {
          $desktop = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
          if (Test-Path $desktop) {
            Write-Host '  + starting Docker Desktop'
            Start-Process $desktop
            for ($i = 0; $i -lt 60; $i++) { if (Test-Engine docker 10) { break }; Start-Sleep 2 }
          }
        }
      }
      if (Test-Engine docker) { $script:ContainerCli = 'docker' }
    }

    if ($script:ContainerCli -and @(Get-ForeignArchGaps).Count -gt 0) {
      $binfmt = @('run', '--rm', '--privileged', 'docker.io/tonistiigi/binfmt')
      if (-not (Test-EngineImage $script:ContainerCli 'docker.io/tonistiigi/binfmt')) {
        Add-Record 'engine-image' "$($script:ContainerCli) docker.io/tonistiigi/binfmt"
      }
      # A dead registration is in the way of a new one, so clear them first.
      foreach ($action in @(@('--uninstall', 'qemu-arm,qemu-aarch64'), @('--install', 'arm,arm64'))) {
        if ($script:ContainerCli -eq 'podman') {
          # Registering needs root in the engine's kernel, which a rootless
          # Podman machine does not give its containers; run it as root there.
          Invoke-Step podman @('machine', 'ssh', "sudo podman $(($binfmt + $action) -join ' ')")
        } else {
          Invoke-Step $script:ContainerCli ($binfmt + $action)
        }
      }
      Add-Record 'binfmt' $script:ContainerCli
    }
  }
}

# -------------------------------------------------------------- uninstall ---

# The kinds of entry in the record that this script removes, in the order to
# remove them: what uses a thing goes before the thing.
$script:RemoveOrder = @('binfmt', 'engine-image', 'podman-machine', 'winget')
# The kinds it lists and leaves: removing them takes an elevated PowerShell and
# a restart, and other software may have come to use them.
$script:LeaveOrder = @('feature', 'wsl')

# The arguments that run a container CLI command as root in the engine: for
# Podman inside its machine, as the installation does it.
function Get-RootEngineArguments {
  param([string]$Cli, [string[]]$Arguments)
  if ($Cli -eq 'podman') { return @('machine', 'ssh', "sudo podman $($Arguments -join ' ')") }
  return $Arguments
}

function Test-EngineImage($cli, $image) {
  Test-Run $cli (Get-RootEngineArguments $cli @('image', 'inspect', $image))
}

function Get-PodmanMachines {
  @((Get-Output podman @('machine', 'list', '--format', '{{.Name}}')) -split "`n" |
    ForEach-Object { $_.Trim().TrimEnd('*') } | Where-Object { $_ })
}

# The entries of some kinds, as objects, in the order to remove them.
function Get-Entries([string[]]$kinds) {
  foreach ($kind in $kinds) {
    $values = @(Get-Recorded | Where-Object { $_ -like "$kind *" } | ForEach-Object { $_.Substring($kind.Length + 1) })
    # Of packages, the one recorded last goes first.
    if ($kind -eq 'winget') { [array]::Reverse($values) }
    foreach ($value in $values) { New-Object psobject -Property @{ Kind = $kind; Value = $value } }
  }
}

# Whether what an entry of the record names is still there. $null: the
# container engine that would know does not answer.
function Test-EntryPresent($entry) {
  $value = $entry.Value
  switch ($entry.Kind) {
    'winget'         { return (Test-Command winget) -and (Test-WingetPackage $value) }
    'podman-machine' { return (Test-Command podman) -and (@(Get-PodmanMachines) -contains $value) }
    'feature'        { return Test-Feature $value }
    'wsl'            { return (Test-Command wsl) -and (Test-Run wsl @('--status')) }
    'binfmt' {
      if (-not (Test-Command $value)) { return $false }
      if (-not (Test-Engine $value 20)) { return $null }
      return $true
    }
    'engine-image' {
      $cli, $image = $value -split ' ', 2
      if (-not (Test-Command $cli)) { return $false }
      if (-not (Test-Engine $cli 20)) { return $null }
      return Test-EngineImage $cli $image
    }
  }
  return $false
}

function Get-EntryText($entry) {
  $value = $entry.Value
  switch ($entry.Kind) {
    'winget'         { return "the winget package $value" }
    'podman-machine' { return "the Podman machine `"$value`", with every container, image and volume in it" }
    'binfmt'         { return "the emulation of other CPU architectures registered in the container engine ($value)" }
    'engine-image'   { return "the container image $(($value -split ' ', 2)[1])" }
  }
}

# Removes what an entry names. Returns whether the entry is settled.
function Remove-Entry($entry) {
  $value = $entry.Value
  $present = Test-EntryPresent $entry
  if ($present -eq $false) { return $true }
  if ($null -eq $present) {
    # Inside an engine that does not answer. Registered emulation is in the
    # memory of the engine's kernel and goes when that restarts.
    if ($entry.Kind -eq 'binfmt') {
      Write-Host "  The container engine does not answer; the registered emulation goes when it restarts (wsl --shutdown)."
      return $true
    }
    if (@(Get-Recorded | Where-Object { $_ -like 'podman-machine *' }).Count -gt 0) { return $true }   # it goes with the machine
    Write-Host "  ! The container engine does not answer, so this stays: $(Get-EntryText $entry)."
    return $false
  }
  try {
    switch ($entry.Kind) {
      'binfmt' {
        Invoke-Step $value (Get-RootEngineArguments $value @('run', '--rm', '--privileged', 'docker.io/tonistiigi/binfmt', '--uninstall', 'qemu-arm,qemu-aarch64'))
      }
      'engine-image' {
        $cli, $image = $value -split ' ', 2
        Invoke-Step $cli (Get-RootEngineArguments $cli @('rmi', $image))
      }
      'podman-machine' { Invoke-Step podman @('machine', 'rm', '--force', $value) }
      'winget'         { Invoke-Step winget @('uninstall', '--exact', '--id', $value, '--accept-source-agreements', '--disable-interactivity') }
    }
  } catch {
    Write-Host "  ! $_"
    return $false
  }
  return $true
}

function Write-Left($entry) {
  switch ($entry.Kind) {
    'feature' {
      Write-Host "  - The Windows feature $($entry.Value), which this script enabled. To disable it, in an"
      Write-Host '    elevated PowerShell, followed by a restart:'
      Write-Host "      Disable-WindowsOptionalFeature -Online -FeatureName $($entry.Value)"
    }
    'wsl' {
      Write-Host '  - WSL 2, which this script installed. To remove it, in an elevated PowerShell:'
      Write-Host '      wsl --uninstall'
    }
  }
}

function Invoke-Uninstall {
  if (@(Get-Recorded).Count -eq 0) {
    Write-Host 'Nothing to remove: this script has no record of installing anything on this host.'
    Write-Host "(It keeps the record in $($script:Record).)"
    exit 0
  }
  Update-Path
  Write-Host "By its record ($($script:Record)), this script installed:"
  $toRemove = 0
  foreach ($entry in @(Get-Entries $script:RemoveOrder)) {
    $present = Test-EntryPresent $entry
    if ($present -eq $false) { Write-Host "  - $(Get-EntryText $entry): gone already" }
    else { Write-Host "  - $(Get-EntryText $entry)"; $toRemove++ }
  }
  $left = @(Get-Entries $script:LeaveOrder | Where-Object { Test-EntryPresent $_ })
  if ($left.Count -gt 0) {
    Write-Host "`nLeft in place, for you to remove: that takes an elevated PowerShell and a restart, and other software may use them by now."
    foreach ($entry in $left) { Write-Left $entry }
  }
  if ($Check) {
    Write-Host "`nNothing was removed. setup.cmd -Uninstall removes it."
    exit 0
  }

  if ($toRemove -gt 0 -and -not $Yes) {
    if (-not [Environment]::UserInteractive) { Write-Host "`nNot running interactively; re-run with -Yes to go ahead."; exit 1 }
    $reply = Read-Host "`nRemove all of this? [y/N]"
    if ($reply -notmatch '^(y|yes)$') { exit 1 }
  }
  Write-Host ''
  $notRemoved = 0
  foreach ($entry in @(Get-Entries $script:RemoveOrder)) {
    if (Remove-Entry $entry) { Remove-Record $entry.Kind $entry.Value } else { $notRemoved++ }
  }
  # What is left for the user stays in the record until it is gone.
  foreach ($entry in @(Get-Entries $script:LeaveOrder)) {
    if (-not (Test-EntryPresent $entry)) { Remove-Record $entry.Kind $entry.Value }
  }
  # A record with nothing left in it goes too.
  if (@(Get-Recorded).Count -eq 0) {
    Remove-Item $script:Record
    $directory = Split-Path $script:Record
    if (@(Get-ChildItem -Force $directory).Count -eq 0) { Remove-Item $directory }
  }
  if ($notRemoved -gt 0) {
    Write-Host "`nNot everything could be removed; see above. What is left stays in the record."
    exit 1
  }
  Write-Host "`nRemoved what this script installed. This repository is untouched, with what the launcher built in it (build\)."
  exit 0
}

# ------------------------------------------------------------------- main ---

if ($Uninstall) { Invoke-Uninstall }


Write-Host 'Checking host dependencies'
Invoke-Checks

if ($script:Missing.Count -eq 0) {
  Write-Host "`nAll host dependencies are present."
  exit 0
}

if ($Check) {
  Write-Host "`nMissing: $($script:Missing -join ' '). Run setup without -Check to install."
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
if ($script:RestartNeeded -or (Test-Missing 'whpx-restart')) {
  Write-Host 'Restart Windows to finish enabling the features above, then run setup again.'
}
if ($script:Missing.Count -eq 0) {
  Write-Host 'All host dependencies are present.'
  exit 0
}
Write-Host "Still missing: $($script:Missing -join ' ')"
if ($installError) { Write-Host "The installation step failed: $installError" }
exit 1
