"""The launcher's audio player for Windows hosts.

Windows ships no program that plays raw samples from its standard input, the
way pacat, pw-cat and aplay do on Linux, so the host-side audio process
(emulator/hostaudio.py) uses this module as its player program. It needs
nothing but Python: it plays through the system's wave output (winmm), which
hands the sound to the Windows audio service like any other application's.

    python -m emulator.winmm_player play [--device NAME_OR_NUMBER] [--volume 0..100] [--monitor FILE]
        Plays 16-bit little-endian stereo at 48 kHz from standard input on an
        output device (the system default unless one is named). With
        --monitor, everything the device takes is also written to FILE, and a
        summary to FILE.json on exit.
    python -m emulator.winmm_player devices
        The output devices, as JSON.
    python -m emulator.winmm_player activity PID
        What the audio service says about a process: whether it is playing,
        and on which devices. JSON.

The sound arrives at the target's pace and leaves at the output device's. A
short buffer in between takes up the difference: when it runs empty the
device gets silence, and when it overflows the oldest sound is dropped, so
the delay stays short.

The volume is the application's volume in the Windows mixer, which Windows
remembers for the program that set it: here the Python interpreter. So the
volume that was there is put back when the player ends, and a player that
was stopped before it could do that leaves a note (in build/host/) from
which the next one puts it back.
"""
import argparse
import ctypes
import json
import os
import sys
import threading
import time
import uuid

RATE = 48000
CHANNELS = 2
FRAME_BYTES = 4
BUFFER_BYTES = RATE // 50 * FRAME_BYTES         # what the device takes at a time: 20 ms
DEVICE_BUFFERS = 4
RING_BYTES = RATE // 2 * FRAME_BYTES            # at most half a second waits to be played
START_BYTES = 2 * BUFFER_BYTES                  # sound to have before the device starts

WAVE_MAPPER = 0xFFFFFFFF                        # "the default device"
CALLBACK_EVENT = 0x00050000
WHDR_INQUEUE = 0x10
TIME_SAMPLES, TIME_BYTES = 2, 4
DRVM_MAPPER_PREFERRED_GET = 0x2015

if os.name == "nt":
    from ctypes import wintypes

    class _Format(ctypes.Structure):            # WAVEFORMATEX
        _pack_ = 1
        _fields_ = [("tag", wintypes.WORD), ("channels", wintypes.WORD), ("rate", wintypes.DWORD),
                    ("bytes_per_second", wintypes.DWORD), ("block_align", wintypes.WORD),
                    ("bits", wintypes.WORD), ("extra", wintypes.WORD)]

    class _Header(ctypes.Structure):            # WAVEHDR
        _fields_ = [("data", ctypes.c_void_p), ("length", wintypes.DWORD), ("recorded", wintypes.DWORD),
                    ("user", ctypes.c_size_t), ("flags", wintypes.DWORD), ("loops", wintypes.DWORD),
                    ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]

    class _Caps(ctypes.Structure):              # WAVEOUTCAPSW
        _fields_ = [("manufacturer", wintypes.WORD), ("product", wintypes.WORD), ("version", wintypes.UINT),
                    ("name", wintypes.WCHAR * 32), ("formats", wintypes.DWORD), ("channels", wintypes.WORD),
                    ("reserved", wintypes.WORD), ("support", wintypes.DWORD)]

    class _Time(ctypes.Structure):              # MMTIME
        _pack_ = 1
        _fields_ = [("type", wintypes.UINT), ("value", wintypes.DWORD), ("more", wintypes.DWORD)]

    def _winmm():
        winmm = ctypes.WinDLL("winmm")
        handle, pointer, size = ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t
        for name, arguments in (
                ("waveOutGetNumDevs", []),
                ("waveOutGetDevCapsW", [size, pointer, wintypes.UINT]),
                ("waveOutMessage", [handle, wintypes.UINT, pointer, pointer]),
                ("waveOutOpen", [pointer, wintypes.UINT, pointer, size, size, wintypes.DWORD]),
                ("waveOutPrepareHeader", [handle, pointer, wintypes.UINT]),
                ("waveOutUnprepareHeader", [handle, pointer, wintypes.UINT]),
                ("waveOutWrite", [handle, pointer, wintypes.UINT]),
                ("waveOutGetPosition", [handle, pointer, wintypes.UINT]),
                ("waveOutGetVolume", [handle, pointer]),
                ("waveOutSetVolume", [handle, wintypes.DWORD]),
                ("waveOutReset", [handle]),
                ("waveOutClose", [handle])):
            function = getattr(winmm, name)
            function.argtypes, function.restype = arguments, wintypes.UINT
        return winmm


def _fail(text, status=1):
    sys.stderr.write("emu winmm_player: %s\n" % text)
    return status


