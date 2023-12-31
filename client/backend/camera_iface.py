# %% Imports
from __future__ import annotations
import json
import sys
from typing import Any, List, Optional
import warnings
import zmq
import zmq.utils.monitor as zmonitor
from datetime import timedelta
import enum
from result import Result, Ok, Err
# %% Commands


class Commands(enum.IntEnum):
    InvalidCommand = -1,         # special
    """Invalid command"""
    ImageFormat = 100,           # string
    """Image format (string)"""
    SensorBitDepth = 101,        # string
    """Sensor bit depth (string)"""
    TrigLine = 102,              # string
    """Trigger line (string)"""
    TrigLineMode = 103,          # string
    """Trigger line mode (string)"""
    TrigLineSrc = 104,           # string
    """Trigger line source (string)"""
    ExposureUs = 105,            # double
    """Exposure time in microseconds (double)"""
    AcqFramerate = 106,          # double
    """Acquisition framerate (double)"""
    AcqFrameRateAuto = 107,      # bool
    """Acquisition framerate auto (bool)"""
    FrameSize = 108,             # int
    """Frame size (int)"""
    ImageSize = 200,             # special, two arguments, ints
    """Imae size (special, two arguments, ints)"""
    ImageOfst = 201,             # special, two arguments, ints
    """Image offset (special, two arguments, ints)"""
    SensorSize = 202,            # special, two arguments, ints
    """Sensor size (special, two arguments, ints)"""
    ThroughputLimit = 300,       # int
    """Throughput limit (int)"""
    ThroughputLimitRange = 301,  # special
    """Throughput limit range (special)"""
    CameraInfo = 302,            # special
    """Camera info (special)"""
    TrigLineSrcs = 303,          # special
    """Trigger line sources (special)"""
    TrigLines = 304,             # special
    """Trigger lines list (special)"""
    ImageFormats = 305,          # special
    """Image formats list (special)"""
    SensorBitDepths = 306,       # special
    """Sensor bit depths list (special)"""
    ADIOBit = 10,                # special
    """ADIO bit (int)"""
    CaptureMaxLen = 400,         # special, int, time in seconds
    """Maximum capture length (special, int, time in seconds)"""


class ReturnCodes(enum.IntEnum):
    VmbErrorSuccess = 0,                  # No error
    VmbErrorInternalFault = -1,           # Unexpected fault in VmbC or driver
    # ::VmbStartup() was not called before the current command
    VmbErrorApiNotStarted = -2,
    # The designated instance (camera, feature etc.) cannot be found
    VmbErrorNotFound = -3,
    VmbErrorBadHandle = -4,               # The given handle is not valid
    VmbErrorDeviceNotOpen = -5,           # Device was not opened for usage
    VmbErrorInvalidAccess = -6,  # Operation is invalid with the current access mode
    # One of the parameters is invalid (usually an illegal pointer)
    VmbErrorBadParameter = -7,
    # The given struct size is not valid for this version of the API
    VmbErrorStructSize = -8,
    VmbErrorMoreData = -9,  # More data available in a string/list than space is provided
    VmbErrorWrongType = -10,          # Wrong feature type for this access function
    # The value is not valid; either out of bounds or not an increment of the minimum
    VmbErrorInvalidValue = -11,
    VmbErrorTimeout = -12,          # Timeout during wait
    VmbErrorOther = -13,          # Other error
    VmbErrorResources = -14,          # Resources not available (e.g. memory)
    # Call is invalid in the current context (e.g. callback)
    VmbErrorInvalidCall = -15,
    VmbErrorNoTL = -16,          # No transport layers are found
    VmbErrorNotImplemented = -17,          # API feature is not implemented
    VmbErrorNotSupported = -18,          # API feature is not supported
    # The current operation was not completed (e.g. a multiple registers read or write)
    VmbErrorIncomplete = -19,
    VmbErrorIO = -20,          # Low level IO error in transport layer
    # The valid value set could not be retrieved, since the feature does not provide this property
    VmbErrorValidValueSetNotPresent = -21,
    VmbErrorGenTLUnspecified = -22,          # Unspecified GenTL runtime error
    VmbErrorUnspecified = -23,          # Unspecified runtime error
    VmbErrorBusy = -24,          # The responsible module/entity is busy executing actions
    VmbErrorNoData = -25,          # The function has no data to work on
    # An error occurred parsing a buffer containing chunk data
    VmbErrorParsingChunkData = -26,
    VmbErrorInUse = -27,          # Something is already in use
    VmbErrorUnknown = -28,          # Error condition unknown
    VmbErrorXml = -29,          # Error parsing XML
    VmbErrorNotAvailable = -30,          # Something is not available
    VmbErrorNotInitialized = -31,          # Something is not initialized
    # The given address is out of range or invalid for internal reasons
    VmbErrorInvalidAddress = -32,
    VmbErrorAlready = -33,          # Something has already been done
    # A frame expected to contain chunk data does not contain chunk data
    VmbErrorNoChunkData = -34,
    # A callback provided by the user threw an exception
    VmbErrorUserCallbackException = -35,
    # The XML for the module is currently not loaded; the module could be in the wrong state or the XML could not be retrieved or could not be parsed properly
    VmbErrorFeaturesUnavailable = -36,
    VmbErrorTLNotFound = -37,  # A required transport layer could not be found or loaded
    # An entity cannot be uniquely identified based on the information provided
    VmbErrorAmbiguous = -39,
    # Something could not be accomplished with a given number of retries
    VmbErrorRetriesExceeded = -40,
    VmbErrorInsufficientBufferCount = -41,  # The operation requires more buffers
    VmbErrorCustom = 1,  # The minimum error code to use for user defined error codes to avoid conflict with existing error codes
