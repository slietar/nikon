# nikon

This Python package provides control of the Nikon Ti2-E microscope. It does not rely on the Nikon SDK but instead uses the reverse-engineered USB protocol of the microscope directly through [PyUSB](https://github.com/pyusb/pyusb).

On Windows, the driver for the Nikon Ti2-E must be set to WinUSB or [another driver supported by libusb](https://github.com/libusb/libusb/wiki/Windows), assuming you are using libusb as a backend for PyUSB.


## Example usage

```py
import asyncio
from nikon import MicroscopeDevice

async def main():
  devices = MicroscopeDevice.list()
  device = next(devices)

  await device.set_x(-31790)
  await device.set_y(28120)

  await device.set_condenser(3)
  await device.set_light(True)

  async for event in device:
    match event:
      case StatusEvent():
        event.condenser
        event.dia
        event.filter
        event.light
        event.objective
        event.optical_path
        event.x
        event.y
        event.z


asyncio.run(main())
```

Every command first tries to acquire a lock common to the device, therefore starting two commands at the same time will still cause them to run sequentially.

If you do not wish to use functions asynchronously, you can wrap all calls with `asyncio.run()`.

```py
asyncio.run(device.set_x(-31790))
asyncio.run(device.set_light(True))
```
