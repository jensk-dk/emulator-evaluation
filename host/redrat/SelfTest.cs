using System.Text.Json;
using RedRat.IR;
using RedRat.Util.Serialization;

namespace RedRatBridge;

internal static class SelfTest
{
    internal static int Run()
    {
        var checks = 0;
        void Check(bool success, string name)
        {
            if (!success)
                throw new InvalidOperationException($"SDK self-test failed: {name}");
            checks++;
        }
        var signal = new ModulatedSignal
        {
            Lengths = [9, 4.5, 0.56, 1.69, 2.25],
            MainSignal = [0, 1, 2, 2, 2, 2, 2],
            RepeatSignal = [0, 4, 2],
            ToggleData = [new ToggleBit(3, 2, 3)],
            ModulationFreq = 38000
        };
        var json = Serializer.IrPacketToJson(signal);
        using var document = JsonDocument.Parse(json);
        var roundtrip = Profile.ReadSignal(document.RootElement);
        Check(roundtrip.MainSignal.SequenceEqual(signal.MainSignal) &&
            roundtrip.RepeatSignal.SequenceEqual(signal.RepeatSignal) &&
            roundtrip.ToggleData.Length == 1, "SDK JSON roundtrip");
        var profile = Profile.Parse(JsonSerializer.Serialize(new
        {
            version = 1, id = "self-test", name = "Synthetic self-test",
            buttons = new { up = new[] { json } }
        }));
        var now = DateTime.UtcNow;
        Check(profile.Decode(roundtrip, now) == "up", "learned signal");
        var toggled = ModulatedSignal.GetToggleSignal2(roundtrip);
        Check(profile.Decode(toggled, now.AddMilliseconds(10)) == "up", "toggle variant");
        var jitter = (ModulatedSignal)roundtrip.Clone();
        jitter.Lengths = jitter.Lengths.Select(length => length + 0.015).ToArray();
        Check(profile.Decode(jitter, now.AddMilliseconds(20)) == "up", "timing tolerance");
        var repeat = new ModulatedSignal { Lengths = signal.Lengths, MainSignal = [0, 4, 2], RepeatSignal = [] };
        Check(profile.Decode(repeat, now.AddMilliseconds(80)) == "up", "contextual repeat");
        Check(profile.Decode(repeat, now.AddSeconds(1)) is null, "stale repeat");
        var unmatched = new ModulatedSignal { Lengths = signal.Lengths, MainSignal = [2, 2, 2], RepeatSignal = [] };
        Check(profile.Decode(unmatched, now.AddSeconds(2)) is null, "unmapped signal");
        var rejected = false;
        try
        {
            Profile.Parse(JsonSerializer.Serialize(new
            {
                version = 1, id = "ambiguous", name = "Ambiguous",
                buttons = new { up = new[] { json }, down = new[] { json } }
            }));
        }
        catch (InvalidDataException) { rejected = true; }
        Check(rejected, "ambiguous profile rejected");
        return checks;
    }
}
