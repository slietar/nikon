from dataclasses import dataclass
from typing import Optional, cast
import asyncio
import random
import struct
import time

import usb.backend
import usb.core
import usb.util


@dataclass(kw_only=True)
class ButtonPressEvent:
  fnL: bool
  fnR: bool
  fn1: bool
  fn2: bool
  fn3: bool
  fn4: bool
  fn5: bool
  fn6: bool

@dataclass(kw_only=True)
class StatusEvent:
  condenser: int
  """ The current condenser's index (0-6). """

  dia: float
  """ The diaphgram's opening (0-1). """

  filter: int
  """ The current filter's index (0-5). """

  light: bool
  """ Whether the light is enabled.  """

  objective: int
  """ The current objective's index (0-5). """

  optical_path: int
  """ The current optical path's index (0-3). """

  shutter: bool
  """ Whether the shutter is enabled. """

  x: int
  """ The x position [0.1 µm]. """

  y: int
  """ The y position [0.1 µm]. """

  z: int
  """ The z position [0.01 µm]. """

  zoom: int
  """ The internal zoom level, `1` for 1X, `2` for 1.5X and `0` for an indeterminate value, which is reported when the user is changing the zoom from one level to the other. """

  @property
  def point(self):
    return (self.x, self.y, self.z)

@dataclass(kw_only=True)
class ObjectiveInfo:
  magnification: int
  """ The magnification [0.1 X], for example `200` for 20X. """

  numerical_aperture: int # [0.01]
  """ The numerical aperture [0.01], for example `50` for 0.5. """

  model: str
  """ The model identifier, for example `"MRH00201"`. Using this identifier, more information on the objective can be found on [Nikon's website](https://www.microscope.healthcare.nikon.com/products/optics/selector). """

  observation: str
  """ The observation technique, one of `"Ph"`, `"DIC"`, `"NAMC"`, `"IMSI"` or `"TIRF"`. """

  pfs: bool
  """ Whether the objective supports PFS. """

  refractive_index: str
  """ The refractive index, one of `"Dry"`, `"WI"`, `"MImm"`, `"Oil"` or `"Sil"`. """

  series: str
  """ The series identifier, for example `"Plan Fluor"`. """

  working_distance: int
  """ The working distance [0.01 mm], for example `210` for 2.10 mm. """


