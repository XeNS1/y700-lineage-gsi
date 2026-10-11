// SPDX-License-Identifier: Apache-2.0
package com.android.settings.fuelgauge.y700;

import android.content.Context;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.RemoteException;
import android.os.ServiceManager;
import android.os.SystemProperties;
import android.os.UserHandle;
import androidx.annotation.Nullable;
import com.android.settings.R;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.lineageos.y700.BypassState;
import org.lineageos.y700.IY700Bypass;

/** One authoritative backend. No saved enabled boolean and no UI-thread Binder I/O. */
public final class Y700BypassClient {
    public interface Listener { void onState(@Nullable BypassState state); }
    private final Handler mMain=new Handler(Looper.getMainLooper());
    private final ExecutorService mWorker=Executors.newSingleThreadExecutor();
    private final Listener mListener;
    private boolean mListening;
    private boolean mClosed;
    private int mGeneration;
    private final Runnable mPoll=this::refresh;

    public Y700BypassClient(Listener listener) { mListener=listener; }
    public static boolean isTarget() {
        return UserHandle.myUserId()==0
                && "TB321FU".equals(SystemProperties.get("ro.product.vendor.device"))
                && "pineapple".equals(SystemProperties.get("ro.board.platform"))
                && "TB321FU_CN_OPEN_USER_Q00011.0_V_ZUI_17.0.10.138_ST_250626"
                   .equals(SystemProperties.get("ro.vendor.build.version.incremental"));
    }
    private static IY700Bypass service() throws RemoteException {
        IBinder binder=ServiceManager.checkService("y700_bypass");
        if (binder==null) throw new RemoteException("Backend unavailable");
        return IY700Bypass.Stub.asInterface(binder);
    }
    public void start() {
        if (mClosed || mListening) return;
        mListening=true; ++mGeneration; refresh();
    }
    public void stop() {
        mListening=false; ++mGeneration; mMain.removeCallbacks(mPoll);
    }
    public void close() { stop(); mClosed=true; mWorker.shutdownNow(); }
    public void refresh() {
        if (!mListening || mClosed) return;
        final int generation=mGeneration;
        mMain.removeCallbacks(mPoll);
        mWorker.execute(()-> {
            BypassState state=null;
            try { state=service().getState(); } catch (RemoteException|SecurityException ignored) { }
            final BypassState result=state;
            mMain.post(()-> {
                if (!mListening || mClosed || generation!=mGeneration) return;
                mListener.onState(result);
                mMain.postDelayed(mPoll,1000);
            });
        });
    }
    public void request(boolean enabled) { request(enabled,null); }
    public void request(boolean enabled,@Nullable Context tileContext) {
        if (mClosed) return;
        final int generation=mGeneration;
        mWorker.execute(()-> {
            BypassState state=null;
            try {
                IY700Bypass backend=service();
                backend.setEnabled(enabled); state=backend.getState();
                if (enabled && tileContext!=null && state.managed
                        && (state.phase==BypassState.STARTING || state.phase==BypassState.SETTLING
                            || state.phase==BypassState.ON)) {
                    Y700BypassTiles.ensureAdded(tileContext);
                }
            } catch (RemoteException|SecurityException ignored) { }
            final BypassState result=state;
            mMain.post(()-> {
                if (!mListening || mClosed || generation!=mGeneration) return;
                mListener.onState(result);
            });
        });
    }
    public static boolean selected(@Nullable BypassState s) {
        return s!=null && s.supported && s.managed && s.chargingEnabled==0;
    }
    public static boolean canStart(@Nullable BypassState s) {
        return s!=null && s.supported && !s.managed && s.chargingEnabled==1;
    }
    public static boolean canStop(@Nullable BypassState s) {
        return s!=null && s.supported && s.managed
                && s.phase!=BypassState.STARTING
                && s.phase!=BypassState.STOPPING && s.phase!=BypassState.FAULT;
    }
    public static int phaseText(@Nullable BypassState s) {
        if (s==null) return R.string.y700_bypass_unavailable;
        switch (s.phase) {
            case BypassState.OFF: return R.string.y700_bypass_off;
            case BypassState.STARTING: return R.string.y700_bypass_starting;
            case BypassState.SETTLING: return R.string.y700_bypass_settling;
            case BypassState.ON: return R.string.y700_bypass_on;
            case BypassState.STOPPING: return R.string.y700_bypass_stopping;
            case BypassState.FAULT: return R.string.y700_bypass_restore_failed;
            case BypassState.EXTERNAL: return R.string.y700_bypass_external;
            default: return R.string.y700_bypass_unsupported;
        }
    }
    public static int reasonText(int reason) {
        switch (reason) {
            case 1: return R.string.y700_bypass_unsupported;
            case 2: return R.string.y700_bypass_connect;
            case 3: return R.string.y700_bypass_need_charge;
            case 4: return R.string.y700_bypass_capacity;
            case 5: return R.string.y700_bypass_temperature;
            case 6: case 7: return R.string.y700_bypass_write_failed;
            case 8: return R.string.y700_bypass_telemetry;
            case 9: return R.string.y700_bypass_not_settled;
            case 10: return R.string.y700_bypass_discharge;
            case 11: return R.string.y700_bypass_charge_continues;
            case 12: return R.string.y700_bypass_external;
            case 13: return R.string.y700_bypass_restore_failed;
            default: return R.string.y700_bypass_description;
        }
    }
    public static CharSequence summary(Context context,@Nullable BypassState state) {
        if (state==null || !state.supported) return context.getText(phaseText(state));
        int detail=state.reason!=0 ? reasonText(state.reason) : R.string.y700_bypass_description;
        if (state.managed && state.phase!=BypassState.FAULT) return context.getText(phaseText(state));
        return context.getText(detail);
    }
}
