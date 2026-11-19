using RedRat;
using RedRat.RedRat3;
using RedRat.RedRat4.StreamIO.X;
using RedRat.RedRat4.Usb.RedRatPico;
using RedRat.Usb;

namespace RedRatBridge;

internal sealed record Device(string Id, string Name, string Type, UsbLocationInfo Location)
{
    internal object Json => new { id = Id, name = Name, type = Type };
}

internal static class Devices
{
    internal static IReadOnlyList<Device> Find()
    {
        using var finder = UsbDeviceFactory.Finder();
        var result = new List<Device>();
        foreach (var usb in finder.FindUsbDevices())
        {
            UsbLocationInfo? location = usb.ProductDescriptor.Pid switch
            {
                ProductDescriptor.ProductId.RedRatPico => new RedRatPicoLocationInfo(usb.SerialNumber, result.Count, usb.GlobalName),
                ProductDescriptor.ProductId.RedRat_X => new RedRatXUsbLocationInfo(usb.SerialNumber, result.Count, usb.GlobalName),
                ProductDescriptor.ProductId.RedRat3 or ProductDescriptor.ProductId.RedRat3_II when OperatingSystem.IsWindows()
                    => new RedRat3LocationInfo(usb.SerialNumber),
                _ => null
            };
            if (location is null)
                continue;
            var id = $"{(int)usb.ProductDescriptor.Pid:x4}:{usb.SerialNumber}";
            var name = string.IsNullOrWhiteSpace(usb.GlobalName) ? location.DeviceName : usb.GlobalName;
            if (result.Any(device => device.Id == id))
                throw new IOException($"Devices have duplicate identity '{id}'; cannot select safely.");
            result.Add(new Device(id, name, usb.ProductDescriptor.Pid.ToString(), location));
        }
        return result;
    }

    internal static Device Select(IReadOnlyList<Device> devices, string? id)
    {
        if (id is not null)
            return devices.SingleOrDefault(device => device.Id == id)
                ?? throw new IOException($"No supported USB RedRat device with ID '{id}' is attached.");
        return devices.Count == 0
            ? throw new IOException("No supported USB RedRat device is attached.")
            : devices[0];
    }
}
