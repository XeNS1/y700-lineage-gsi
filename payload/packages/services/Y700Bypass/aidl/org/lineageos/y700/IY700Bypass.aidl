// SPDX-License-Identifier: Apache-2.0
package org.lineageos.y700;
import org.lineageos.y700.BypassState;
interface IY700Bypass {
    BypassState getState();
    void setEnabled(boolean enabled);
}
