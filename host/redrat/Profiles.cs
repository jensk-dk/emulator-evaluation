using System.Text.Json;
using RedRat.AvDeviceDb;
using RedRat.IR;
using RedRat.Util.Serialization;

namespace RedRatBridge;

internal sealed class Profile
{
    private readonly Dictionary<string, AVDeviceDB> decoders = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> keys = new(StringComparer.Ordinal);
    private readonly Dictionary<string, AVDeviceDB> repeats = new(StringComparer.Ordinal);
    private string? lastKey;
    private DateTime lastSeen;

    private Profile() { }

    internal static Profile Load(string path) => Parse(File.ReadAllText(path));

    internal static Profile Parse(string json)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object ||
            !root.TryGetProperty("version", out var version) ||
            !version.TryGetInt32(out var number) || number != 1)
            throw new InvalidDataException("Profile must have version: 1.");
        _ = RequiredString(root, "id");
        _ = RequiredString(root, "name");
        if (!root.TryGetProperty("buttons", out var buttons) || buttons.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Profile buttons must be an object of signal arrays.");

        var profile = new Profile();
        var signals = new List<IRPacket>();
        var buttonNames = new HashSet<string>(StringComparer.Ordinal);
        foreach (var button in buttons.EnumerateObject())
        {
            if (string.IsNullOrWhiteSpace(button.Name) || !buttonNames.Add(button.Name) ||
                button.Value.ValueKind != JsonValueKind.Array)
                throw new InvalidDataException("Each profile button must have a unique nonempty name and a signal array.");
            foreach (var value in button.Value.EnumerateArray())
            {
                var signal = ReadSignal(value);
                var signalName = $"signal-{signals.Count}";
                signal.Name = signalName;
                profile.keys.Add(signalName, button.Name);
                signals.Add(signal);
                if (signal.RepeatSignal is { Length: > 0 } && !ModulatedSignal.MainRepeatIdentical(signal))
                {
                    var repeat = (ModulatedSignal)signal.Clone();
                    repeat.MainSignal = signal.RepeatSignal;
                    repeat.RepeatSignal = [];
                    repeat.ToggleData = [];
                    if (!profile.repeats.TryGetValue(button.Name, out var repeatDatabase))
                    {
                        repeatDatabase = CreateDatabase();
                        repeatDatabase.AddAVDevice(CreateDevice(button.Name));
                        profile.repeats.Add(button.Name, repeatDatabase);
                    }
                    repeatDatabase.AVDevices[0].AddSignal(repeat, false);
                }
            }
        }
        profile.RejectAmbiguity(signals.Cast<ModulatedSignal>());
        foreach (var repeatDatabase in profile.repeats.Values)
            repeatDatabase.CreateDecoder();
        return profile;
    }

    private void RejectAmbiguity(IEnumerable<ModulatedSignal> signals)
    {
        var groups = signals.GroupBy(signal => keys[signal.Name])
            .Select(group =>
            {
                var db = CreateDatabase();
                var device = CreateDevice(group.Key);
                device.Signals = group.Cast<IRPacket>().ToArray();
                db.AddAVDevice(device);
                db.CreateDecoder();
                return (Key: group.Key, Signals: group.ToArray(), Database: db);
            }).ToArray();
        foreach (var group in groups)
            decoders.Add(group.Key, group.Database);
        foreach (var group in groups)
        foreach (var signal in group.Signals)
        {
            var forms = signal.ToggleData.Length == 0 ? new[] { signal }
                : new[] { ModulatedSignal.GetToggleSignal1(signal), ModulatedSignal.GetToggleSignal2(signal) };
            foreach (var other in groups.Where(other => other.Key != group.Key))
            foreach (var form in forms)
                if (other.Database.DecodeSignal(form).KeyStatus == SignalKey.Status.KNOWN)
                    throw new InvalidDataException($"Ambiguous profile: buttons '{group.Key}' and '{other.Key}' match the same signal.");
        }
    }

    internal string? Decode(ModulatedSignal signal, DateTime now)
    {
        // A short repeat frame may be shared by every button (e.g. NEC). It is
        // meaningful only immediately after a matching full frame.
        if (lastKey is not null && now >= lastSeen && now - lastSeen <= TimeSpan.FromMilliseconds(400) &&
            repeats.TryGetValue(lastKey, out var repeatDatabase) &&
            repeatDatabase.DecodeSignal(signal).KeyStatus == SignalKey.Status.KNOWN)
        {
            lastSeen = now;
            return lastKey;
        }
        string? key = null;
        foreach (var decoder in decoders)
        {
            if (decoder.Value.DecodeSignal(signal).KeyStatus != SignalKey.Status.KNOWN)
                continue;
            if (key is not null)
            {
                lastKey = null;
                return null;
            }
            key = decoder.Key;
        }
        lastKey = key;
        if (key is not null)
            lastSeen = now;
        return key;
    }

    private static AVDeviceDB CreateDatabase() => new()
    {
        // The SDK's 0.45 state-building default can merge distinct short/long pulse variants.
        DecoderSMCreateDelta = 0.2,
        DecoderLogEnabled = false,
        DecoderLogOutput = Console.Error
    };

    private static AVDevice CreateDevice(string name) => new(name, AVDevice.AVDeviceType.OTHER)
    {
        // Learning and listening both use the same narrow-band detector; the
        // SDK's default wide-band-to-narrow-band pulse correction is not needed.
        RCCorrection = new AVDevice.RcCorrectionData { useDefault = false, rcCorrVal = 0 }
    };

    internal static ModulatedSignal ReadSignal(JsonElement value)
    {
        var json = value.ValueKind switch
        {
            JsonValueKind.String => value.GetString()!,
            JsonValueKind.Object => value.GetRawText(),
            _ => throw new InvalidDataException("A learned signal must be an SDK JSON string or object.")
        };
        if (Serializer.IrPacketFromJson(json) is not ModulatedSignal signal ||
            signal.Lengths is not { Length: > 0 } || signal.MainSignal is not { Length: > 0 } ||
            signal.Lengths.Any(length => !double.IsFinite(length) || length <= 0) ||
            signal.MainSignal.Any(index => index >= signal.Lengths.Length) ||
            (signal.RepeatSignal?.Any(index => index >= signal.Lengths.Length) ?? false) ||
            signal.ToggleData.Any(toggle => toggle.bitNo < 0 || toggle.bitNo >= signal.MainSignal.Length ||
                toggle.len1 < 0 || toggle.len1 >= signal.Lengths.Length || toggle.len2 < 0 || toggle.len2 >= signal.Lengths.Length))
            throw new InvalidDataException("A learned signal must contain valid ModulatedSignal timings and data.");
        return signal;
    }

    private static string RequiredString(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String ||
            string.IsNullOrWhiteSpace(value.GetString()))
            throw new InvalidDataException($"Profile {name} must be a nonempty string.");
        return value.GetString()!;
    }
}