# %% Connection


class Camera:
    pass


class CameraConnection:
    """Establish connection to a camera server. Allows for camera enumeration, and property setting/getting.
    """

    def __init__(self, ctx: Optional[zmq.Context] = None, cam_id: Optional[str] = None, host: str = 'localhost', port: int = 5555, quit_on_close: bool = False):
        self._ctx = ctx
        self._cam_id = '' if cam_id is None else cam_id
        self._host = host
        self._port = port
        self._qoc = quit_on_close
        self._packet = {
            'cmd_type': 'list',
            'cam_id': '',
            'command': -1,
            'arguments': [],
            'retcode': 0,
            'retargs': [],
        }
        self._opened = False

    def __del__(self):
        self.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._opened:
            if self._qoc:
                self._packet['cmd_type'] = 'quit'
                self._sock.send(json.dumps(self._packet).encode('utf-8'))
                _ = self._sock.recv()
            self._sock.close()
            self._opened = False

    def open(self):
        if self._ctx is None:
            self._ctx = zmq.Context()
        self._sock: zmq.Socket = self._ctx.socket(zmq.REQ)
        self._sock.setsockopt(zmq.RCVTIMEO, 1000)
        self._sock.setsockopt(zmq.REQ_CORRELATE, 1)
        self._sock.setsockopt(zmq.REQ_RELAXED, 1)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.connect(f"tcp://{self._host}:{self._port}")
        self._sock.send(json.dumps(self._packet).encode('utf-8'))
        reply = self._sock.recv()
        packet = json.loads(reply)
        if packet['retcode'] != ReturnCodes.VmbErrorSuccess:
            raise Exception(
                f'Command {packet["cmd_type"]}: Error: {packet["retcode"]}')
        self._cameras = packet['retargs']
        for idx, camera in enumerate(self._cameras):
            packet['cam_id'] = camera
            packet['cmd_type'] = 'set'
            packet['command'] = Commands.ADIOBit
            packet['arguments'] = [str(idx)]
            self._sock.send(json.dumps(packet).encode('utf-8'))
            reply = self._sock.recv()
            packet = json.loads(reply)
            if packet['retcode'] != ReturnCodes.VmbErrorSuccess:
                retcode = ReturnCodes(packet['retcode'])
                command = Commands(packet['command'])
                warnings.warn(
                    f'Command {packet["cmd_type"]} ({command.name}): Error: {retcode.name}')
        self._opened = True

    @property
    def zmq_context(self) -> zmq.Context:
        return self._ctx

    @property
    def cameras(self) -> List[str]:
        return self._cameras

    @property
    def status(self) -> Result[List[str], ReturnCodes]:
        self._packet['cmd_type'] = 'status'
        self._packet['cam_id'] = ''  # for all
        self._sock.send(json.dumps(self._packet).encode('utf-8'))
        reply = self._sock.recv()
        packet = json.loads(reply)
        if packet['retcode'] != ReturnCodes.VmbErrorSuccess:
            return Err(ReturnCodes(packet['retcode']))
        return Ok(packet['retargs'])

    def set_nocheck(self, camera_id: str, command: Commands, arguments: List[Any]) -> Result[None, ReturnCodes]:
        self._packet['cmd_type'] = 'set'
        self._packet['cam_id'] = camera_id
        self._packet['command'] = command.value
        self._packet['arguments'] = [str(arg) for arg in arguments]
        self._sock.send(json.dumps(self._packet).encode('utf-8'))
        reply = self._sock.recv()
        packet = json.loads(reply)
        retcode = ReturnCodes(packet['retcode'])
        if retcode != ReturnCodes.VmbErrorSuccess:
            return Err(retcode)
        return Ok(None)

    def set(self, camera_id: str, command: Commands, arguments: List[Any]) -> Result[None, ReturnCodes]:
        if camera_id not in self._cameras:
            return None
        return self.set_nocheck(camera_id, command, arguments)

    def get_nocheck(self, camera_id: str, command: Commands) -> Result[List[str], ReturnCodes]:
        self._packet['cmd_type'] = 'get'
        self._packet['cam_id'] = camera_id
        self._packet['command'] = command.value
        self._packet['arguments'] = []
        self._sock.send(json.dumps(self._packet).encode('utf-8'))
        reply = self._sock.recv()
        packet = json.loads(reply)
        if packet['retcode'] != ReturnCodes.VmbErrorSuccess:
            return Err(ReturnCodes(packet['retcode']))
        return Ok(packet['retargs'])

    def get(self, camera_id: str, command: Commands) -> Result[List[str], ReturnCodes]:
        if camera_id not in self._cameras:
            return None
        return self.get_nocheck(camera_id, command)

    def get_camera(self, camera_id: str) -> Camera:
        return Camera(self, camera_id)

    @property
    def capture_maxlen(self) -> timedelta:
        res = self.get_nocheck(self._cameras[0], Commands.CaptureMaxLen)
        print(res)
        if res.is_err():
            return timedelta(0)
        return timedelta(milliseconds=float(res.unwrap()[0]))

    @capture_maxlen.setter
    def capture_maxlen(self, value: timedelta):
        self.set_nocheck(self._cameras[0], Commands.CaptureMaxLen, [
                         value.total_seconds()*1e3])