class MicroscopeDevice:
  def __init__(self, device: usb.core.Device):
    self._device = device
    self._lock = asyncio.Lock()
    self._next_request_number = random.randrange(0xffff)

  async def _request(self, payload: bytes, /):
    request_number = self._next_request_number
    self._next_request_number = (self._next_request_number + 1) % 0xffff
    # print("WRITE", "".join([f"{a:02x}" for a in list(payload.ljust(58, b"\x00") + b"\x30\x31" + struct.pack(">H", request_number))]))

    def run():
      self._device.write(0x01, payload.ljust(58, b"\x00") + b"\x30\x31" + struct.pack(">H", request_number))

      while True:
        response = cast(bytes, self._device.read(0x81, 62, 10000).tobytes())
        response_number, = struct.unpack(">H", response[60:])

        if response_number == request_number:
          return response

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run)

  async def _call(self, call_type: int, payload: bytes, /):
    return await self._request(b"\x01\x00\x21\xff\x00\x00" + bytes([call_type]) + payload.rjust(4, b"\x00"))


  # Version numbers

  async def get_firmware_cpu_version(self):
    flag = False

    async with self._lock:
      res = await self._request(b"\x01\x00\x08\x00\x00\x00\x00\x00\x00" + struct.pack(">?", flag))
      return res[6:11].decode("ascii")

  async def get_version(self):
    async with self._lock:
      res = await self._request(b"\x01\x00\xe8\x30")
      return res[6:14].decode("ascii")


  # Labels

  async def _get_label(self, header: bytes, index: int):
    async with self._lock:
      res = await self._request(header + struct.pack(">5xB", index + 1))
      return (
        res[10:40].decode("ascii").rstrip(" "),
        res[40:50].decode("ascii").rstrip(" ")
      )

  async def get_condenser_label(self, index: int, /):
    return (await self._get_label(b"\x01\x00\x19\x04", index))[0]

  async def get_condenser_labels(self):
    return [await self.get_condenser_label(index) for index in range(7)]

  async def get_filter_label(self, index: int, /):
    return (await self._get_label(b"\x01\x00\x19\x08", index))[0]

  async def get_filter_labels(self):
    return [await self.get_filter_label(index) for index in range(6)]

  async def get_optical_path_label(self, index: int, /):
    return (await self._get_label(b"\x01\x00\x19\x18", index))[1]

  async def get_optical_path_labels(self):
    return [await self.get_optical_path_label(index) for index in range(4)]

  async def get_zoom_label(self, index: int, /):
    return (await self._get_label(b"\x01\x00\x19\x2c", index))[1]

  async def get_zoom_labels(self):
    return [await self.get_zoom_label(index) for index in range(2)]


  # Objectives

  async def get_objective_info(self, index: int, /):
    async with self._lock:
      res = await self._request(b"\x01\x00\x19\x00" + struct.pack(">5xB", index + 1))
      model, magnification, numerical_aperture, pfs, \
        series, working_distance, observation, refractive_index = struct.unpack(">10x8sHHH14s4s4s4s12x", res)

      return ObjectiveInfo(
        magnification=magnification,
        numerical_aperture=numerical_aperture,
        model=model.decode("ascii"),
        observation=observation.decode("ascii").rstrip("\x00"),
        pfs=(pfs == 2),
        refractive_index=refractive_index.decode("ascii").rstrip("\x00"),
        series=series.decode("ascii").rstrip("\x00"),
        working_distance=round(float(working_distance) * 100.0),
      )

  async def get_objective_infos(self):
    return [await self.get_objective_info(index) for index in range(6)]


  # Stage bounds

  async def _get_bound(self, header: bytes):
    res = await self._request(b"\x01\x00" + header)
    bound, = cast(tuple[int], struct.unpack(">i", res[6:10]))
    return bound

  async def get_x_bounds(self):
    """
    Queries the stage's x bounds.

    Returns:
      tuple[int, int]: The minimum and maximum x positions [0.1 µm].
    """

    return (
      await self._get_bound(b"\x1b\x08"),
      await self._get_bound(b"\x1a\x08")
    )

  async def get_y_bounds(self):
    """
    Queries the stage's x bounds.

    Returns:
      tuple[int, int]: The minimum and maximum y positions [0.1 µm].
    """

    return (
      await self._get_bound(b"\x1b\x0c"),
      await self._get_bound(b"\x1a\x0c")
    )

  async def get_z_bound(self):
    """
    Queries the stage's z bound.

    Returns:
      int: The maximum z position [0.01 µm].
    """

    return await self._get_bound(b"\x1b\x04")


  # Events

  async def get_event(self):
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, lambda: self._device.read(0x82, 64, 15000))
    unpacked = struct.unpack(">xxxBBBxxBxixxxxixxxxixxxxH?7xB19x", data)

    return StatusEvent(
      condenser=(unpacked[1] - 1),
      dia=(unpacked[7] - 1) / 2099.0,
      filter=((unpacked[2] & 0x0f) - 1),
      light=unpacked[8],
      objective=(unpacked[0] - 1),
      optical_path=(unpacked[3] - 1),
      shutter=(unpacked[2] >= 0x10),
      x=unpacked[5],
      y=unpacked[6],
      z=unpacked[4],
      zoom=(unpacked[9] - 0x40)
    )

  async def get_status(self):
    async for event in self:
      if isinstance(event, StatusEvent):
        return event

    raise Exception()

  async def get_stable_status(self, *, idle_duration: float = 0.5):
    status = await self.get_status()

    while True:
      try:
        status = await asyncio.wait_for(self.get_status(), timeout=idle_duration)
      except TimeoutError:
        return status


  # Iterator methods

  def __aiter__(self):
    return self

  async def __anext__(self):
    return await self.get_event()


  # Stage

  async def set_x(self, value: int, /):
    """
    Moves the stage to a given x position.

    Args:
      value: The x position [0.1 µm].
    """

    async with self._lock:
      await self._call(0xa8, struct.pack(">i", value))

  async def set_y(self, value: int, /):
    """
    Moves the stage to a given y position.

    Args:
      value: The y position [0.1 µm].
    """

    async with self._lock:
      await self._call(0xac, struct.pack(">i", value))

  async def set_z(self, value: int, /):
    """
    Moves the stage to a given z position.

    Args:
      value: The z position [0.01 µm].
    """

    async with self._lock:
      await self._call(0xa0, struct.pack(">i", value))

  # async def set_z_accuracy(self, value: int, /):
  #   assert 0 <= value <= 9

  #   async with self._lock:
  #     await self._request(b"\x01\x00\x17\xff\x00\x00\xa0\x00\x00\x00" + struct.pack(">B", value))


  # Other controls

  async def set_condenser(self, value: int, /):
    """
    Sets the condenser.

    Args:
      value: The index of the condenser to set, from 0 to 6.
    """

    assert 0 <= value < 7

    async with self._lock:
      await self._call(0x88, struct.pack(">H", value + 1))

  # [100 %]
  async def set_dia(self, value: float, /):
    """
    Sets the diaphragm's opening.

    Args:
      value: The diaphragm's opening, from `0.0` for 0% to `1.0` for 100%.
    """
    assert 0.0 <= value <= 1.0

    async with self._lock:
      await self._call(0xb5, struct.pack(">H", round(value * 2099.0 + 1.0)))

  async def set_filter(self, value: int, /):
    """
    Sets the filter.

    Args:
      value: The index of the filter to set, from 0 to 5.
    """

    assert 0 <= value < 6

    async with self._lock:
      await self._call(0x8c, struct.pack(">H", value + 1))

  async def set_light(self, value: bool, /):
    """
    Enables or disables the light.

    Args:
      value: Whether to enable the light.
    """
    async with self._lock:
      await self._call(0xb4, struct.pack(">x?", value))

  async def set_objective(self, value: int, /):
    """
    Sets the objective.

    Args:
      value: The index of the objective to set, from 0 to 5.
    """
    assert 0 <= value < 6

    async with self._lock:
      await self._call(0x80, struct.pack(">B", value + 1))

  async def set_optical_path(self, value: int, /):
    """
    Sets the optical path.

    Args:
      value: The index of the optical path to set, from 0 to 3.
    """

    assert 0 <= value < 4

    async with self._lock:
      await self._call(0x98, struct.pack(">B", value + 1))

  async def set_shutter(self, value: bool, /):
    """
    Enables or disables the shutter.

    Args:
      value: Whether to enable the shutter.
    """

    async with self._lock:
      await self._call(0x8d, struct.pack(">?", value))


  # Buttons

  async def set_button_function(self, index: int, function: int):
    assert 0 <= index < 8

    async with self._lock:
      await self._request(b"\x01\x00\x03\x28" + struct.pack(">5xB3xB", index, function))

  # async def set_button_notifications(self, e: ButtonPressEvent):
  #   async with self._lock:
  #     await self._request(b"\x01\xa0\x0b\x28" + struct.pack(">10x8I", e.fnL, e.fnR, e.fn1, e.fn2, e.fn3, e.fn4, e.fn5, e.fn6))


  @classmethod
  def list(cls, *, backend: Optional[usb.backend.IBackend] = None):
    """
    Lists available devices.

    Args:
      backend (Optional[usb.backend.IBackend]): The [PyUSB backend](https://github.com/pyusb/pyusb/blob/master/docs/tutorial.rst#specifying-libraries-by-hand) to use. Automatic by default.

    Returns:
      list[MicroscopeDevice]: A list of available devices.
    """
    return [cls(device) for device in usb.core.find(backend=backend, find_all=True, idVendor=0x04b0, idProduct=0x7836)] # type: ignore


__all__ = [
  'ButtonPressEvent',
  'MicroscopeDevice',
  'ObjectiveInfo',
  'StatusEvent'
]
