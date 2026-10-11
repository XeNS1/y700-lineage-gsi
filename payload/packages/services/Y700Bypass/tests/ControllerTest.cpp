// SPDX-License-Identifier: Apache-2.0
#include "Controller.h"
#include <cstdlib>
#include <functional>
#include <iostream>
#include <map>
#include <string>
#include <vector>
using namespace y700;
static const char* currentTest="initialization";
static void check(bool value,const char* message) {
    if (!value) {
        std::cerr<<"FAIL "<<currentTest<<": "<<message<<'\n';
        std::exit(EXIT_FAILURE);
    }
}
struct FakeOutput: Output {
    Frame frame;
    int64_t now=0, delayDisable=0, delayRestore=0;
    bool ignoreDisable=false, ignoreRestore=false, failDisable=false;
    std::vector<bool> writes;
    std::map<int64_t,bool> pending;
    FakeOutput() {
        frame.charging=1; frame.online=1; frame.suspended=0;
        frame.capacity=52; frame.temp=340; frame.current=-441000;
        frame.fg1=220000; frame.fg2=220000;
        frame.numbersValid=true; frame.fgValid=true; frame.isCharging=true;
    }
    void apply(bool allowed) {
        frame.charging=allowed ? 1 : 0; frame.current=allowed ? -441000 : 0;
        frame.fg1=allowed ? 220000 : 0; frame.fg2=frame.fg1; frame.isCharging=allowed;
    }
    bool writeCharging(bool allowed) override {
        writes.push_back(allowed);
        if (!allowed && failDisable) return false;
        if ((!allowed && ignoreDisable) || (allowed && ignoreRestore)) return true;
        const int64_t delay=allowed ? delayRestore : delayDisable;
        if (delay) pending[now+delay]=allowed; else apply(allowed);
        return true;
    }
    void time(int64_t stamp) {
        now=stamp;
        while (!pending.empty() && pending.begin()->first<=now) {
            apply(pending.begin()->second); pending.erase(pending.begin());
        }
    }
    int disables() const { int n=0; for (bool value:writes) if (!value) ++n; return n; }
};
struct Fixture {
    FakeOutput io;
    Controller controller;
    Fixture(): controller(io) {
        controller.boot(true,io.frame,0); tick(0); tick(1000);
        check(controller.state().phase==OFF,"boot did not confirm ordinary charging");
    }
    void tick(int64_t now) { io.time(now); controller.tick(io.frame,now); }
    void request(bool enable,int64_t now) { io.time(now); controller.request(enable,io.frame,now); }
    void on() {
        request(true,2000); tick(2000); tick(5000); tick(8000);
        check(controller.state().active,"three zero samples should qualify active mode");
    }
    void off(int64_t now) {
        request(false,now); tick(now); tick(now+1000);
        check(controller.state().phase==OFF && io.frame.charging==1,"confirmed restore missing");
    }
};

