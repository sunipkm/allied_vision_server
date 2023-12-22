# %% Imports
import sys
from datetime import timedelta
from backend import CameraConnection
from backend import openAD2, GetDigitalData, DwfDigitalInTriggerType, DwfMaximizeBuffer
# %%
with CameraConnection() as cam_man, openAD2(buffer_maximize=DwfMaximizeBuffer.DigitalIn) as ad2:
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

# %%
