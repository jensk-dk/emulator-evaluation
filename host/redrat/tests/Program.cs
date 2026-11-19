using System.Text.Json;
using System.Threading.Channels;
using RedRat;
using RedRat.IR;
using RedRat.RedRat4.Usb.RedRatPico;
using RedRat.Util.Serialization;
using RedRatBridge;

var passed = 0;
void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
    passed++;
}
void Reject(Action action, string message)
{
    try { action(); }
    catch { passed++; return; }
    throw new Exception(message);
}
ModulatedSignal Signal(byte[] data, byte[]? repeat = null) => new()
{
    Lengths = [9, 4.5, 0.56, 1.69, 2.25],
    MainSignal = data,
    RepeatSignal = repeat ?? [],
    ModulationFreq = 38000
};
string ProfileJson(object buttons) => JsonSerializer.Serialize(new { version = 1, id = "test", name = "Test", buttons });

Check(SelfTest.Run() == 8, "hardware-independent self-test");
Check(Options.Parse(["list"]).Command == "list", "list parsing");
Check(Options.Parse(["validate-profile"]).Command == "validate-profile", "hardware-independent profile validation");
Check(Options.Parse(["listen", "--profile", "keys.json", "--device", "0010:42"]).Device == "0010:42", "listen options");
foreach (var invalidArgs in new[] { Array.Empty<string>(), ["list", "--device", "x"], ["listen", "--profile"],
    ["listen", "--device", "x", "--device", "y"], ["listen", "--unknown", "x"],
    ["validate-profile", "--device", "x"], ["validate-profile", "--profile", "x"] })
    Reject(() => Options.Parse(invalidArgs), "invalid arguments accepted");
var selected = new Device("0010:42", "Pico", "RedRatPico", new RedRatPicoLocationInfo(42, 0, "Pico"));
Check(Devices.Select([selected], null) == selected, "single-device selection");
Check(Devices.Select([selected], selected.Id) == selected, "explicit-device selection");
Reject(() => Devices.Select([], null), "missing device accepted");
var second = selected with { Id = "0010:43" };
Check(Devices.Select([selected, second], null) == selected, "first-device default");
Check(Devices.Select([selected, second], second.Id) == second, "explicit second-device selection");
Reject(() => Devices.Select([selected], "absent"), "unknown device accepted");

var up = Signal([0, 1, 2, 3, 2, 2, 2], [0, 4, 2]);
var down = Signal([0, 1, 2, 2, 2, 3, 2], [0, 4, 2]);
var variant = Signal([0, 1, 2, 3, 2, 3, 2]);
var wire = Serializer.IrPacketToJson(up);
using var wireString = JsonDocument.Parse(JsonSerializer.Serialize(wire));
using var wireObject = JsonDocument.Parse(wire);
Check(Profile.ReadSignal(wireString.RootElement).MainSignal.SequenceEqual(up.MainSignal), "SDK string roundtrip");
Check(Profile.ReadSignal(wireObject.RootElement).RepeatSignal.SequenceEqual(up.RepeatSignal), "SDK object roundtrip");
var profile = Profile.Parse(ProfileJson(new
{
    up = new object[] { wire, JsonSerializer.Deserialize<JsonElement>(Serializer.IrPacketToJson(variant)) },
    down = new[] { Serializer.IrPacketToJson(down) }
}));
var now = DateTime.UtcNow;
Check(profile.Decode(up, now) == "up", "learned main signal");
Check(profile.Decode(variant, now.AddMilliseconds(10)) == "up", "second learned variant");
var jitter = (ModulatedSignal)up.Clone();
jitter.Lengths = up.Lengths.Select(length => length + 0.015).ToArray();
Check(profile.Decode(jitter, now.AddMilliseconds(20)) == "up", "SDK timing tolerance");
var repeatSignal = Signal([0, 4, 2]);
Check(profile.Decode(repeatSignal, now.AddMilliseconds(80)) == "up", "contextual repeat");
Check(profile.Decode(down, now.AddMilliseconds(100)) == "down", "second key");
Check(profile.Decode(repeatSignal, now.AddMilliseconds(160)) == "down", "shared repeat belongs to last key");
Check(profile.Decode(repeatSignal, now.AddSeconds(1)) is null, "stale repeat must not match");
Check(profile.Decode(Signal([2, 2, 2]), now.AddSeconds(2)) is null, "unmapped signal");
var closeTiming = (ModulatedSignal)up.Clone();
closeTiming.Lengths = [9, 4.5, 0.76, 1.69, 2.25];
Reject(() => Profile.Parse(ProfileJson(new
{
    up = new[] { wire },
    down = new[] { Serializer.IrPacketToJson(closeTiming) }
})), "signals within SDK tolerance must not become first-key wins");
var ambiguous = (ModulatedSignal)up.Clone();
ambiguous.Lengths = [9, 4.5, 0.87, 0.87, 2.25];
Check(profile.Decode(ambiguous, now.AddSeconds(3)) is null, "ambiguous incoming timing must not become first-key wins");

