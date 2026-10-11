// SPDX-License-Identifier: Apache-2.0
#include "Controller.h"

namespace y700 {
static bool nearZero(int64_t n) { return n>=-50000 && n<=50000; }

void Controller::boot(bool supported, const Frame& frame, int64_t now) {
    s_=State{}; s_.supported=supported; s_.frame=frame;
    if (!supported) return;
    // Never restore a saved experimental mode. Confirm ordinary charging on boot.
    s_.managed=true;
    stop(NONE, now);
}
void Controller::request(bool enable, const Frame& frame, int64_t now) {
    tick(frame, now);
    if (!s_.supported) return;
    if (!enable) {
        if (s_.managed && s_.phase!=STOPPING) stop(NONE, now);
        return;
    }
    if (s_.managed) return;
    s_.reason=NONE;
    if (frame.charging!=1) { s_.reason=OVERRIDE; return; }
    if (frame.online!=1 || frame.suspended!=0) { s_.reason=POWER; return; }
    if (!frame.numbersValid || !frame.fgValid) { s_.reason=TELEMETRY; return; }
    // Full batteries can report Full/Not charging and near-zero current while
    // the connected charger powers the tablet. An incoming charge is not a
    // prerequisite in this case. Reject a discharge beyond telemetry noise.
    const bool chargingNow=frame.isCharging && frame.current<0;
    const bool fullOnExternalPower=(frame.isFull || frame.capacity==100)
                                   && frame.current<=50000;
    if (!chargingNow && !fullOnExternalPower) { s_.reason=NEED_CHARGE; return; }
    if (frame.capacity<20) { s_.reason=CAPACITY; return; }
    if (frame.temp>=450) { s_.reason=TEMPERATURE; return; }
    s_.managed=true; s_.phase=STARTING; s_.active=false;
    started_=now; lastSample_=now-3000;
    zero_=0; discharge_=0; charge_=0;
    // One disable write per explicit user request. Never reassert after an override.
    if (!output_.writeCharging(false)) stop(WRITE, now);
}
void Controller::stop(Reason reason, int64_t now) {
    s_.active=false; s_.phase=STOPPING; s_.reason=reason;
    restoreAttempts_=0; stableRestore_=0; lastRestoreCheck_=now-1000;
    restoreAttempt(now);
}
void Controller::restoreAttempt(int64_t now) {
    ++restoreAttempts_; stableRestore_=0;
    output_.writeCharging(true);
    restoreDeadline_=now+6000;
}
void Controller::restored() {
    s_.managed=false; s_.active=false; s_.phase=OFF;
    // Preserve why the mode was stopped, without claiming it is still enabled.
}
void Controller::tick(const Frame& frame, int64_t now) {
    s_.frame=frame;
    if (!s_.supported) return;
    if (s_.phase==STOPPING || s_.phase==FAULT) {
        if (now-lastRestoreCheck_>=1000) {
            lastRestoreCheck_=now;
            stableRestore_=frame.charging==1 ? stableRestore_+1 : 0;
            if (stableRestore_>=2) { restored(); return; }
        }
        if (s_.phase==FAULT) {
            if (now>=retryAt_) { stop(RESTORE, now); }
        } else if (now>=restoreDeadline_) {
            if (restoreAttempts_<3) restoreAttempt(now);
            else { s_.phase=FAULT; s_.reason=RESTORE; retryAt_=now+30000; }
        }
        return;
    }
    if (!s_.managed) {
        s_.phase=frame.charging==0 ? EXTERNAL : OFF;
        s_.active=false;
        if (s_.phase==EXTERNAL) s_.reason=OVERRIDE;
        if (s_.phase==OFF && s_.reason==POWER && frame.online==1) s_.reason=NONE;
        return;
    }
    if (frame.online!=1) { stop(POWER, now); return; }
    if (frame.suspended!=0 || !frame.numbersValid) { stop(TELEMETRY, now); return; }
    if (s_.phase==ON && !frame.fgValid) { stop(TELEMETRY, now); return; }
    if (frame.capacity<20) { stop(CAPACITY, now); return; }
    if (frame.temp>=450) { stop(TEMPERATURE, now); return; }
    if (s_.phase==STARTING) {
        if (frame.charging==0) s_.phase=SETTLING;
        else if (frame.charging!=1) { stop(TELEMETRY, now); return; }
        else if (now-started_>=6000) { stop(IGNORED, now); return; }
    } else if (frame.charging!=0) { stop(OVERRIDE, now); return; }
    if (s_.phase==STARTING || now-lastSample_<3000) return;
    lastSample_=now;
    const bool zero=frame.fgValid && nearZero(frame.current)
                    && nearZero(frame.fg1) && nearZero(frame.fg2);
    zero_=zero ? zero_+1 : 0;
    if (zero_>=3) { s_.phase=ON; s_.active=true; }
    if (s_.phase!=ON && now-started_>=45000) { stop(SETTLE, now); return; }
    if (now-started_>=35000) {
        discharge_=frame.current>250000 ? discharge_+1 : 0;
        charge_=frame.current< -250000 ? charge_+1 : 0;
        if (discharge_>=3) { stop(DISCHARGING, now); return; }
        if (charge_>=3) { stop(CHARGING, now); return; }
    }
}
State Controller::state() const {
    State value=s_;
    // Never use the user's requested boolean as the tile's active state.
    value.active=value.phase==ON && value.managed && value.frame.charging==0
                 && value.frame.online==1 && value.frame.suspended==0;
    return value;
}
}