class Camera:
    """Camera object for setting/getting camera properties.
    """

    def __init__(self, parent: CameraConnection, cam_id: str):
        self._parent = parent
        self._cam_id = cam_id

    @property
    def status(self) -> Result[List[str], ReturnCodes]:
        """Get camera status.

        Returns:
            Result[List[str], ReturnCodes]: Status list or error code.
        """
        self._parent._packet['cmd_type'] = 'status'
        self._parent._packet['cam_id'] = self._cam_id  # for all
        self._parent._sock.send(json.dumps(
            self._parent._packet).encode('utf-8'))
        reply = self._parent._sock.recv()
        packet = json.loads(reply)
        if packet['retcode'] != ReturnCodes.VmbErrorSuccess:
            return Err(ReturnCodes(packet['retcode']))
        return Ok(packet['retargs'])

    def set(self, command: Commands, arguments: List[Any]) -> Result[None, ReturnCodes]:
        """Set a camera property.

        Args:
            command (Commands): Property command.
            arguments (List[Any]): List of arguments.

        Returns:
            Result[None, ReturnCodes]: Ok on success, Err on failure.
        """
        return self._parent.set(self._cam_id, command, arguments)

    def get(self, command: Commands) -> Result[List[str], ReturnCodes]:
        return self._parent.get(self._cam_id, command)

    @property
    def sensor_size(self) -> List[int]:
        """Get the sensor size in pixels

        Returns:
            List[int]: width, height
        """
        res = self.get(Commands.SensorSize)
        if res.is_err():
            return []
        return list(map(int, res.unwrap()))

    @property
    def image_size(self) -> List[int]:
        """Get the image size in pixels

        Returns:
            List[int]: width, height
        """
        res = self.get(Commands.ImageSize)
        if res.is_err():
            return []
        return list(map(int, res.unwrap()))

    @image_size.setter
    def image_size(self, value: List[int]):
        self.set(Commands.ImageSize, value)

    @property
    def image_ofst(self) -> List[int]:
        """Get the image offset in pixels

        Returns:
            List[int]: x, y
        """
        res = self.get(Commands.ImageOfst)
        if res.is_err():
            return []
        return list(map(int, res.unwrap()))

    @image_ofst.setter
    def image_ofst(self, value: List[int]):
        """Set image offset in pixels

        Args:
            value (List[int]): Offset x, Offset y
        """
        self.set(Commands.ImageOfst, value)

    @property
    def trigger_line(self) -> str:
        """Get the selected trigger line

        Returns:
            str: trigger line name
        """
        res = self.get(Commands.TrigLine)
        if res.is_err():
            return ''
        return res.unwrap()[0]

    @trigger_line.setter
    def trigger_line(self, value: str):
        """Set the selected trigger line

        Args:
            value (str): Trigger line name
        """
        self.set(Commands.TrigLine, [value])

    @property
    def trigger_lines(self) -> List[str]:
        """Get the available trigger lines

        Returns:
            List[str]: trigger line names
        """
        res = self.get(Commands.TrigLines)
        if res.is_err():
            return []
        return res.unwrap()

    @property
    def trigger_mode(self) -> str:
        """Get the mode of the selected trigger line

        Returns:
            str: Input/Output
        """
        res = self.get(Commands.TrigLineMode)
        if res.is_err():
            return ''
        return res.unwrap()[0]

    @trigger_mode.setter
    def trigger_mode(self, mode: str):
        if mode not in ['Input', 'Output']:
            raise Exception('Invalid trigger mode')
        self.set(Commands.TrigLineMode, [mode])

    @property
    def trigger_srcs(self) -> List[str]:
        """Get the available trigger sources for the selected trigger line.

        Returns:
            List[str]: trigger source names.
        """
        res = self.get(Commands.TrigLineSrcs)
        if res.is_err():
            return []
        return res.unwrap()

    @property
    def trigger_src(self) -> str:
        """Get the output source for the selected trigger line.

        Returns:
            str: trigger source name.
        """
        res = self.get(Commands.TrigLineSrc)
        if res.is_err():
            return ''
        return res.unwrap()[0]

    @trigger_src.setter
    def trigger_src(self, value: str):
        self.set(Commands.TrigLineSrc, [value])

    @property
    def exposure(self) -> timedelta:
        """Get the exposure time

        Returns:
            Timedelta: exposure time
        """
        res = self.get(Commands.ExposureUs)
        if res.is_err():
            return timedelta(0)
        return timedelta(microseconds=float(res.unwrap()[0]))

    @exposure.setter
    def exposure(self, value: timedelta):
        self.set(Commands.ExposureUs, [value.total_seconds()*1e6])

    @property
    def framerate_auto(self) -> Optional[bool]:
        """Get the auto framerate setting

        Returns:
            bool: True if auto framerate is enabled
        """
        res = self.get(Commands.AcqFrameRateAuto)
        if res.is_err():
            return None
        return res.unwrap()[0] == 'True'

    @framerate_auto.setter
    def framerate_auto(self, value: bool):
        self.set(Commands.AcqFrameRateAuto, [str(value)])

    @property
    def framerate(self) -> float:
        """Get the framerate

        Returns:
            float: framerate
        """
        res = self.get(Commands.AcqFramerate)
        if res.is_err():
            return 0
        return float(res.unwrap()[0])

    @framerate.setter
    def framerate(self, value: float):
        self.set(Commands.AcqFramerate, [value])

    @property
    def image_format(self) -> str:
        """Get the image format

        Returns:
            str: image format
        """
        res = self.get(Commands.ImageFormat)
        if res.is_err():
            return ''
        return res.unwrap()[0]

    @image_format.setter
    def image_format(self, value: str):
        self.set(Commands.ImageFormat, [value])

    @property
    def image_formats(self) -> List[str]:
        """Get the available image formats

        Returns:
            List[str]: image formats
        """
        res = self.get(Commands.ImageFormats)
        if res.is_err():
            return []
        return res.unwrap()

    @property
    def sensor_bit_depth(self) -> str:
        """Get the sensor bit depth

        Returns:
            str: sensor bit depth
        """
        res = self.get(Commands.SensorBitDepth)
        if res.is_err():
            return ''
        return res.unwrap()[0]

    @sensor_bit_depth.setter
    def sensor_bit_depth(self, value: str):
        self.set(Commands.SensorBitDepth, [value])

    @property
    def sensor_bit_depths(self) -> List[str]:
        """Get the available sensor bit depths

        Returns:
            List[str]: sensor bit depths
        """
        res = self.get(Commands.SensorBitDepths)
        if res.is_err():
            return []
        return res.unwrap()

    @property
    def througput_limit(self) -> int:
        """Get the throughput limit

        Returns:
            int: throughput limit
        """
        res = self.get(Commands.ThroughputLimit)
        if res.is_err():
            return 0
        return int(res.unwrap()[0])

    @througput_limit.setter
    def througput_limit(self, value: int):
        self.set(Commands.ThroughputLimit, [value])

    @property
    def througput_limit_range(self) -> List[int]:
        """Get the throughput limit range

        Returns:
            List[int]: throughput limit range
        """
        res = self.get(Commands.ThroughputLimitRange)
        if res.is_err():
            return []
        return list(map(int, res.unwrap()))

    def max_exposure(self, retry: int = 50) -> timedelta:
        """Get the maximum exposure time for a set framerate.

        Args:
            retry (int, optional): Number of retries to find the maximum exposure time. Defaults to 50.

        Returns:
            timedelta: maximum exposure time
        """
        auto = self.framerate_auto

        fps_target = fps = self.framerate
        exposure_max = timedelta(microseconds=50)
        increment = timedelta(seconds=1/fps) * 0.25
        self.exposure = exposure_max
        exposure_prev = timedelta(seconds=1/fps)
        while abs((exposure_prev - exposure_max).total_seconds()) > 50e-6 and retry > 0 and increment.total_seconds() > 10e-6:
            exposure_prev = exposure_max
            while self.framerate >= fps_target:
                exposure_max += increment
                self.exposure = exposure_max
                exposure_max = self.exposure
                if not auto:
                    self.framerate = fps_target
                retry -= 1
            # flip!
            increment /= 2
            while self.framerate < fps_target:
                exposure_max -= increment
                self.exposure = exposure_max
                exposure_max = self.exposure
                if not auto:
                    self.framerate = fps_target
                retry -= 1
            # flip!
            increment /= 2

        return exposure_max
