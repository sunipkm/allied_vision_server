/**
 * @file main.cpp
 * @author Mit Bailey (mitbailey@outlook.com)
 * @brief
 * @version See Git tags for version information.
 * @date 2023.11.28
 *
 * @copyright Copyright (c) 2023
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <string.h>
#include <czmq.h>
#include <math.h>
#include <vector>
#include <map>
#include <string>
#include <stdarg.h>
#include <signal.h>

#include "server.hpp"
#include "imagecam.hpp"
#include "stringhasher.hpp"
#include "string_format.hpp"

volatile sig_atomic_t done = 0;

void sighandler(int sig)
{
    done = 1;
}

int main(int argc, char *argv[])
{
    // signal handler
    signal(SIGINT, sighandler);
    // arguments
    int adio_minor_num = 0;
    int port = 5555;
    std::string camera_id = "";
    // Argument parsing
    {
        int c;
        while ((c = getopt(argc, argv, "c:a:h")) != -1)
        {
            switch (c)
            {
            case 'c':
            {
                printf("Camera ID from command line: %s\n", optarg);
                camera_id = optarg;
                break;
            }
            case 'a':
            {
                printf("ADIO minor number: %s\n", optarg);
                adio_minor_num = atoi(optarg);
                break;
            }
            case 'p':
            {
                printf("Port number: %s\n", optarg);
                port = atoi(optarg);
                if (port < 5000 || port > 65535)
                {
                    dbprintlf(RED_FG "Invalid port number: %d", port);
                    exit(EXIT_FAILURE);
                }
                break;
            }
            case 'h':
            default:
            {
                printf("\nUsage: %s [-c Camera ID] [-a ADIO Minor Device] [-p ZMQ Port] [-h Show this message]\n\n", argv[0]);
                exit(EXIT_SUCCESS);
            }
            }
        }
    }
    // Create the pipe name
    std::string pipe_name = string_format("tcp://*:%d", port);
    // Set up ADIO
    DeviceHandle adio_dev = nullptr;
    if (OpenDIO_aDIO(&adio_dev, adio_minor_num) != 0)
    {
        dbprintlf(RED_FG "Could not initialize ADIO API. Check if /dev/rtd-aDIO* exists. aDIO features will be disabled.");
        adio_dev = nullptr;
    }
    else
    {
        // set up port A as output and set all bits to low
        int ret = LoadPort0BitDir_aDIO(adio_dev, 1, 1, 1, 1, 1, 1, 1, 1);
        if (ret == -1)
        {
            dbprintlf(RED_FG "Could not set PORT0 to output.");
        }
        else
        {
            ret = WritePort_aDIO(adio_dev, 0, 0); // set all to low
            if (ret < 0)
            {
                dbprintlf(RED_FG "Could not set all PORT0 bits to LOW: %s [%d]", strerror(ret), ret);
            }
        }
    }
    // Initialize String Hasher
    StringHasher hasher = StringHasher();
    // Set up cameras
    std::vector<uint32_t> camids;
    std::map<uint32_t, CameraInfo> caminfos;
    std::map<uint32_t, ImageCam> imagecams;

    VmbError_t err = allied_init_api(NULL);
    if (err != VmbErrorSuccess)
    {
        dbprintlf(FATAL "Failed to initialize Allied Vision API: %s", allied_strerr(err));
        return 1;
    }

    VmbUint32_t count;
    VmbCameraInfo_t *vmbcaminfos;
    err = allied_list_cameras(&vmbcaminfos, &count);
    if (err != VmbErrorSuccess)
    {
        dbprintlf(FATAL "Failed to list cameras: %s", allied_strerr(err));
        return 1;
    }
    if (count == 0)
    {
        dbprintlf(FATAL "No cameras found.");
        return 1;
    }
    for (VmbUint32_t idx = 0; idx < count; idx++)
    {
        CameraInfo caminfo = CameraInfo(vmbcaminfos[idx]);
        uint32_t hash = hasher.get_hash(caminfo.idstr);
        camids.push_back(hash);
        caminfos.insert(std::pair<uint32_t, CameraInfo>(hash, caminfo));
        dbprintlf("Camera %d: %s", idx, caminfo.idstr.c_str());
        dbprintlf("Camera %d: %s", idx, caminfo.name.c_str());
        dbprintlf("Camera %d: %s", idx, caminfo.model.c_str());
        dbprintlf("Camera %d: %s", idx, caminfo.serial.c_str());
        if (camera_id != "" && camera_id != caminfo.idstr) // if a camera id was specified and it doesn't match this camera
        {
            continue;
        }
        imagecams.insert(std::pair<uint32_t, ImageCam>(hash, ImageCam(caminfo, adio_dev)));
    }
    free(vmbcaminfos);
    // Setup ZMQ.
    zsock_t *pipe = zsock_new_rep(pipe_name.c_str());
    assert(pipe);
    zpoller_t *poller = zpoller_new(pipe, NULL);
    assert(poller);
    // Loop, waiting for ZMQ commands and performing them as necessary.
    while (!done)
    {
        zsock_t *which = (zsock_t *)zpoller_wait(poller, 1000); // wait a second
        if (which == NULL)
        {
            continue;
        }
        char *message = zstr_recv(which);
        if (message == NULL)
        {
            continue;
        }
        NetPacket packet = json::parse(message);
        zstr_free(&message);

        packet.retargs.clear();                          // clear return arguments
        uint32_t chash = hasher.get_hash(packet.cam_id); // get camera hash
        VmbError_t err = VmbErrorSuccess;                // set default error

        if (packet.cmd_type == "quit")
        {
            done = 1;
        }
        else if (packet.cmd_type == "list")
        {
            // list cameras
            for (auto &hash : camids)
            {
                packet.retargs.push_back(std::to_string(hash));
            }
        }
        else if (packet.cmd_type == "start_capture_all")
        {
            err = VmbErrorSuccess;
            for (auto &image_cam : imagecams)
            {
                err = image_cam.second.start_capture();
                if (err != VmbErrorSuccess)
                {
                    break;
                }
            }
        }
        else if (packet.cmd_type == "stop_capture_all")
        {
            err = VmbErrorSuccess;
            for (auto &image_cam : imagecams)
            {
                err = image_cam.second.stop_capture();
                if (err != VmbErrorSuccess)
                {
                    break;
                }
            }
        }
        else if (packet.cmd_type == "start_capture")
        {
            try
            {
                ImageCam image_cam = imagecams.at(chash);
                err = image_cam.start_capture(); // do this for specific camera id
            }
            catch (const std::out_of_range &oor)
            {
                err = VmbErrorNotFound;
            }
        }
        else if (packet.cmd_type == "stop_capture")
        {
            try
            {
                ImageCam image_cam = imagecams.at(chash);
                err = image_cam.stop_capture(); // do this for specific camera id
            }
            catch (const std::out_of_range &oor)
            {
                err = VmbErrorNotFound;
            }
        }
        else if (packet.cmd_type == "get")
        {
            try
            {
                ImageCam image_cam = imagecams.at(chash);
                std::vector<std::string> reply;
                switch (packet.command)
                {
                    GET_CASE_STR(image_format)
                    GET_CASE_STR(sensor_bit_depth)
                    GET_CASE_STR(trigline)
                    GET_CASE_STR(trigline_src)
                    GET_CASE_DBL(exposure_us)
                    GET_CASE_DBL(acq_framerate)
                    GET_CASE_BOOL(acq_framerate_auto)
                    GET_CASE_INT(throughput_limit)
                case CommandNames::frame_size:
                {
                    uint32_t fsize = allied_get_frame_size(image_cam.handle);
                    reply.push_back(std::to_string(fsize));
                    break;
                }
                case CommandNames::sensor_size:
                {
                    VmbInt64_t width = 0, height = 0;
                    err = allied_get_sensor_size(image_cam.handle, &width, &height);
                    reply.push_back(std::to_string(width));
                    reply.push_back(std::to_string(height));
                    break;
                }
                case CommandNames::image_size:
                {
                    VmbInt64_t width = 0, height = 0;
                    err = allied_get_image_size(image_cam.handle, &width, &height);
                    reply.push_back(std::to_string(width));
                    reply.push_back(std::to_string(height));
                    break;
                }
                case CommandNames::image_ofst:
                {
                    VmbInt64_t width = 0, height = 0;
                    err = allied_get_image_ofst(image_cam.handle, &width, &height);
                    reply.push_back(std::to_string(width));
                    reply.push_back(std::to_string(height));
                    break;
                }
                case CommandNames::adio_bit:
                {
                    reply.push_back(std::to_string(image_cam.adio_bit));
                    break;
                }
                case CommandNames::throughput_limit_range:
                {
                    VmbInt64_t vmin = 0, vmax = 0;
                    err = allied_get_throughput_limit_range(image_cam.handle, &vmin, &vmax, NULL);
                    reply.push_back(std::to_string(vmin));
                    reply.push_back(std::to_string(vmax));
                    break;
                }
                case CommandNames::camera_info:
                {
                    reply.push_back(std::to_string(image_cam.get_info()));
                }
                default:
                {
                    err = VmbErrorWrongType; // wrong command
                    break;
                }
                }
                packet.retargs = reply;
            }
            catch (const std::out_of_range &oor)
            {
                err = VmbErrorNotFound;
            }
        }
        else if (packet.cmd_type == "set")
        {
            if (packet.arguments.size() < 1) // no data to set
            {
                err = VmbErrorNoData;
            }
            else
            {
                std::vector<std::string> reply;
                const char *argument = packet.arguments[0].c_str(); // this must exist at this point
                try
                {
                    ImageCam image_cam = imagecams.at(chash);
                    switch (packet.command)
                    {
                        SET_CASE_STR(image_format)
                        SET_CASE_STR(sensor_bit_depth)
                        SET_CASE_STR(trigline)
                        SET_CASE_STR(trigline_src)
                        SET_CASE_DBL(exposure_us)
                        SET_CASE_DBL(acq_framerate)
                        SET_CASE_BOOL(acq_framerate_auto)
                        SET_CASE_INT(throughput_limit)
                    case CommandNames::image_size:
                    {
                        if (packet.arguments.size() != 2)
                        {
                            err = VmbErrorWrongType;
                            break;
                        }
                        VmbInt64_t arg1l = atol(packet.arguments[0].c_str());
                        VmbInt64_t arg2l = atol(packet.arguments[1].c_str());
                        err = allied_set_image_size(image_cam.handle, arg1l, arg2l);
                        err = allied_get_image_size(image_cam.handle, &arg1l, &arg2l);
                        reply.push_back(std::to_string(arg1l));
                        reply.push_back(std::to_string(arg2l));
                        break;
                    }
                    case CommandNames::image_ofst:
                    {
                        if (packet.arguments.size() != 2)
                        {
                            err = VmbErrorWrongType;
                            break;
                        }
                        VmbInt64_t arg1l = atol(packet.arguments[0].c_str());
                        VmbInt64_t arg2l = atol(packet.arguments[1].c_str());
                        err = allied_set_image_ofst(image_cam.handle, arg1l, arg2l);
                        err = allied_get_image_ofst(image_cam.handle, &arg1l, &arg2l);
                        reply.push_back(std::to_string(arg1l));
                        reply.push_back(std::to_string(arg2l));
                        break;
                    }
                    case CommandNames::adio_bit:
                    {
                        long arg1l = atol(argument);
                        image_cam.adio_bit = arg1l;
                        reply.push_back(std::to_string(arg1l));
                        break;
                    }
                    default:
                    {
                        err = VmbErrorWrongType; // wrong command
                        break;
                    }
                    }
                }
                catch (const std::out_of_range &oor)
                {
                    err = VmbErrorNotFound;
                }
                packet.retargs = reply;
            }
        }
        else
        {
            err = VmbErrorBadParameter; // wrong command
        }
        packet.retcode = err; // set return code
        // send reply
        json j = packet;
        zstr_send(which, j.dump().c_str());
    }
    // Cleanup
    zpoller_destroy(&poller);
    zsock_destroy(&pipe);

    if (adio_dev != nullptr)
        CloseDIO_aDIO(adio_dev);

    return 0;
}