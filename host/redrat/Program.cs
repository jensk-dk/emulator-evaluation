using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using RedRat;
using RedRat.RedRat3;
using RedRat.RedRat4;
using RedRat.RedRat4.StreamIO;
using RedRat.Usb;
using RedRat.Util.Serialization;

namespace RedRatBridge;

internal static class Program
{
    internal static async Task<int> Main(string[] args)
    {
        // Vendor diagnostics must never corrupt the JSON-lines transport.
        using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
        Console.SetOut(Console.Error);
        try
        {
            var options = Options.Parse(args);
            if (options.Command == "self-test")
            {
                var checks = SelfTest.Run();
                await Write(output, new { @event = "self-test", passed = true, checks, hardware = false });
                return 0;
            }
            if (options.Command == "validate-profile")
            {
                Profile.Parse(await Console.In.ReadToEndAsync());
                await Write(output, new { @event = "profile-valid" });
                return 0;
            }
            var profile = options.Profile is null ? null : Profile.Load(options.Profile);
            var devices = Devices.Find();
            if (options.Command == "list")
            {
                await Write(output, new { devices = devices.Select(device => device.Json) });
                return 0;
            }
            var selected = Devices.Select(devices, options.Device);
            await Listen(selected, profile, Console.In, output);
            return 0;
        }
        catch (Exception error)
        {
            await Console.Error.WriteLineAsync($"RedRatBridge: {error.GetBaseException().Message}");
            return 1;
        }
    }

    internal static async Task Listen(Device selected, Profile? profile, TextReader input, TextWriter output)
    {
        using var usb = UsbDeviceFactory.Creator();
        using var device = selected.Location.GetRedRat();
        if (device is not IRedRat3 receiver)
            throw new NotSupportedException($"Device '{selected.Id}' does not support narrow-band IR capture.");
        using var stop = new CancellationTokenSource();
        var events = Channel.CreateBounded<SignalEventArgs>(new BoundedChannelOptions(256)
        {
            SingleReader = true,
            SingleWriter = false,
            FullMode = BoundedChannelFullMode.Wait
        });
        void OnSignal(object? sender, SignalEventArgs args)
        {
            if (!events.Writer.TryWrite(args) && !stop.IsCancellationRequested)
                events.Writer.TryComplete(new IOException("IR event queue overflow; consumer cannot keep up."));
        }
        void OnCancel(object? sender, ConsoleCancelEventArgs args)
        {
            args.Cancel = true;
            stop.Cancel();
        }
        void OnConnection(object? sender, ConnStateChangedEventArgs args)
        {
            if (args.ConnectionState != ConnectionStatus.CONNECTED && !stop.IsCancellationRequested)
                events.Writer.TryComplete(new IOException("USB RedRat device disconnected."));
        }
        receiver.RCDetectorSignalIn += OnSignal;
        if (device is IRedRat4 connectedDevice)
            connectedDevice.ConnStateChanged += OnConnection;
        Console.CancelKeyPress += OnCancel;
        Task? commands = null;
        var enabled = false;
        try
        {
            device.Connect();
            // Mark before enabling so partial enable failures still attempt cancellation.
            enabled = true;
            receiver.RCInputOneShot = false;
            receiver.RCDetectorEnabled = true;
            await Write(output, new { @event = "ready", device = selected.Json });
            commands = ReadCommands(input, events.Writer, stop.Token);
            await foreach (var args in events.Reader.ReadAllAsync(stop.Token))
            {
                switch (args.Action)
                {
                    case SignalEventAction.EXCEPTION:
                        throw new IOException("IR receiver failed.", args.Exception);
                    case SignalEventAction.RC_DETECTOR_DISABLED:
                        throw new IOException("IR receiver stopped unexpectedly.");
                    case SignalEventAction.MODULATED_SIGNAL:
                        if (args.ModulatedSignal is null)
                            throw new IOException("IR receiver returned an empty signal.");
                        if (profile is null)
                        {
                            // Ambient-light blips are not learnable IR frames. Three
                            // timings still allow short protocol repeat frames.
                            if (args.ModulatedSignal.MainSignal.Length < 3)
                                break;
                            await Write(output, new { @event = "signal", signal = Serializer.IrPacketToJson(args.ModulatedSignal) });
                        }
                        else
                        {
                            var key = profile.Decode(args.ModulatedSignal, args.TimeStamp);
                            await Write(output, key is null ? new { @event = "unmapped" } : (object)new { @event = "key", key });
                        }
                        break;
                }
            }
            if (commands is not null)
                await commands;
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested)
        {
        }
        finally
        {
            stop.Cancel();
            receiver.RCDetectorSignalIn -= OnSignal;
            if (device is IRedRat4 disconnectingDevice)
                disconnectingDevice.ConnStateChanged -= OnConnection;
            Console.CancelKeyPress -= OnCancel;
            try
            {
                if (enabled)
                    receiver.RCDetectorEnabled = false;
            }
            finally
            {
                device.Disconnect();
            }
        }
    }

    internal static Task ReadCommands(TextReader input, ChannelWriter<SignalEventArgs> writer, CancellationToken token) =>
        // Console.In can block synchronously even through ReadLineAsync.
        Task.Run(async () =>
        {
            try
            {
                while (await input.ReadLineAsync(token) is { } line)
                {
                    using var document = JsonDocument.Parse(line);
                    var root = document.RootElement;
                    if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("do", out var action) ||
                        action.ValueKind != JsonValueKind.String || action.GetString() != "quit")
                        throw new InvalidDataException("Expected a JSON command {\"do\":\"quit\"} or stdin EOF.");
                    break;
                }
                writer.TryComplete();
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested)
            {
            }
            catch (Exception error)
            {
                writer.TryComplete(new InvalidDataException("Invalid stdin command: " + error.Message, error));
            }
        });

    private static Task Write(TextWriter output, object value) => output.WriteLineAsync(JsonSerializer.Serialize(value));
}

internal sealed record Options(string Command, string? Device, string? Profile)
{
    internal static Options Parse(string[] args)
    {
        const string usage = "Usage: RedRatBridge list | listen [--device ID] [--profile PATH] | validate-profile (JSON on stdin) | self-test";
        if (args.Length == 1 && args[0] is "list" or "self-test" or "validate-profile")
            return new(args[0], null, null);
        if (args.Length == 0 || args[0] != "listen")
            throw new ArgumentException(usage);
        string? device = null, profile = null;
        for (var index = 1; index < args.Length; index += 2)
        {
            if (index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]) || args[index + 1].StartsWith("--"))
                throw new ArgumentException(usage);
            switch (args[index])
            {
                case "--device" when device is null: device = args[index + 1]; break;
                case "--profile" when profile is null: profile = args[index + 1]; break;
                default: throw new ArgumentException(usage);
            }
        }
        return new("listen", device, profile);
    }
}
