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

int main(int argc, char *argv[])
{
    // Initialize ZSYS
    void *zctx = zsys_init();
    if (zctx == NULL)
    {
        dbprintlf(FATAL "Could not initialize ZSYS.");
        return 1;
    }
    // arguments
    int adio_minor_num = 0;
    int port = 5555;
    std::string camera_id = "";
    char *cti_path = NULL;
    // Argument parsing
    {
        int c;
        while ((c = getopt(argc, argv, "c:a:p:d:h")) != -1)
        {
            switch (c)
            {
            case 'c':
            {
                ZSYS_INFO("Camera ID from command line: %s\n", optarg);
                camera_id = optarg;
                break;
            }
            case 'a':
            {
                ZSYS_INFO("ADIO minor number: %s\n", optarg);
                adio_minor_num = atoi(optarg);
                break;
            }
            case 'p':
            {
                ZSYS_INFO("Port number: %s\n", optarg);
                port = atoi(optarg);
                if (port < 5000 || port > 65535)
                {
                    ZSYS_ERROR("Invalid port number: %d", port);
                    exit(EXIT_FAILURE);
                }
                break;
            }
            case 'd':
            {
                ZSYS_INFO("CTI directory: %s\n", optarg);
                cti_path = optarg;
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
        ZSYS_WARNING("Could not initialize ADIO API. Check if /dev/rtd-aDIO* exists. aDIO features will be disabled.");
        adio_dev = nullptr;
    }
    else
    {
        // set up port A as output and set all bits to low
        int ret = LoadPort0BitDir_aDIO(adio_dev, 1, 1, 1, 1, 1, 1, 1, 1);
        if (ret == -1)
        {
            ZSYS_ERROR("Could not set PORT0 to output.");
        }
        else
        {
            ret = WritePort_aDIO(adio_dev, 0, 0); // set all to low
            if (ret < 0)
            {
                ZSYS_ERROR("Could not set all PORT0 bits to LOW: %s [%d]", strerror(ret), ret);
            }
        }
    }
    // Initialize String Hasher
    StringHasher hasher = StringHasher();
    // Set up cameras
    std::vector<uint32_t> camids;
    std::map<uint32_t, CameraInfo> caminfos;
    std::map<uint32_t, ImageCam *> imagecams;

    VmbError_t err = allied_init_api(cti_path);
    if (err != VmbErrorSuccess)
    {
        ZSYS_ERROR("Failed to initialize Allied Vision API: %s", allied_strerr(err));
        return 0;
    }

    VmbUint32_t count;
    VmbCameraInfo_t *vmbcaminfos;
    err = allied_list_cameras(&vmbcaminfos, &count);
    if (err != VmbErrorSuccess)
    {
        ZSYS_ERROR("Failed to list cameras: %s", allied_strerr(err));
        return 0;
    }
    if (count == 0)
    {
        ZSYS_ERROR("No cameras found.");
        return 0;
    }
    for (VmbUint32_t idx = 0; idx < count; idx++)
    {
        CameraInfo caminfo = CameraInfo(vmbcaminfos[idx]);
        uint32_t hash = hasher.get_hash(caminfo.idstr);
        camids.push_back(hash);
        caminfos.insert(std::pair<uint32_t, CameraInfo>(hash, caminfo));
        ZSYS_INFO("Camera %d: %s | %s", idx, caminfo.idstr.c_str(), caminfo.name.c_str());
        if (camera_id != "" && camera_id != caminfo.idstr) // if a camera id was specified and it doesn't match this camera
        {
            continue;
        }
        imagecams.insert(std::pair<uint32_t, ImageCam *>(hash, new ImageCam(caminfo, adio_dev)));
    }
    free(vmbcaminfos);
    // Capture time limit
    int64_t capture_timelim = 5000; // milliseconds
    // Setup ZMQ.
    zsock_t *pipe = zsock_new_rep(pipe_name.c_str());
    assert(pipe);
    zpoller_t *poller = zpoller_new(pipe, NULL);
    assert(poller);
    // Loop, waiting for ZMQ commands and performing them as necessary.
    while (!zsys_interrupted)
    {
        zsock_t *which = (zsock_t *)zpoller_wait(poller, 1000); // wait a second
        // here we have returned, either for a timeout or because we have a message
        int64_t currtime = zclock_mono();
        for (auto &image_cam_pair : imagecams)
        {
            if (image_cam_pair.second->running())
            {
                int64_t elapsed = image_cam_pair.second->capture_time(currtime);
                if (elapsed > capture_timelim)
                {
                    image_cam_pair.second->stop_capture();
                    ZSYS_INFO("Camera %s: Capture time limit reached (%ld ms), stopping capture.", image_cam_pair.second->get_info().idstr.c_str(), capture_timelim);
                }
                else
                {
                    ZSYS_INFO("Camera %s: Capture time remaining %ld ms, not stopping capture.", image_cam_pair.second->get_info().idstr.c_str(), capture_timelim - elapsed);
                }
            }
        }
        if (which == NULL)
        {
            if (zsys_interrupted)
            {
                ZSYS_INFO("Received SIGINT.");
            }
            continue;
        }
        char *message = zstr_recv(which);
        if (message == NULL)
        {
            char *ident = zsock_identity(which);
            ZSYS_INFO("Client disconnected: %s", ident);
            zstr_free(&ident);
            continue;
        }
        NetPacket packet = json::parse(message);
        zstr_free(&message);

        packet.retargs.clear();               // clear return arguments
        uint32_t chash = atol(packet.cam_id.c_str()); // get camera hash
        VmbError_t err = VmbErrorSuccess;     // set default error

        if (packet.cmd_type == "quit")
        {
            ZSYS_INFO("Received quit command.");
            zsys_interrupted = true;
        }
        else if (packet.cmd_type == "status") // should be sent every second by client if idle
        {
            // status
            std::vector<std::string> reply;
            if (packet.cam_id != "")
            {
                try
                {
                    ImageCam *image_cam = imagecams.at(chash);
                    double temp;
                    const char *tempsrc;
                    allied_get_temperature(image_cam->handle, &temp);
                    allied_get_temperature_src(image_cam->handle, &tempsrc);
                    reply.push_back(image_cam->running() ? "True" : "False");
                    reply.push_back(tempsrc);
                    reply.push_back(std::to_string(temp));
                    ZSYS_INFO("Camera %s: %s -> %.2f C", image_cam->get_info().idstr.c_str(), tempsrc, temp);
                }
                catch (const std::out_of_range &oor)
                {
                    err = VmbErrorNotFound;
                }
            }
            else
            {
                for (auto &image_cam_pair : imagecams)
                {
                    double temp;
                    const char *tempsrc;
                    allied_get_temperature(image_cam_pair.second->handle, &temp);
                    allied_get_temperature_src(image_cam_pair.second->handle, &tempsrc);
                    reply.push_back(std::to_string(image_cam_pair.first));
                    reply.push_back(image_cam_pair.second->get_info().idstr);
                    reply.push_back(image_cam_pair.second->running() ? "True" : "False");
                    reply.push_back(tempsrc);
                    reply.push_back(std::to_string(temp));
                    ZSYS_INFO("Camera %s: %s -> %.2f C", image_cam_pair.second->get_info().idstr.c_str(), tempsrc, temp);
                }
            }
            packet.retargs = reply;
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
            for (auto &image_cam_pair : imagecams)
            {
                err = image_cam_pair.second->start_capture();
                ZSYS_INFO("start_capture_all (%s): %s", image_cam_pair.second->get_info().idstr.c_str(), allied_strerr(err));
                if (err != VmbErrorSuccess)
                {
                    break;
                }
            }
        }
        else if (packet.cmd_type == "stop_capture_all")
        {
            err = VmbErrorSuccess;
            for (auto &image_cam_pair : imagecams)
            {
                err = image_cam_pair.second->stop_capture();
                ZSYS_INFO("stop_capture_all (%s): %s", image_cam_pair.second->get_info().idstr.c_str(), allied_strerr(err));
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
                ImageCam *image_cam = imagecams.at(chash);
                err = image_cam->start_capture(); // do this for specific camera id
                ZSYS_INFO("start_capture (%s): %s", image_cam->get_info().idstr.c_str(), allied_strerr(err));
            }
            catch (const std::out_of_range &oor)
            {
                err = VmbErrorNotFound;
                ZSYS_INFO("start_capture (%s): %s", std::to_string(chash), allied_strerr(err));
            }
        }
        else if (packet.cmd_type == "stop_capture")
        {
            try
            {
                ImageCam *image_cam = imagecams.at(chash);
                err = image_cam->stop_capture(); // do this for specific camera id
                ZSYS_INFO("stop_capture (%s): %s", image_cam->get_info().idstr.c_str(), allied_strerr(err));
            }
            catch (const std::out_of_range &oor)
            {
                err = VmbErrorNotFound;
                ZSYS_INFO("stop_capture (%s): %s", std::to_string(chash), allied_strerr(err));
            }
        }
        else if (packet.cmd_type == "get")
        {
            try
            {
                ImageCam *image_cam = imagecams.at(chash);
                std::vector<std::string> reply;
                switch (packet.command)
                {
                    GET_CASE_STR(image_format)
                    GET_CASE_STR(sensor_bit_depth)
                    GET_CASE_STR(trigline)
                    GET_CASE_STR(trigline_mode)
                    GET_CASE_STR(trigline_src)
                    GET_CASE_DBL(exposure_us)
                    GET_CASE_DBL(acq_framerate)
                    GET_CASE_BOOL(acq_framerate_auto)
                    GET_CASE_INT(throughput_limit)
                    GET_CASE_LIST(trigline_src_list)
                    GET_CASE_LIST(triglines_list)
                    GET_CASE_LIST(image_format_list)
                    GET_CASE_LIST(sensor_bit_depth_list)
                case CommandNames::frame_size:
                {
                    uint32_t fsize = allied_get_frame_size(image_cam->handle);
                    ZSYS_INFO("get (%s): frame_size -> %d", image_cam->get_info().idstr.c_str(), fsize);
                    reply.push_back(std::to_string(fsize));
                    break;
                }
                case CommandNames::sensor_size:
                {
                    VmbInt64_t width = 0, height = 0;
                    err = allied_get_sensor_size(image_cam->handle, &width, &height);
                    ZSYS_INFO("get (%s): sensor_size -> %ld x %ld", image_cam->get_info().idstr.c_str(), width, height);
                    reply.push_back(std::to_string(width));
                    reply.push_back(std::to_string(height));
                    break;
                }
                case CommandNames::image_size:
                {
                    VmbInt64_t width = 0, height = 0;
                    err = allied_get_image_size(image_cam->handle, &width, &height);
                    ZSYS_INFO("get (%s): image_size -> %ld x %ld", image_cam->get_info().idstr.c_str(), width, height);
                    reply.push_back(std::to_string(width));
                    reply.push_back(std::to_string(height));
                    break;
                }
                case CommandNames::image_ofst:
                {
                    VmbInt64_t width = 0, height = 0;
                    err = allied_get_image_ofst(image_cam->handle, &width, &height);
                    ZSYS_INFO("get (%s): image_ofst -> %ld x %ld", image_cam->get_info().idstr.c_str(), width, height);
                    reply.push_back(std::to_string(width));
                    reply.push_back(std::to_string(height));
                    break;
                }
                case CommandNames::adio_bit:
                {
                    ZSYS_INFO("get (%s): adio_bit", image_cam->get_info().idstr.c_str());
                    reply.push_back(std::to_string(image_cam->adio_bit));
                    break;
                }
                case CommandNames::throughput_limit_range:
                {
                    VmbInt64_t vmin = 0, vmax = 0;
                    err = allied_get_throughput_limit_range(image_cam->handle, &vmin, &vmax, NULL);
                    ZSYS_INFO("get (%s): throughput_limit_range -> %ld, %ld", image_cam->get_info().idstr.c_str(), vmin, vmax);
                    reply.push_back(std::to_string(vmin));
                    reply.push_back(std::to_string(vmax));
                    break;
                }
                case CommandNames::camera_info:
                {
                    ZSYS_INFO("get (%s): camera_info", image_cam->get_info().idstr.c_str());
                    reply.push_back(std::to_string(image_cam->get_info()));
                }
                case CommandNames::capture_maxlen:
                {
                    ZSYS_INFO("get: capture_maxlen: %ld", capture_timelim);
                    reply.push_back(std::to_string(capture_timelim));
                    break;
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
                ZSYS_ERROR("No data to set.");
                err = VmbErrorNoData;
            }
            else
            {
                std::vector<std::string> reply;
                const char *argument = packet.arguments[0].c_str(); // this must exist at this point
                try
                {
                    ImageCam *image_cam = imagecams.at(chash);
                    switch (packet.command)
                    {
                        SET_CASE_STR(image_format)
                        SET_CASE_STR(sensor_bit_depth)
                        SET_CASE_STR(trigline)
                        SET_CASE_STR(trigline_mode)
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
                        ZSYS_INFO("set (%s): image_size -> %ld x %ld", image_cam->get_info().idstr.c_str(), arg1l, arg2l);
                        err = allied_set_image_size(image_cam->handle, arg1l, arg2l);
                        if (err != VmbErrorSuccess)
                        {
                            break;
                        }
                        err = allied_get_image_size(image_cam->handle, &arg1l, &arg2l);
                        ZSYS_INFO("set (%s): image_size = %ld x %ld", image_cam->get_info().idstr.c_str(), arg1l, arg2l);
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
                        ZSYS_INFO("set (%s): image_ofst -> %ld x %ld", image_cam->get_info().idstr.c_str(), arg1l, arg2l);
                        err = allied_set_image_ofst(image_cam->handle, arg1l, arg2l);
                        if (err != VmbErrorSuccess)
                        {
                            break;
                        }
                        err = allied_get_image_ofst(image_cam->handle, &arg1l, &arg2l);
                        ZSYS_INFO("set (%s): image_ofst = %ld x %ld", image_cam->get_info().idstr.c_str(), arg1l, arg2l);
                        reply.push_back(std::to_string(arg1l));
                        reply.push_back(std::to_string(arg2l));
                        break;
                    }
                    case CommandNames::adio_bit:
                    {
                        long arg1l = atol(argument);
                        image_cam->adio_bit = arg1l;
                        ZSYS_INFO("set (%s): adio_bit = %d", image_cam->get_info().idstr.c_str(), image_cam->adio_bit);
                        reply.push_back(std::to_string(arg1l));
                        break;
                    }
                    case CommandNames::capture_maxlen:
                    {
                        long arg1l = atol(argument);
                        if (arg1l < 1000)
                        {
                            ZSYS_WARNING("Capture time limit too low, setting to 1000 ms.");
                            arg1l = 1000;
                        }
                        capture_timelim = arg1l;
                        ZSYS_INFO("set: capture_maxlen = %ld", capture_timelim);
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
    zsys_shutdown();
    for (auto &image_cam_pair : imagecams)
    {
        delete image_cam_pair.second;
    }
    if (adio_dev != nullptr)
        CloseDIO_aDIO(adio_dev);

    return 0;
}