// These short/long pulse variants were merged by the SDK's default state builder.
var shortLeft1 = new ModulatedSignal
{
    Lengths = [2.671168, 0.880432, 0.479832, 0.408512, 0.851984, 0.923368],
    MainSignal = [0,1,2,3,2,3,2,4,2,4,5,3,2,3,2,3,2,3,2,3,2,3,2,3,2,3,5,4,2,3,2,3,2,3,2,3,2,3,5,4,5,3,2,4,2,3,5,4,5,3,2,4,5,4,2],
    RepeatSignal = []
};
var shortLeft2 = new ModulatedSignal
{
    Lengths = [2.705424, 0.84884, 0.457184, 0.430904, 0.443976, 0.87408, 0.926096, 0.406256],
    MainSignal = [0,1,2,3,4,4,2,5,2,5,6,7,4,4,2,3,2,3,2,3,2,3,2,3,2,3,6,1,2,3,2,3,2,3,2,3,2,3,6,1,6,7,2,5,2,3,6,1,6,7,2,5,6,1,2],
    RepeatSignal = []
};
var shortRight1 = new ModulatedSignal
{
    Lengths = [2.6984, 0.85072, 0.481648, 0.405704, 0.927616],
    MainSignal = [0,1,2,3,2,3,2,1,2,1,4,3,2,3,2,3,2,3,2,3,2,3,2,3,2,3,4,1,2,3,2,3,2,3,2,3,2,3,4,1,4,3,2,1,2,3,4,1,4,3,2,1,4,3,2],
    RepeatSignal = []
};
var shortRight2 = new ModulatedSignal
{
    Lengths = [2.698976, 0.88176, 0.455872, 0.406144, 0.481632, 0.849968, 0.923856, 0.900832],
    MainSignal = [0,1,2,3,4,3,4,5,4,5,6,3,4,3,4,3,4,3,4,3,4,3,4,3,4,3,6,5,4,3,4,3,4,3,4,3,4,3,6,1,7,3,4,5,4,3,6,5,6,3,4,5,6,3,4],
    RepeatSignal = []
};
var shortProfile = Profile.Parse(ProfileJson(new
{
    left = new[] { Serializer.IrPacketToJson(shortLeft1), Serializer.IrPacketToJson(shortLeft2) },
    right = new[] { Serializer.IrPacketToJson(shortRight1), Serializer.IrPacketToJson(shortRight2) }
}));
foreach (var (sample, key) in new[] { (shortLeft1, "left"), (shortLeft2, "left"), (shortRight1, "right"), (shortRight2, "right") })
{
    Check(shortProfile.Decode(sample, now) == key, "distinct short-pulse " + key);
    var varied = (ModulatedSignal)sample.Clone();
    varied.Lengths = sample.Lengths.Select(length => length + 0.03).ToArray();
    Check(shortProfile.Decode(varied, now.AddMilliseconds(10)) == key, "short-pulse jitter for " + key);
}

var toggled = Signal([0, 1, 2, 2, 2, 2, 2]);
toggled.ToggleData = [new ToggleBit(3, 2, 3)];
var toggleProfile = Profile.Parse(ProfileJson(new { up = new[] { Serializer.IrPacketToJson(toggled) } }));
Check(toggleProfile.Decode(toggled, now) == "up", "toggle first form");
var otherToggle = Signal([0, 1, 2, 3, 2, 2, 2]);
Check(toggleProfile.Decode(otherToggle, now.AddMilliseconds(50)) == "up", "SDK toggle second form");
Reject(() => Profile.Parse(ProfileJson(new { up = new[] { wire }, down = new[] { wire } })), "duplicate cross-key signal accepted");
Reject(() => Profile.Parse(ProfileJson(new
{
    up = new[] { Serializer.IrPacketToJson(toggled) },
    down = new[] { Serializer.IrPacketToJson(otherToggle) }
})), "cross-key toggle ambiguity accepted");
var empty = Profile.Parse(ProfileJson(new { }));
Check(empty.Decode(up, now) is null, "empty profile is valid and unmapped");
foreach (var json in new[] { "{}", """{"version":2,"id":"x","name":"x","buttons":{}}""",
    """{"version":1,"id":"x","name":"x","buttons":{"up":[12]}}""",
    """{"version":1,"id":"x","name":"x","buttons":{"up":"bad"}}""" })
    Reject(() => Profile.Parse(json), "invalid profile accepted");

foreach (var command in new[] { "", "{\"do\":\"quit\"}\n" })
{
    var channel = Channel.CreateUnbounded<SignalEventArgs>();
    await RedRatBridge.Program.ReadCommands(new StringReader(command), channel.Writer, CancellationToken.None);
    await channel.Reader.Completion;
    Check(true, "EOF/quit completion");
}
foreach (var command in new[] { "not-json\n", "{\"do\":\"match\"}\n", "[]\n" })
{
    var channel = Channel.CreateUnbounded<SignalEventArgs>();
    await RedRatBridge.Program.ReadCommands(new StringReader(command), channel.Writer, CancellationToken.None);
    try { await channel.Reader.Completion; throw new Exception("invalid command accepted"); }
    catch (InvalidDataException) { passed++; }
}
using (var input = new BlockingCommandReader())
{
    var channel = Channel.CreateUnbounded<SignalEventArgs>();
    using var returned = new ManualResetEventSlim();
    var caller = Task.Run(async () =>
    {
        var commands = RedRatBridge.Program.ReadCommands(TextReader.Synchronized(input), channel.Writer, CancellationToken.None);
        returned.Set();
        await commands;
    });
    bool responsive;
    try
    {
        Check(input.Reading.Wait(TimeSpan.FromSeconds(5)), "stdin command reader started");
        responsive = returned.Wait(TimeSpan.FromSeconds(1));
    }
    finally
    {
        input.Release.Set();
        await caller;
    }
    Check(responsive, "waiting for console input must not block IR event processing");
}
Console.WriteLine($"Passed {passed} RedRat bridge checks.");

sealed class BlockingCommandReader : TextReader
{
    internal readonly ManualResetEventSlim Reading = new();
    internal readonly ManualResetEventSlim Release = new();

    public override string? ReadLine()
    {
        Reading.Set();
        Release.Wait();
        return "{\"do\":\"quit\"}";
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Reading.Dispose();
            Release.Dispose();
        }
        base.Dispose(disposing);
    }
}
