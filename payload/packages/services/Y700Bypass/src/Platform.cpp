// SPDX-License-Identifier: Apache-2.0
#include "Platform.h"
#include <android-base/properties.h>
#include <android-base/file.h>
#include <android-base/strings.h>
#include <android/log.h>
#include <selinux/selinux.h>
#include <charconv>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <fcntl.h>
#include <sstream>
#include <sys/utsname.h>
#include <thread>
#include <time.h>
#include <unistd.h>

namespace y700 {
int64_t uptimeMillis() {
    timespec ts{};
    clock_gettime(CLOCK_BOOTTIME, &ts);
    return static_cast<int64_t>(ts.tv_sec)*1000+ts.tv_nsec/1000000;
}
static bool number(const std::string& path, int64_t* value) {
    std::string raw;
    if (!android::base::ReadFileToString(path, &raw)) return false;
    raw=android::base::Trim(raw);
    auto parsed=std::from_chars(raw.data(), raw.data()+raw.size(), *value);
    return !raw.empty() && parsed.ec==std::errc{} && parsed.ptr==raw.data()+raw.size();
}
static int smallNumber(const char* path) {
    int64_t value=0;
    if (!number(path, &value) || value<0 || value>1000000) return -1;
    return static_cast<int>(value);
}
bool matchesProfile() {
    using android::base::GetProperty;
    utsname kernel{};
    char resolved[4096];
    return getuid()==0 && security_getenforce()==1
        && GetProperty("ro.product.vendor.device", "")=="TB321FU"
        && GetProperty("ro.board.platform", "")=="pineapple"
        && GetProperty("ro.vendor.build.version.incremental", "")==
           "TB321FU_CN_OPEN_USER_Q00011.0_V_ZUI_17.0.10.138_ST_250626"
        && GetProperty("ro.build.version.sdk", "")=="36"
        && GetProperty("ro.lineage.version", "").rfind("23.2-", 0)==0
        && uname(&kernel)==0
        && std::string(kernel.release)=="6.1.112-android14-11-gd03cb1d7abcd-ab12592111"
        && realpath(CHARGE, resolved)!=nullptr && std::string(resolved)==REAL_CHARGE;
}
Frame readFrame() {
    Frame value;
    value.charging=smallNumber(CHARGE);
    value.online=smallNumber("/sys/class/power_supply/usb/online");
    value.suspended=smallNumber("/sys/class/power_supply/usb/input_suspend");
    value.capacity=smallNumber("/sys/class/power_supply/battery/capacity");
    value.temp=smallNumber("/sys/class/power_supply/battery/temp");
    value.numbersValid=number("/sys/class/power_supply/battery/current_now", &value.current)
                       && value.capacity>=0 && value.capacity<=100 && value.temp>=0;
    value.fgValid=number("/sys/class/qcom-battery/fg1_current", &value.fg1)
                  && number("/sys/class/qcom-battery/fg2_current", &value.fg2);
    std::string status;
    if (android::base::ReadFileToString("/sys/class/power_supply/battery/status", &status)) {
        status=android::base::Trim(status);
        value.isCharging=status=="Charging";
        value.isFull=status=="Full";
    }
    return value;
}
bool publishHeartbeat(bool managed) {
    const std::string temporary=std::string(HEARTBEAT)+".new";
    const std::string payload=std::to_string(uptimeMillis())+" "+std::to_string(getpid())
                              +" "+(managed ? "1\n" : "0\n");
    return android::base::WriteStringToFile(payload, temporary, 0600, 0, 0)
           && rename(temporary.c_str(), HEARTBEAT)==0;
}
bool PlatformOutput::writeCharging(bool allowed) {
    // Publish the active lease before the disable syscall, including write failures.
    if (!allowed && !publishHeartbeat(true)) return false;
    const char* data=allowed ? "1\n" : "0\n";
    const bool result=android::base::WriteStringToFile(data, REAL_CHARGE);
    if (!result) __android_log_print(ANDROID_LOG_ERROR, "Y700Bypass", "charging_enable write failed");
    return result;
}
bool restoreCharging() {
    PlatformOutput writer;
    for (int attempt=0; attempt<3; ++attempt) {
        writer.writeCharging(true);
        int stable=0;
        for (int check=0; check<6; ++check) {
            stable=smallNumber(CHARGE)==1 ? stable+1 : 0;
            if (stable>=2) return true;
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    }
    return false;
}
int runWatchdog() {
    if (!matchesProfile()) return 2;
    WatchdogLease lease;
    while (true) {
        std::string raw;
        if (android::base::ReadFileToString(HEARTBEAT, &raw)) {
            std::istringstream stream(raw);
            int64_t stamp; int pid; int armed;
            if (stream>>stamp>>pid>>armed) lease.observe(stamp,pid,armed,uptimeMillis());
        }
        if (lease.expired(uptimeMillis())) {
            // SELinux permits signalling only this daemon's own domain. Killing a
            // stuck worker also makes init execute its onrestart restore command.
            if (lease.pid()>1 && lease.pid()!=getpid()) kill(lease.pid(), SIGKILL);
            if (!restoreCharging())
                __android_log_print(ANDROID_LOG_ERROR, "Y700Bypass", "watchdog could not confirm charging restore");
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
}
}
