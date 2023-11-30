#pragma once

#include "json.hpp"
#include "alliedcam.h"

enum CommandNames
{
    image_format = 100,           // string
    sensor_bit_depth = 101,       // string
    trigline = 102,               // string
    trigline_src = 103,           // string
    exposure_us = 104,            // double
    acq_framerate = 105,          // double
    acq_framerate_auto = 106,     // bool
    frame_size = 107,             // int
    image_size = 200,             // special, two arguments, ints
    image_ofst = 201,             // special, two arguments, ints
    sensor_size = 202,            // special, two arguments, ints
    throughput_limit = 300,       // int
    throughput_limit_range = 301, // special
    camera_info = 302,            // special
    adio_bit = 10,                // special
};

using json = nlohmann::json;

class NetPacket
{
public:
    std::string cmd_type = "None";
    std::string cam_id = "None";
    int command = 0;
    std::vector<std::string> arguments;
    int retcode = VmbErrorSuccess;
    std::vector<std::string> retargs;

    NLOHMANN_DEFINE_TYPE_INTRUSIVE(NetPacket, cmd_type, cam_id, command, arguments, retcode, retargs)
};

#define SET_CASE_STR(NAME)                                    \
    case CommandNames::NAME:                                  \
    {                                                         \
        err = allied_set_##NAME(image_cam.handle, argument);  \
        err = allied_get_##NAME(image_cam.handle, &argument); \
        reply.push_back(argument);                            \
        break;                                                \
    }

#define SET_CASE_INT(NAME)                               \
    case CommandNames::NAME:                             \
    {                                                    \
        VmbInt64_t arg = atol(argument);                 \
        err = allied_set_##NAME(image_cam.handle, arg);  \
        err = allied_get_##NAME(image_cam.handle, &arg); \
        reply.push_back(std::to_string(arg));            \
        break;                                           \
    }

#define SET_CASE_DBL(NAME)                               \
    case CommandNames::NAME:                             \
    {                                                    \
        double arg = atof(argument);                     \
        err = allied_set_##NAME(image_cam.handle, arg);  \
        err = allied_get_##NAME(image_cam.handle, &arg); \
        reply.push_back(string_format("%.6f", arg));     \
        break;                                           \
    }

#define SET_CASE_BOOL(NAME)                              \
    case CommandNames::NAME:                             \
    {                                                    \
        char *narg = strdup(argument);                   \
        for (int i = 0; narg[i]; i++)                    \
        {                                                \
            narg[i] = tolower(narg[i]);                  \
        }                                                \
        bool arg = streq(narg, "true");                  \
        err = allied_set_##NAME(image_cam.handle, arg);  \
        err = allied_get_##NAME(image_cam.handle, &arg); \
        reply.push_back(arg ? "True" : "False");         \
        break;                                           \
    }

#define GET_CASE_STR(NAME)                                               \
    case CommandNames::NAME:                                             \
    {                                                                    \
        char *garg;                                                      \
        err = allied_get_##NAME(image_cam.handle, (const char **)&garg); \
        reply.push_back(garg);                                           \
        break;                                                           \
    }

#define GET_CASE_DBL(NAME)                                \
    case CommandNames::NAME:                              \
    {                                                     \
        double garg;                                      \
        err = allied_get_##NAME(image_cam.handle, &garg); \
        reply.push_back(string_format("%.6f", garg));     \
        break;                                            \
    }

#define GET_CASE_INT(NAME)                                \
    case CommandNames::NAME:                              \
    {                                                     \
        VmbInt64_t garg;                                  \
        err = allied_get_##NAME(image_cam.handle, &garg); \
        reply.push_back(std::to_string(garg));            \
        break;                                            \
    }

#define GET_CASE_BOOL(NAME)                                      \
    case CommandNames::NAME:                                     \
    {                                                            \
        VmbBool_t garg;                                          \
        err = allied_get_##NAME(image_cam.handle, &garg);        \
        reply.push_back(garg == VmbBoolTrue ? "True" : "False"); \
        break;                                                   \
    }
