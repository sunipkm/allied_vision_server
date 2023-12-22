#pragma once

#include <assert.h>
#include <zclock.h>
#include "meb_print.h"
#include "alliedcam.h"
#include "aDIO_library.h"
#include <string>
#include <stdexcept>

class CharContainer
{
private:
    char *strdup(const char *str)
    {
        int len = strlen(str);
        char *out = new char[len + 1];
        strcpy(out, str);
        return out;
    }

public:
    char **arr = nullptr;
    int narr = 0;
    int selected;
    size_t maxlen = 0;

    ~CharContainer()
    {
        if (arr)
        {
            for (int i = 0; i < narr; i++)
            {
                delete[] arr[i];
            }
            delete[] arr;
        }
    }

    CharContainer()
    {
        arr = nullptr;
        narr = 0;
        selected = -1;
    }

    CharContainer(const char **arr, int narr)
    {
        this->arr = new char *[narr];
        this->narr = narr;
        this->selected = -1;
        for (int i = 0; i < narr; i++)
        {
            this->arr[i] = strdup(arr[i]);
            if (strlen(arr[i]) > maxlen)
            {
                maxlen = strlen(arr[i]);
            }
        }
    }

    CharContainer(const char **arr, int narr, const char *key)
    {
        this->arr = new char *[narr];
        this->narr = narr;
        for (int i = 0; i < narr; i++)
        {
            this->arr[i] = strdup(arr[i]);
            if (strlen(arr[i]) > maxlen)
            {
                maxlen = strlen(arr[i]);
            }
        }
        this->selected = find_idx(key);
    }

    int find_idx(const char *str)
    {
        int res = -1;
        for (int i = 0; i < narr; i++)
        {
            if (strcmp(arr[i], str) == 0)
                res = i;
        }
        return res;
    }
};

class CameraInfo
{
public:
    std::string idstr;
    std::string name;
    std::string model;
    std::string serial;

    CameraInfo()
    {
        idstr = "";
        name = "";
        model = "";
        serial = "";
    }

    CameraInfo(VmbCameraInfo_t info)
    {
        idstr = info.cameraIdString;
        name = info.cameraName;
        model = info.modelName;
        serial = info.serialString;
    }

    CameraInfo(VmbCameraInfo_t *info)
    {
        idstr = info->cameraIdString;
        name = info->cameraName;
        model = info->modelName;
        serial = info->serialString;
    }
};

namespace std
{
    std::string to_string(const CameraInfo &info) noexcept
    {
        std::string reply = "ID: " + info.idstr + ",\n";
        reply += "Name: " + info.name + ",\n";
        reply += "Model: " + info.model + ",\n";
        reply += "Serial: " + info.serial + ",\n";
        return reply;
    }
};

class ImageCam
{
    bool opened = false;
    unsigned char state = 0;
    bool capturing;
    DeviceHandle adio_hdl = nullptr;
    CameraInfo info;
    int64_t capture_start_time = -1;
    uint64_t frames = 0;

    ImageCam(const ImageCam &other) = delete;

public:
    int adio_bit = -1;
    AlliedCameraHandle_t handle = nullptr;

    CameraInfo &get_info()
    {
        return info;
    }

    ImageCam()
    {
        handle = nullptr;
        capturing = false;
    }

    ImageCam(CameraInfo &camera_info, DeviceHandle adio_hdl)
    {
        handle = nullptr;
        capturing = false;
        this->adio_hdl = adio_hdl;
        this->info = camera_info;
        if (allied_open_camera(&handle, info.idstr.c_str(), 5) != VmbErrorSuccess)
        {
            dbprintlf(FATAL "Failed to open camera %s.", camera_info.idstr.c_str());
            throw std::runtime_error("Failed to open camera.");
        }
    }

    ~ImageCam()
    {
        close_camera();
    }

    static void Callback(const AlliedCameraHandle_t handle, const VmbHandle_t stream, VmbFrame_t *frame, void *user_data)
    {
        assert(user_data);

        ImageCam *self = (ImageCam *)user_data;
        self->frames++;
        if (self->adio_hdl != nullptr && self->adio_bit >= 0)
        {
            self->state = ~self->state;
            WriteBit_aDIO(self->adio_hdl, 0, self->adio_bit, self->state);
        }

        // self->stat.update();
        // self->img.update(frame);
    }

