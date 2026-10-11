// SPDX-License-Identifier: Apache-2.0
package com.android.settings.fuelgauge.y700;

import android.content.ComponentName;
import android.content.Context;
import android.os.RemoteException;
import android.os.ServiceManager;
import android.provider.Settings;
import android.util.Log;
import com.android.internal.statusbar.IStatusBarService;

/** Called after an explicit, accepted enable request, even if Battery UI closes. */
final class Y700BypassTiles {
    private Y700BypassTiles() { }
    static void ensureAdded(Context context) {
        ComponentName component=new ComponentName(context,Y700BypassTile.class);
        String spec="custom("+component.flattenToShortString()+")";
        String tiles=Settings.Secure.getString(context.getContentResolver(),"sysui_qs_tiles");
        if (tiles!=null) {
            for (String tile:tiles.split(",")) if (spec.equals(tile.trim())) return;
        }
        try {
            IStatusBarService bar=IStatusBarService.Stub.asInterface(
                    ServiceManager.checkService(Context.STATUS_BAR_SERVICE));
            if (bar!=null) bar.addTile(component);
        } catch (RemoteException|SecurityException error) {
            Log.w("Y700Bypass","Could not add Quick Settings tile",error);
        }
    }
}
