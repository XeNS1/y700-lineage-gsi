// SPDX-License-Identifier: Apache-2.0
package com.android.settings.fuelgauge.y700;

import android.app.PendingIntent;
import android.content.Intent;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;
import androidx.annotation.Nullable;
import com.android.settings.R;
import org.lineageos.y700.BypassState;

public final class Y700BypassTile extends TileService {
    @Nullable private Y700BypassClient mClient;
    @Nullable private BypassState mState;
    @Override public void onCreate() {
        super.onCreate(); mClient=new Y700BypassClient(this::accept);
    }
    @Override public void onStartListening() {
        super.onStartListening();
        mState=null; accept(null); if (mClient!=null) mClient.start();
    }
    @Override public void onStopListening() { if (mClient!=null) mClient.stop(); super.onStopListening(); }
    @Override public void onDestroy() { if (mClient!=null) mClient.close(); super.onDestroy(); }
    private void accept(@Nullable BypassState state) {
        mState=state;
        Tile tile=getQsTile(); if (tile==null) return;
        tile.setLabel(getString(R.string.y700_bypass_tile_label));
        tile.setSubtitle(getString(Y700BypassClient.phaseText(state)));
        final boolean transition=state!=null
                && (state.phase==BypassState.STARTING || state.phase==BypassState.STOPPING
                    || state.phase==BypassState.FAULT || state.phase==BypassState.EXTERNAL);
        // Highlight only a qualified active mode confirmed by a fresh backend read.
        int status=state==null || !state.supported || transition ? Tile.STATE_UNAVAILABLE
                : state.active ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE;
        tile.setState(status);
        tile.setContentDescription(getString(R.string.y700_bypass_tile_label)+", "+tile.getSubtitle());
        tile.updateTile();
    }
    @Override public void onClick() {
        super.onClick();
        unlockAndRun(()-> {
            if (mClient!=null && Y700BypassClient.canStop(mState)) mClient.request(false);
            else if (mClient!=null && Y700BypassClient.canStart(mState)) mClient.request(true);
            else openBattery();
        });
    }
    private void openBattery() {
        Intent screen=new Intent("android.intent.action.POWER_USAGE_SUMMARY")
                .setPackage(getPackageName());
        PendingIntent intent=PendingIntent.getActivity(this,0,screen,
                PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        startActivityAndCollapse(intent);
    }
}
