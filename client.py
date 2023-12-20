# %% Imports
from __future__ import annotations
import sys
import json
import time
from typing import Any, List, Optional
import warnings
import zmq
import signal
import zmq.utils.monitor as zmonitor
from datetime import datetime
import enum
from result import Result, Ok, Err
# %% Commands


class Commands(enum.IntEnum):
    InvalidCommand = -1,         # special
    ImageFormat = 100,           # string
    SensorBitDepth = 101,        # string
    TrigLine = 102,              # string
    TrigLineMode = 103,          # string
    TrigLineSrc = 104,           # string
    ExposureUs = 105,            # double
    AcqFramerate = 106,          # double
    AcqFrameRateAuto = 107,      # bool
    FrameSize = 108,             # int
    ImageSize = 200,             # special, two arguments, ints
    ImageOfst = 201,             # special, two arguments, ints
    SensorSize = 202,            # special, two arguments, ints
    ThroughputLimit = 300,       # int
    ThroughputLimitRange = 301,  # special
    CameraInfo = 302,            # special
    TrigLineModeSrc = 303,       # special
    ADIOBit = 10,                # special
    CaptureMaxLen = 400,         # special, int, time in seconds


class ReturnCodes(enum.IntEnum):
    VmbErrorSuccess = 0,           # No error
    VmbErrorInternalFault = -1,           # Unexpected fault in VmbC or driver
    # ::VmbStartup() was not called before the current command
    VmbErrorApiNotStarted = -2,
    # The designated instance (camera, feature etc.) cannot be found
    VmbErrorNotFound = -3,
    VmbErrorBadHandle = -4,           # The given handle is not valid
    VmbErrorDeviceNotOpen = -5,           # Device was not opened for usage
    # Operation is invalid with the current access mode
    VmbErrorInvalidAccess = -6,
    # One of the parameters is invalid (usually an illegal pointer)
    VmbErrorBadParameter = -7,
    # The given struct size is not valid for this version of the API
    VmbErrorStructSize = -8,
    # More data available in a string/list than space is provided
    VmbErrorMoreData = -9,
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
    # A required transport layer could not be found or loaded
    VmbErrorTLNotFound = -37,
    # An entity cannot be uniquely identified based on the information provided
    VmbErrorAmbiguous = -39,
    # Something could not be accomplished with a given number of retries
    VmbErrorRetriesExceeded = -40,
    # The operation requires more buffers
    VmbErrorInsufficientBufferCount = -41,
    # The minimum error code to use for user defined error codes to avoid conflict with existing error codes
    VmbErrorCustom = 1,
# %% Connection


class Camera:
    pass


class CameraConnection:
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

    def set(self, camera_id: str, command: Commands, arguments: List[Any]) -> Result[None, ReturnCodes]:
        if camera_id not in self._cameras:
            return None
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

    def get(self, camera_id: str, command: Commands) -> Result[List[str], ReturnCodes]:
        if camera_id not in self._cameras:
            return None
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

    def get_camera(self, camera_id: str) -> Camera:
        return Camera(self, camera_id)


class Camera:
    def __init__(self, parent: CameraConnection, cam_id: str):
        self._parent = parent
        self._cam_id = cam_id

    @property
    def status(self)->Result[List[str], ReturnCodes]:
        self._parent._packet['cmd_type'] = 'status'
        self._parent._packet['cam_id'] = self._cam_id  # for all
        self._parent._sock.send(json.dumps(self._parent._packet).encode('utf-8'))
        reply = self._parent._sock.recv()
        packet = json.loads(reply)
        if packet['retcode'] != ReturnCodes.VmbErrorSuccess:
            return Err(ReturnCodes(packet['retcode']))
        return Ok(packet['retargs'])
    
    def set(self, command: Commands, arguments: List[Any]) -> Result[None, ReturnCodes]:
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
        self.set(Commands.TrigLine, [value])

    @property
    def trigger_mode(self)->str:
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
        res = self.get(Commands.TrigLineModeSrc)
        print(res)
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

# %%
with CameraConnection() as cam_man:
    print(cam_man.cameras)
    if len(cam_man.cameras) == 0:
        sys.exit(0)
    print(cam_man.status)
    cam = cam_man.get_camera(cam_man.cameras[0])
    print(cam.status)
    print(cam.sensor_size)
    print(cam.image_size)
    print(cam.image_ofst)
    print(cam.trigger_line)
    print(cam.trigger_mode)
    print(cam.trigger_src)
    print(cam.trigger_srcs)
    cam.trigger_mode = 'Output'
    cam.trigger_src = 'ExposureActive'
    print(cam.trigger_src)

# %%