int main() {
    const std::vector<std::pair<const char*,std::function<void()>>> tests={
      {"default-off-and-normal-toggle",[] {
        Fixture f; check(f.io.disables()==0,"boot disabled charging"); f.on();
        f.off(10000); check(f.io.disables()==1,"disable was reasserted");
      }},
      {"delayed-readback-in-both-directions",[] {
        Fixture f; f.io.delayDisable=2000; f.io.delayRestore=2000;
        f.request(true,2000); f.tick(2000);
        check(f.controller.state().phase==STARTING && !f.controller.state().active,"cached 1 shown active");
        f.tick(4000); f.tick(7000); f.tick(10000); check(f.controller.state().active,"delayed 0 rejected");
        f.request(false,11000); f.tick(11000); check(!f.controller.state().active,"tile stayed active after stop");
        f.tick(13000); f.tick(14000); check(f.controller.state().phase==OFF,"delayed 1 rejected");
        check(f.io.disables()==1,"multiple disable writes");
      }},
      {"twenty-five-second-transient",[] {
        Fixture f; f.request(true,2000);
        f.io.frame.current=324000; f.io.frame.fg1=-324000; f.io.frame.fg2=-324000;
        for (int64_t t=2000;t<27000;t+=1000) f.tick(t);
        check(!f.controller.state().active && f.controller.state().phase==SETTLING,"transition falsely qualified");
        f.io.frame.current=0; f.io.frame.fg1=0; f.io.frame.fg2=0;
        f.tick(29000); f.tick(32000); f.tick(35000);
        check(f.controller.state().active,"known load transition rejected"); f.off(36000);
      }},
      {"unplug-and-replug",[] {
        Fixture f; f.on(); f.io.frame.online=0; f.io.frame.charging=1; f.tick(9000);
        check(!f.controller.state().active,"unplugged tile stayed active"); f.tick(10000); f.tick(11000);
        check(f.controller.state().phase==OFF,"unplug did not restore");
        f.io.frame.online=1; f.tick(12000);
        check(!f.controller.state().active && f.io.disables()==1,"replug auto-enabled bypass");
      }},
      {"external-override",[] {
        Fixture f; f.on(); f.io.frame.charging=1; f.tick(9000); f.tick(10000); f.tick(11000);
        check(f.controller.state().reason==OVERRIDE && !f.controller.state().active,"override not stopped");
        check(f.io.disables()==1,"override fought by another disable");
      }},
      {"temperature-guard",[] {
        Fixture f; f.on(); f.io.frame.temp=450; f.tick(9000); f.tick(10000); f.tick(11000);
        check(f.controller.state().reason==TEMPERATURE && !f.controller.state().active,"thermal stop failed");
      }},
      {"low-battery-while-active",[] {
        Fixture f; f.on(); f.io.frame.capacity=19; f.tick(9000); f.tick(10000); f.tick(11000);
        check(f.controller.state().reason==CAPACITY && !f.controller.state().active,"capacity stop failed");
      }},
      {"unreadable-telemetry",[] {
        Fixture f; f.on(); f.io.frame.numbersValid=false; f.tick(9000); f.tick(10000); f.tick(11000);
        check(f.controller.state().reason==TELEMETRY && !f.controller.state().active,"invalid telemetry accepted");
      }},
      {"missing-fuel-gauge-rejected-before-disable",[] {
        Fixture f; f.io.frame.fgValid=false; f.request(true,2000);
        check(f.io.disables()==0 && f.controller.state().reason==TELEMETRY,
              "missing fuel gauge allowed a disable request");
      }},
      {"fuel-gauge-loss-removes-active-state",[] {
        Fixture f; f.on(); f.io.frame.fgValid=false; f.tick(9000);
        check(!f.controller.state().active && f.controller.state().phase==STOPPING
              && f.controller.state().reason==TELEMETRY,
              "lost fuel gauge left active tile state");
        f.tick(10000); f.tick(11000);
        check(f.controller.state().phase==OFF && f.io.frame.charging==1,
              "lost fuel gauge did not restore ordinary charging");
      }},
      {"ignored-disable",[] {
        Fixture f; f.io.ignoreDisable=true; f.request(true,2000); f.tick(8000); f.tick(9000); f.tick(10000);
        check(f.controller.state().reason==IGNORED && f.controller.state().phase==OFF,"ignored write not rejected");
        check(f.io.disables()==1,"ignored write repeated");
      }},
      {"disable-write-error",[] {
        Fixture f; f.io.failDisable=true; f.request(true,2000); f.tick(2000); f.tick(3000);
        check(f.controller.state().reason==WRITE && f.controller.state().phase==OFF,"write error not restored");
      }},
      {"settling-timeout-with-missing-fuel-gauge",[] {
        Fixture f; f.request(true,2000); f.io.frame.fgValid=false;
        for (int64_t t=2000;t<=50000;t+=1000) f.tick(t);
        check(f.controller.state().reason==SETTLE && f.controller.state().phase==OFF,"missing FG claimed active");
      }},
      {"sustained-discharge",[] {
        Fixture f; f.on(); f.io.frame.current=400000;
        for (int64_t t=37000;t<=48000;t+=1000) f.tick(t);
        check(f.controller.state().reason==DISCHARGING && f.controller.state().phase==OFF,"sustained discharge accepted");
      }},
      {"continued-charge",[] {
        Fixture f; f.on(); f.io.frame.current=-400000;
        for (int64_t t=37000;t<=48000;t+=1000) f.tick(t);
        check(f.controller.state().reason==CHARGING && f.controller.state().phase==OFF,"continued charging accepted");
      }},
      {"single-current-spike",[] {
        Fixture f; f.on(); f.io.frame.current=324000; f.tick(37000);
        f.io.frame.current=0; f.tick(40000); f.tick(43000);
        check(f.controller.state().active,"single spike stopped qualified mode"); f.off(44000);
      }},
      {"restore-failure-and-later-recovery",[] {
        Fixture f; f.on(); f.io.ignoreRestore=true; f.request(false,9000);
        for (int64_t t=9000;t<=29000;t+=1000) f.tick(t);
        check(f.controller.state().phase==FAULT && f.controller.state().managed && !f.controller.state().active,
              "restore failure claimed off/success");
        f.io.ignoreRestore=false; f.tick(59000); f.tick(60000); f.tick(61000);
        check(f.controller.state().phase==OFF && f.io.frame.charging==1,"retry recovery failed");
      }},
      {"daemon-restart-does-not-persist-on",[] {
        Fixture f; f.on(); Controller restarted(f.io);
        f.io.time(9000); restarted.boot(true,f.io.frame,9000);
        restarted.tick(f.io.frame,9000); restarted.tick(f.io.frame,10000);
        check(restarted.state().phase==OFF && f.io.frame.charging==1,"mode persisted across restart");
        check(f.io.disables()==1,"restart issued another disable");
      }},
      {"unsupported-profile-never-writes",[] {
        FakeOutput io; Controller c(io); c.boot(false,io.frame,0);
        c.request(true,io.frame,1); c.request(false,io.frame,2);
        check(io.writes.empty() && c.state().phase==UNSUPPORTED,"wrong device written");
      }},
      {"preflight-rejects-low-full-hot-offline",[] {
        for (int caseNo=0;caseNo<4;++caseNo) {
            Fixture f;
            if (caseNo==0) f.io.frame.capacity=19;
            if (caseNo==1) f.io.frame.capacity=100;
            if (caseNo==2) f.io.frame.temp=450;
            if (caseNo==3) f.io.frame.online=0;
            f.request(true,2000); check(f.io.disables()==0,"preflight disabled charging");
        }
      }},
      {"duplicate-request-never-reasserts-zero",[] {
        Fixture f; f.on(); f.request(true,9000); f.request(true,10000);
        check(f.io.disables()==1,"duplicate enable wrote zero again"); f.off(11000);
      }},
      {"watchdog-lease-deadline-and-corruption",[] {
        WatchdogLease w; check(!w.expired(99999),"inactive watchdog acted");
        w.observe(1000,123,1,1000); check(!w.expired(18999),"watchdog expired early");
        w.observe(999999,123,1,2000); w.observe(2000,0,1,2000);
        check(w.expired(19000) && w.pid()==123,"invalid heartbeat hid lost lease");
        w.observe(20000,124,0,20000); check(!w.expired(99000),"idle heartbeat restored external controller");
      }},
    };
    for (const auto& test:tests) {
        currentTest=test.first;
        test.second();
        std::cout<<"PASS "<<test.first<<'\n';
    }
    std::cout<<tests.size()<<" controller/watchdog cases passed\n";
    return 0;
}
