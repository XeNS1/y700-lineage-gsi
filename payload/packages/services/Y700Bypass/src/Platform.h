// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "Controller.h"
#include <cstdint>
#include <string>

namespace y700 {
constexpr const char* CHARGE="/sys/class/power_supply/battery/charging_enable";
constexpr const char* REAL_CHARGE="/sys/devices/platform/soc/soc:qcom,pmic_glink/soc:qcom,pmic_glink:qcom,battery_charger/power_supply/battery/charging_enable";
constexpr const char* HEARTBEAT="/data/misc/y700-bypass/heartbeat";
int64_t uptimeMillis();
bool matchesProfile();
Frame readFrame();
bool publishHeartbeat(bool managed);
bool restoreCharging();
int runWatchdog();
class PlatformOutput final: public Output {
public:
    bool writeCharging(bool allowed) override;
};
}