# ------------------------------------------------------------- devices ---

def _device_names(winmm):
    names = []
    for number in range(winmm.waveOutGetNumDevs()):
        caps = _Caps()
        names.append(caps.name if winmm.waveOutGetDevCapsW(number, ctypes.byref(caps), ctypes.sizeof(caps)) == 0
                     else "")
    return names


def _default_device(winmm):
    """The number of the device the system plays on by default, or None."""
    number, flags = wintypes.DWORD(WAVE_MAPPER), wintypes.DWORD(0)
    done = winmm.waveOutMessage(ctypes.c_void_p(WAVE_MAPPER), DRVM_MAPPER_PREFERRED_GET, ctypes.byref(number),
                                ctypes.byref(flags))
    return number.value if done == 0 and number.value != WAVE_MAPPER else None


def _find_device(winmm, wanted):
    """The number of the device with this number or name, or None. The wave
    interface cuts a name off after 31 characters, so the start of the full
    name, as the Windows sound settings show it, names the device as well."""
    names = _device_names(winmm)
    if wanted.isdigit():
        return int(wanted) if int(wanted) < len(names) else None
    for number, name in enumerate(names):
        if name and (wanted.lower() == name.lower() or (len(name) == 31 and wanted.lower().startswith(name.lower()))):
            return number
    return None


def list_devices():
    winmm = _winmm()
    chosen = _default_device(winmm)
    print(json.dumps([{"number": number, "name": name, "default": number == chosen}
                      for number, name in enumerate(_device_names(winmm))]))
    return 0


# ---------------------------------------------------------------- play ---

class _Ring:
    """The sound that waits to be played."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = bytearray()
        self.taken = 0          # bytes the device took, silence included
        self.sound = 0          # of those, bytes that came from standard input
        self.dropped = 0        # bytes dropped because the buffer was full

    def store(self, block):
        with self.lock:
            self.data += block
            excess = len(self.data) - RING_BYTES
            if excess > 0:
                excess += -excess % FRAME_BYTES
                del self.data[:excess]
                self.dropped += excess

    def take(self, want):
        with self.lock:
            have = min(len(self.data), want)
            have -= have % FRAME_BYTES
            block = bytes(self.data[:have])
            del self.data[:have]
            self.taken += want
            self.sound += have
        return block + bytes(want - have)

    def waiting(self):
        with self.lock:
            return len(self.data)


def _volume_note():
    """Where a player that changed the application's volume notes what the
    volume was, until it has put that back."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "build", "host", "winmm-volume.json")


def _process_runs(pid):
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel32.OpenProcess(0x00100000, False, pid) if pid else None      # the right to wait for it
    if not process:
        return False
    running = kernel32.WaitForSingleObject(process, 0) == 258                    # 258: it has not ended
    kernel32.CloseHandle(process)
    return running


def _restore_volume(winmm, device):
    """Put back the volume a stopped player left changed."""
    try:
        with open(_volume_note()) as handle:
            note = json.load(handle)
        before, owner = int(note["volume"]), int(note.get("pid", 0))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return
    if owner != os.getpid() and _process_runs(owner):
        return                  # that player puts it back itself
    if winmm.waveOutSetVolume(device, before) == 0:
        try:
            os.unlink(_volume_note())
        except OSError:
            pass


def _set_volume(winmm, device, percent):
    """Set the application's volume; returns whether there is one to put back."""
    before = wintypes.DWORD()
    if winmm.waveOutGetVolume(device, ctypes.byref(before)) != 0:
        return False
    level = int(round(percent / 100.0 * 0xFFFF))
    if before.value == (level << 16 | level):
        return False
    try:
        os.makedirs(os.path.dirname(_volume_note()), exist_ok=True)
        with open(_volume_note(), "x") as handle:
            json.dump({"volume": before.value, "pid": os.getpid()}, handle)
    except FileExistsError:
        return False            # another player has changed it and puts it back
    except OSError:
        pass
    return winmm.waveOutSetVolume(device, level << 16 | level) == 0


