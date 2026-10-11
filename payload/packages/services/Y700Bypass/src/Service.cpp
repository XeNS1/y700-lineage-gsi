// SPDX-License-Identifier: Apache-2.0
#include "Platform.h"
#include <aidl/org/lineageos/y700/BnY700Bypass.h>
#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <android/log.h>
#include <chrono>
#include <csignal>
#include <cstring>
#include <mutex>
#include <thread>

namespace {
volatile sig_atomic_t stopRequested=0;
void stopSignal(int) { stopRequested=1; }
using aidl::org::lineageos::y700::BypassState;
using aidl::org::lineageos::y700::BnY700Bypass;
class Service final: public BnY700Bypass {
public:
    Service(): controller_(output_) {
        const bool supported=y700::matchesProfile();
        if (supported) y700::publishHeartbeat(true);
        controller_.boot(supported, y700::readFrame(), y700::uptimeMillis());
    }
    ndk::ScopedAStatus getState(BypassState* result) override {
        if (!authorized()) return ndk::ScopedAStatus::fromExceptionCode(EX_SECURITY);
        std::lock_guard<std::mutex> guard(mutex_);
        pollLocked();
        const auto state=controller_.state();
        result->supported=state.supported; result->managed=state.managed;
        result->active=state.active; result->phase=state.phase; result->reason=state.reason;
        result->chargingEnabled=state.frame.charging; result->online=state.frame.online;
        result->capacity=state.frame.capacity; result->temperature=state.frame.temp;
        result->currentMicroamps=state.frame.current; result->telemetryValid=state.frame.numbersValid;
        return ndk::ScopedAStatus::ok();
    }
    ndk::ScopedAStatus setEnabled(bool enabled) override {
        if (!authorized()) return ndk::ScopedAStatus::fromExceptionCode(EX_SECURITY);
        std::lock_guard<std::mutex> guard(mutex_);
        controller_.request(enabled, y700::readFrame(), y700::uptimeMillis());
        y700::publishHeartbeat(controller_.state().managed);
        return ndk::ScopedAStatus::ok();
    }
    void poll() { std::lock_guard<std::mutex> guard(mutex_); pollLocked(); }
private:
    static bool authorized() {
        const uid_t uid=AIBinder_getCallingUid();
        // Settings runs as android.uid.system. Secondary users and third-party
        // apps cannot enable the device-wide hardware mode.
        return uid==1000 || uid==0;
    }
    void pollLocked() {
        controller_.tick(y700::readFrame(), y700::uptimeMillis());
        if (controller_.state().supported)
            y700::publishHeartbeat(controller_.state().managed);
    }
    std::mutex mutex_;
    y700::PlatformOutput output_;
    y700::Controller controller_;
};
}
int main(int argc, char** argv) {
    if (argc==2 && std::strcmp(argv[1], "--watchdog")==0) return y700::runWatchdog();
    if (argc!=1) return 2;
    signal(SIGTERM, stopSignal); signal(SIGINT, stopSignal);
    ABinderProcess_setThreadPoolMaxThreadCount(2);
    auto service=ndk::SharedRefBase::make<Service>();
    if (AServiceManager_addService(service->asBinder().get(), "y700_bypass")!=STATUS_OK) return 2;
    ABinderProcess_startThreadPool();
    while (!stopRequested) {
        service->poll();
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    if (y700::matchesProfile() && !y700::restoreCharging()) return 5;
    return 0;
}
