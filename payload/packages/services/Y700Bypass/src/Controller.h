// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstdint>

namespace y700 {
enum Phase { UNSUPPORTED=0, OFF=1, STARTING=2, SETTLING=3, ON=4,
             STOPPING=5, FAULT=6, EXTERNAL=7 };
enum Reason { NONE=0, PROFILE=1, POWER=2, NEED_CHARGE=3, CAPACITY=4,
              TEMPERATURE=5, WRITE=6, IGNORED=7, TELEMETRY=8, SETTLE=9,
              DISCHARGING=10, CHARGING=11, OVERRIDE=12, RESTORE=13 };
struct Frame {
    int charging=-1, online=-1, suspended=-1, capacity=-1, temp=-1;
    int64_t current=0, fg1=0, fg2=0;
    bool numbersValid=false, fgValid=false, isCharging=false;
};
struct State {
    bool supported=false, managed=false, active=false;
    Phase phase=UNSUPPORTED;
    Reason reason=PROFILE;
    Frame frame;
};
class Output {
public:
    virtual ~Output()=default;
    virtual bool writeCharging(bool allowed)=0;
};
class Controller {
public:
    explicit Controller(Output& output): output_(output) {}
    void boot(bool supported, const Frame& frame, int64_t now);
    void request(bool enable, const Frame& frame, int64_t now);
    void tick(const Frame& frame, int64_t now);
    State state() const;
private:
    void stop(Reason reason, int64_t now);
    void restoreAttempt(int64_t now);
    void restored();
    Output& output_;
    State s_;
    int64_t started_=0, lastSample_=-3000, lastRestoreCheck_=-1000;
    int64_t restoreDeadline_=0, retryAt_=0;
    int restoreAttempts_=0, stableRestore_=0, zero_=0, discharge_=0, charge_=0;
};
class WatchdogLease {
public:
    void observe(int64_t stamp, int pid, int armed, int64_t now) {
        if (stamp<0 || stamp>now || pid<=0 || (armed!=0 && armed!=1)) return;
        stamp_=stamp; pid_=pid; armed_=armed==1;
    }
    bool expired(int64_t now) const { return armed_ && now-stamp_>=18000; }
    int pid() const { return pid_; }
private:
    int64_t stamp_=0;
    int pid_=0;
    bool armed_=false;
};
}