# %% Test


def main():
    with CameraConnection() as cam_man:
        print(cam_man.cameras)
        if len(cam_man.cameras) == 0:
            sys.exit(0)
        print(cam_man.status)
        print(cam_man.capture_maxlen)
        cam = cam_man.get_camera(cam_man.cameras[0])
        print(cam.status)
        print(cam.sensor_size)
        print(cam.image_size)
        print(cam.image_ofst)
        print(cam.trigger_line)
        print(cam.trigger_lines)
        print(cam.trigger_mode)
        print(cam.trigger_src)
        print(cam.trigger_srcs)
        cam.trigger_mode = 'Output'
        cam.trigger_src = 'ExposureActive'
        print(cam.trigger_src)
        print(cam.exposure)
        cam.exposure = timedelta(microseconds=100)
        print(cam.exposure)
        print(cam.framerate_auto)
        cam.framerate_auto = True
        print(cam.framerate_auto)
        print(cam.framerate)
        print(cam.image_format)
        print(cam.image_formats)
        print(cam.sensor_bit_depth)
        print(cam.sensor_bit_depths)
        print(cam.througput_limit)
        print(cam.througput_limit_range)
        cam.image_size = [256, 256]
        print(cam.image_size)
        print(cam.framerate)
        maxexp = cam.max_exposure()
        print(cam.framerate)
        print(maxexp)
        cam.exposure = maxexp
        print(cam.exposure)
        print(cam.framerate)

        cam.framerate_auto = False
        cam.framerate = 100
        print(cam.framerate)
        maxexp = cam.max_exposure()
        print(cam.framerate)
        print(maxexp)
        cam.exposure = maxexp
        print(cam.exposure)
        print(cam.framerate)


if __name__ == '__main__':
    main()
