// SPDX-License-Identifier: Apache-2.0
package org.lineageos.y700;
parcelable BypassState {
    const int UNSUPPORTED=0;
    const int OFF=1;
    const int STARTING=2;
    const int SETTLING=3;
    const int ON=4;
    const int STOPPING=5;
    const int FAULT=6;
    const int EXTERNAL=7;
    boolean supported;
    boolean managed;
    boolean active;
    int phase=0;
    int reason=1;
    int chargingEnabled=-1;
    int online=-1;
    int capacity=-1;
    int temperature=-1;
    long currentMicroamps=0;
    boolean telemetryValid;
}
