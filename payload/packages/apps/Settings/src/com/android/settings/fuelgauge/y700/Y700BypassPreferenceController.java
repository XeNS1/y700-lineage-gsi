// SPDX-License-Identifier: Apache-2.0
package com.android.settings.fuelgauge.y700;

import android.content.Context;
import androidx.annotation.Nullable;
import androidx.preference.Preference;
import androidx.preference.PreferenceScreen;
import com.android.settings.R;
import com.android.settings.core.TogglePreferenceController;
import com.android.settingslib.core.lifecycle.LifecycleObserver;
import com.android.settingslib.core.lifecycle.events.OnStart;
import com.android.settingslib.core.lifecycle.events.OnStop;
import com.android.settingslib.core.lifecycle.events.OnDestroy;
import org.lineageos.y700.BypassState;

public final class Y700BypassPreferenceController extends TogglePreferenceController
        implements LifecycleObserver, OnStart, OnStop, OnDestroy {
    private final Y700BypassClient mClient;
    @Nullable private BypassState mState;
    @Nullable private Preference mPreference;

    public Y700BypassPreferenceController(Context context,String key) {
        super(context,key); mClient=new Y700BypassClient(this::accept);
    }
    @Override public int getAvailabilityStatus() {
        return Y700BypassClient.isTarget() ? AVAILABLE : UNSUPPORTED_ON_DEVICE;
    }
    @Override public int getSliceHighlightMenuRes() { return R.string.menu_key_battery; }
    @Override public void displayPreference(PreferenceScreen screen) {
        super.displayPreference(screen);
        mPreference=screen.findPreference(getPreferenceKey());
        if (mPreference!=null) updateState(mPreference);
    }
    @Override public boolean isChecked() { return Y700BypassClient.selected(mState); }
    @Override public boolean setChecked(boolean enabled) {
        if (mPreference!=null) mPreference.setEnabled(false);
        mClient.request(enabled,mContext.getApplicationContext());
        // Do not optimistically save/toggle the switch: wait for the sysfs readback.
        return false;
    }
    @Override public void updateState(Preference preference) {
        super.updateState(preference);
        preference.setPersistent(false);
        preference.setSummary(Y700BypassClient.summary(mContext,mState));
        preference.setEnabled(Y700BypassClient.canStart(mState)||Y700BypassClient.canStop(mState));
    }
    @Override public void onStart() { mClient.start(); }
    @Override public void onStop() { mClient.stop(); }
    @Override public void onDestroy() { mClient.close(); }
    private void accept(@Nullable BypassState state) {
        mState=state;
        if (mPreference!=null) updateState(mPreference);
    }
}