def play(device_name, volume, monitor_path):
    winmm = _winmm()
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]

    monitor = None
    if monitor_path:
        try:
            monitor = open(monitor_path, "wb")
        except OSError:
            return _fail("cannot write %s" % monitor_path)
    number = WAVE_MAPPER
    if device_name:
        number = _find_device(winmm, device_name)
        if number is None:
            return _fail("no output device is named %s (see: python -m emulator.winmm_player devices)" % device_name)
    names = _device_names(winmm)
    shown = number if number != WAVE_MAPPER else _default_device(winmm)
    name = names[shown] if shown is not None and shown < len(names) else "the default output device"

    ring = _Ring()
    stopping = threading.Event()
    state = {"device": None, "started": False, "error": None, "restore": False}
    wake = kernel32.CreateEventW(None, False, False, None)

    def run_device():
        """Open the device and keep it supplied: every 20 ms it has played
        is replaced by the next 20 ms."""
        device = ctypes.c_void_p()
        form = _Format(1, CHANNELS, RATE, RATE * FRAME_BYTES, FRAME_BYTES, 16, 0)
        done = winmm.waveOutOpen(ctypes.byref(device), number, ctypes.byref(form), wake, 0, CALLBACK_EVENT)
        if done != 0:
            state["error"] = "the output device did not open (status %d)" % done
            return
        state["device"] = device
        _restore_volume(winmm, device)
        if volume is not None:
            state["restore"] = _set_volume(winmm, device, volume)
        blocks = [ctypes.create_string_buffer(BUFFER_BYTES) for _ in range(DEVICE_BUFFERS)]
        headers = [_Header(ctypes.addressof(block), BUFFER_BYTES, 0, 0, 0, 0, None, 0) for block in blocks]
        for header in headers:
            winmm.waveOutPrepareHeader(device, ctypes.byref(header), ctypes.sizeof(header))
        state["headers"] = headers
        state["started"] = True
        index = 0
        while not stopping.is_set():
            header = headers[index]
            if header.flags & WHDR_INQUEUE:
                kernel32.WaitForSingleObject(wake, 100)
                continue
            block = ring.take(BUFFER_BYTES)
            ctypes.memmove(header.data, block, BUFFER_BYTES)
            if monitor:
                monitor.write(block)
            if winmm.waveOutWrite(device, ctypes.byref(header), ctypes.sizeof(header)) != 0:
                state["error"] = "the output device stopped taking sound"
                return
            index = (index + 1) % DEVICE_BUFFERS

    thread = None
    source = sys.stdin.buffer
    try:
        while True:
            block = source.read1(BUFFER_BYTES) if hasattr(source, "read1") else source.read(BUFFER_BYTES)
            if not block:
                break
            ring.store(block)
            if thread is None and ring.waiting() >= START_BYTES:
                thread = threading.Thread(target=run_device, daemon=True)
                thread.start()
            if state["error"]:
                break
    except (OSError, KeyboardInterrupt):
        pass
    # Let what still waits reach the device, then stop.
    deadline = time.monotonic() + 1.0
    while thread and thread.is_alive() and ring.waiting() >= FRAME_BYTES and time.monotonic() < deadline:
        time.sleep(0.01)
    device_seconds = 0.0
    device = state["device"]
    if state["started"]:
        time.sleep(DEVICE_BUFFERS * 0.02)
        position = _Time(TIME_SAMPLES, 0, 0)
        if winmm.waveOutGetPosition(device, ctypes.byref(position), ctypes.sizeof(position)) == 0:
            device_seconds = position.value / float(RATE * (FRAME_BYTES if position.type == TIME_BYTES else 1))
    stopping.set()
    if thread:
        thread.join(timeout=2)
    if device:
        winmm.waveOutReset(device)
        for header in state.get("headers", ()):
            winmm.waveOutUnprepareHeader(device, ctypes.byref(header), ctypes.sizeof(header))
        if state["restore"]:
            _restore_volume(winmm, device)
        winmm.waveOutClose(device)

    if monitor:
        monitor.close()
        seconds = lambda count: round(count / float(RATE * FRAME_BYTES), 3)
        try:
            with open(monitor_path + ".json", "w") as handle:
                json.dump({"device": name, "volume": 100 if volume is None else volume, "started": state["started"],
                           "taken_seconds": seconds(ring.taken), "sound_seconds": seconds(ring.sound),
                           "dropped_seconds": seconds(ring.dropped),
                           "device_clock_seconds": round(device_seconds, 3)}, handle)
                handle.write("\n")
        except OSError:
            pass
    if state["error"]:
        return _fail(state["error"])
    return 0


# ------------------------------------------------------------ activity ---
#
# The Windows audio service keeps a session for each program that plays on an
# output device. Asking it takes its COM interfaces, called here by their
# position in each interface's table of functions.

def _guid(text):
    return (ctypes.c_ubyte * 16)(*uuid.UUID(text).bytes_le)


def _method(pointer, index, *arguments):
    """Function number `index` of a COM object, ready to be called."""
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(table[index])


def _release(pointer):
    if pointer:
        _method(pointer, 2)(pointer)


def _checked(status):
    if status < 0:
        raise OSError("the audio service answered with status 0x%08x" % (status & 0xFFFFFFFF))