    void open_camera()
    {
        std::string errmsg = "";
        VmbError_t err = allied_open_camera(&handle, info.idstr.c_str(), 5);
        if (err != VmbErrorSuccess)
        {
            errmsg = "Could not open camera: " + std::string(allied_strerr(err));
            dbprintlf(FATAL "%s", errmsg.c_str());
            return;
        }
        CharContainer *triglines = nullptr;
        CharContainer *trigsrcs = nullptr;
        char *key = nullptr;
        char **arr = nullptr;
        VmbUint32_t narr = 0;
        err = allied_get_trigline(handle, (const char **)&key);
        if (err == VmbErrorSuccess)
        {
            err = allied_get_triglines_list(handle, &arr, NULL, &narr);
            if (err == VmbErrorSuccess)
            {
                triglines = new CharContainer((const char **)arr, narr, (const char *)key);
                free(arr);
                narr = 0;
            }
            else
            {
                dbprintlf("Could not get trigger lines list: %s", allied_strerr(err));
            }
        }
        else
        {
            dbprintlf("Could not get selected trigger line: %s", allied_strerr(err));
        }
        if (triglines != nullptr)
        {
            // set all trigger lines to output
            for (int i = 0; i < triglines->narr; i++)
            {
                char *line = triglines->arr[i];
                err = allied_set_trigline(handle, line);
                if (err != VmbErrorSuccess)
                {
                    dbprintlf("Could not select line %s: %s", line, allied_strerr(err));
                }
                else
                {
                    err = allied_set_trigline_mode(handle, "Output");
                    if (err != VmbErrorSuccess)
                        dbprintlf("Could not set line %s to output: %s", line, allied_strerr(err));
                }
            }
            err = allied_set_trigline(handle, key);
            if (err != VmbErrorSuccess)
                dbprintlf("Could not select line %s: %s", key, allied_strerr(err));
            // get trigger source
            err = allied_get_trigline_src(handle, (const char **)&key);
            if (err == VmbErrorSuccess)
            {
                err = allied_get_trigline_src_list(handle, &arr, NULL, &narr);
                if (err == VmbErrorSuccess)
                {
                    trigsrcs = new CharContainer((const char **)arr, narr, (const char *)key);
                    free(arr);
                    narr = 0;
                }
                else
                {
                    dbprintlf("Could not get trigger sources list: %s", allied_strerr(err));
                }
            }
        }
        delete triglines;
        delete trigsrcs;
        opened = true;
        // std::cout << "Opened!" << std::endl;
    }

    void cleanup()
    {
        if (opened)
        {
            allied_stop_capture(handle);  // just stop capture...
            allied_close_camera(&handle); // close the camera
            opened = false;
        }
    }

    void close_camera()
    {
        cleanup();
        opened = false;
    }

    bool running() const
    {
        return capturing;
    }

    int64_t capture_time() const
    {
        if (capture_start_time < 0)
            return -1;
        return zclock_mono() - capture_start_time;
    }

    int64_t capture_time(int64_t tnow) const
    {
        if (capture_start_time < 0)
            return -1;
        return tnow - capture_start_time;
    }

    VmbError_t start_capture()
    {
        VmbError_t err = VmbErrorSuccess;
        frames = 0;
        if (handle != nullptr && !capturing)
        {
            err = allied_start_capture(handle, &Callback, (void *)this); // set the callback here
        }
        if (err == VmbErrorSuccess)
        {
            capture_start_time = zclock_mono();
            capturing = true;
        }
        else
        {
            capture_start_time = -1;
        }
        return err;
    }

    VmbError_t stop_capture()
    {
        VmbError_t err = VmbErrorSuccess;
        if (handle != nullptr && capturing)
        {
            err = allied_stop_capture(handle);
            if (adio_hdl != nullptr && adio_bit >= 0)
            {
                this->state = 0;
                WriteBit_aDIO(adio_hdl, 0, adio_bit, this->state);
            }
        }
        capturing = false;
        capture_start_time = -1;
        return err;
    }

    uint64_t get_frames() const
    {
        return frames;
    }
};