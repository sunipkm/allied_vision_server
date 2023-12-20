#pragma once

#include "json.hpp"
#include "alliedcam.h"

enum CommandNames
{
    image_format = 100,           // string
    sensor_bit_depth,             // string
    trigline,                     // string
    trigline_mode,                // string
    trigline_src,                 // string
    exposure_us,                  // double
    acq_framerate,                // double
    acq_framerate_auto,           // bool
    frame_size,                   // int
    image_size = 200,             // special, two arguments, ints
    image_ofst = 201,             // special, two arguments, ints
    sensor_size = 202,            // special, two arguments, ints
    throughput_limit = 300,       // int
    throughput_limit_range = 301, // special
    camera_info = 302,            // special
    trigline_mode_src_list = 303, // special
    adio_bit = 10,                // special
    capture_maxlen = 400,         // special, int, time in seconds
};

#define ZSYS_ERROR(fmt, ...)                              \
    {                                                     \
        zsys_error(RED_FG fmt TERMINATOR, ##__VA_ARGS__); \
    }

#define ZSYS_WARNING(fmt, ...)                                 \
    {                                                          \
        zsys_warning(YELLOW_BG fmt TERMINATOR, ##__VA_ARGS__); \
    }

#define ZSYS_INFO(fmt, ...)                               \
    {                                                     \
        zsys_info(CYAN_FG fmt TERMINATOR, ##__VA_ARGS__); \
    }

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

namespace std
{
    static inline std::string to_string(const NetPacket &p) noexcept
    {
        return json(p).dump();
    }
}

#define SET_CASE_STR(NAME)                                                                    \
    case CommandNames::NAME:                                                                  \
    {                                                                                         \
        err = allied_set_##NAME(image_cam.handle, argument);                                  \
        ZSYS_INFO("set (%s): %s -> %s", image_cam.get_info().idstr.c_str(), #NAME, argument); \
        err = allied_get_##NAME(image_cam.handle, &argument);                                 \
        ZSYS_INFO("set (%s): %s = %s", image_cam.get_info().idstr.c_str(), #NAME, argument);  \
        reply.push_back(argument);                                                            \
        break;                                                                                \
    }

#define SET_CASE_INT(NAME)                                                                \
    case CommandNames::NAME:                                                              \
    {                                                                                     \
        VmbInt64_t arg = atol(argument);                                                  \
        err = allied_set_##NAME(image_cam.handle, arg);                                   \
        ZSYS_INFO("set (%s): %s -> %ld", image_cam.get_info().idstr.c_str(), #NAME, arg); \
        err = allied_get_##NAME(image_cam.handle, &arg);                                  \
        ZSYS_INFO("set (%s): %s = %ld", image_cam.get_info().idstr.c_str(), #NAME, arg);  \
        reply.push_back(std::to_string(arg));                                             \
        break;                                                                            \
    }

#define SET_CASE_DBL(NAME)                                                               \
    case CommandNames::NAME:                                                             \
    {                                                                                    \
        double arg = atof(argument);                                                     \
        err = allied_set_##NAME(image_cam.handle, arg);                                  \
        ZSYS_INFO("set (%s): %s -> %f", image_cam.get_info().idstr.c_str(), #NAME, arg); \
        err = allied_get_##NAME(image_cam.handle, &arg);                                 \
        ZSYS_INFO("set (%s): %s = %f", image_cam.get_info().idstr.c_str(), #NAME, arg);  \
        reply.push_back(string_format("%.6f", arg));                                     \
        break;                                                                           \
    }

#define SET_CASE_BOOL(NAME)                                                              \
    case CommandNames::NAME:                                                             \
    {                                                                                    \
        char *narg = strdup(argument);                                                   \
        for (int i = 0; narg[i]; i++)                                                    \
        {                                                                                \
            narg[i] = tolower(narg[i]);                                                  \
        }                                                                                \
        bool arg = streq(narg, "true");                                                  \
        err = allied_set_##NAME(image_cam.handle, arg);                                  \
        ZSYS_INFO("set (%s): %s -> %d", image_cam.get_info().idstr.c_str(), #NAME, arg); \
        err = allied_get_##NAME(image_cam.handle, &arg);                                 \
        ZSYS_INFO("set (%s): %s = %d", image_cam.get_info().idstr.c_str(), #NAME, arg);  \
        reply.push_back(arg ? "True" : "False");                                         \
        break;                                                                           \
    }

#define GET_CASE_STR(NAME)                                                               \
    case CommandNames::NAME:                                                             \
    {                                                                                    \
        char *garg = (char *)"None";                                                     \
        err = allied_get_##NAME(image_cam.handle, (const char **)&garg);                 \
        ZSYS_INFO("get (%s): %s = %s", image_cam.get_info().idstr.c_str(), #NAME, garg); \
        reply.push_back(garg);                                                           \
        break;                                                                           \
    }

#define GET_CASE_DBL(NAME)                                                                 \
    case CommandNames::NAME:                                                               \
    {                                                                                      \
        double garg;                                                                       \
        err = allied_get_##NAME(image_cam.handle, &garg);                                  \
        ZSYS_INFO("get (%s): %s = %.6f", image_cam.get_info().idstr.c_str(), #NAME, garg); \
        reply.push_back(string_format("%.6f", garg));                                      \
        break;                                                                             \
    }

#define GET_CASE_INT(NAME)                                                                \
    case CommandNames::NAME:                                                              \
    {                                                                                     \
        VmbInt64_t garg;                                                                  \
        err = allied_get_##NAME(image_cam.handle, &garg);                                 \
        ZSYS_INFO("get (%s): %s = %ld", image_cam.get_info().idstr.c_str(), #NAME, garg); \
        reply.push_back(std::to_string(garg));                                            \
        break;                                                                            \
    }

#define GET_CASE_BOOL(NAME)                                                                   \
    case CommandNames::NAME:                                                                  \
    {                                                                                         \
        VmbBool_t garg;                                                                       \
        err = allied_get_##NAME(image_cam.handle, &garg);                                     \
        ZSYS_INFO("get (%s): %s = %d", image_cam.get_info().idstr.c_str(), #NAME, (int)garg); \
        reply.push_back(garg == VmbBoolTrue ? "True" : "False");                              \
        break;                                                                                \
    }