def _endpoint_name(endpoint):
    class _Key(ctypes.Structure):
        _fields_ = [("format", ctypes.c_ubyte * 16), ("id", wintypes.DWORD)]

    class _Value(ctypes.Structure):             # PROPVARIANT, as far as a string needs it
        _fields_ = [("type", wintypes.USHORT), ("reserved", wintypes.USHORT * 3), ("text", ctypes.c_wchar_p),
                    ("more", ctypes.c_void_p)]

    store = ctypes.c_void_p()
    if _method(endpoint, 4, wintypes.DWORD, ctypes.c_void_p)(endpoint, 0, ctypes.byref(store)) < 0:
        return None
    try:
        key = _Key(_guid("a45c254e-df1c-4efd-8020-67d146a850e0"), 14)      # the device's friendly name
        value = _Value()
        if _method(store, 5, ctypes.c_void_p, ctypes.c_void_p)(store, ctypes.byref(key), ctypes.byref(value)) < 0:
            return None
        name = value.text if value.type == 31 else None                    # 31: a wide string
        ctypes.WinDLL("ole32").PropVariantClear(ctypes.byref(value))
        return name
    finally:
        _release(store)


def _sessions(pid):
    """(found, playing, devices): whether the audio service has a session of
    the process on an active output device, whether one of them is playing,
    and the devices it plays on."""
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoInitializeEx(None, 0)
    found, playing, devices = False, False, []
    enumerator, endpoints = ctypes.c_void_p(), ctypes.c_void_p()
    _checked(ole32.CoCreateInstance(_guid("bcde0395-e52f-467c-8e3d-c4579291692e"), None, 23,
                                    _guid("a95664d2-9614-4f35-a746-de8db63617e6"), ctypes.byref(enumerator)))
    try:
        # Output devices (0) that are active (1).
        _checked(_method(enumerator, 3, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p)(
            enumerator, 0, 1, ctypes.byref(endpoints)))
        count = wintypes.UINT()
        _checked(_method(endpoints, 3, ctypes.c_void_p)(endpoints, ctypes.byref(count)))
        for number in range(count.value):
            endpoint, manager, sessions = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
            try:
                _checked(_method(endpoints, 4, wintypes.UINT, ctypes.c_void_p)(endpoints, number,
                                                                               ctypes.byref(endpoint)))
                _checked(_method(endpoint, 3, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)(
                    endpoint, _guid("77aa99a0-1bd6-484f-8bc7-2c654c9a9b6f"), 23, None, ctypes.byref(manager)))
                _checked(_method(manager, 5, ctypes.c_void_p)(manager, ctypes.byref(sessions)))
                total = ctypes.c_int()
                _checked(_method(sessions, 3, ctypes.c_void_p)(sessions, ctypes.byref(total)))
                for index in range(total.value):
                    session, extended = ctypes.c_void_p(), ctypes.c_void_p()
                    try:
                        _checked(_method(sessions, 4, ctypes.c_int, ctypes.c_void_p)(sessions, index,
                                                                                    ctypes.byref(session)))
                        _checked(_method(session, 0, ctypes.c_void_p, ctypes.c_void_p)(
                            session, _guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d"), ctypes.byref(extended)))
                        owner, active = wintypes.DWORD(), ctypes.c_int()
                        _method(extended, 14, ctypes.c_void_p)(extended, ctypes.byref(owner))
                        if owner.value != pid:
                            continue
                        found = True
                        _checked(_method(session, 3, ctypes.c_void_p)(session, ctypes.byref(active)))
                        if active.value == 1:           # the session is playing
                            playing = True
                            devices.append(_endpoint_name(endpoint) or "(no device named)")
                    finally:
                        _release(extended)
                        _release(session)
            finally:
                _release(sessions)
                _release(manager)
                _release(endpoint)
    finally:
        _release(endpoints)
        _release(enumerator)
    return found, playing, devices


def process_activity(pid):
    try:
        found, playing, devices = _sessions(pid)
    except (OSError, ValueError, AttributeError) as error:
        print(json.dumps({"pid": pid, "known": None, "reason": str(error)}))
        return 0
    print(json.dumps({"pid": pid, "known": True, "playing": playing, "devices": devices} if found
                     else {"pid": pid, "known": False}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="emulator.winmm_player", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    playing = commands.add_parser("play")
    playing.add_argument("--device")
    playing.add_argument("--volume", type=float)
    playing.add_argument("--monitor")
    commands.add_parser("devices")
    commands.add_parser("activity").add_argument("pid", type=int)
    args = parser.parse_args(argv)
    if os.name != "nt":
        return _fail("this player is for Windows hosts", 64)
    if args.command == "devices":
        return list_devices()
    if args.command == "activity":
        return process_activity(args.pid)
    if args.volume is not None and not 0 <= args.volume <= 100:
        return _fail("--volume is from 0 to 100", 64)
    return play(args.device, args.volume, args.monitor)


if __name__ == "__main__":
    sys.exit(main())
