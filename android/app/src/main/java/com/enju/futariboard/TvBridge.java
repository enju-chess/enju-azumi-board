package com.enju.futariboard;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.webkit.JavascriptInterface;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Webページから呼び出す橋渡し。
 * ソニーの番組表アプリの呼び出し方は公開されていないので、
 * 初回だけ「どのアプリを開くか」を一覧から選んでもらい、以後はそれを開く。
 */
public class TvBridge {
    private static final String PREF = "board";
    private static final String KEY_GUIDE = "guide_pkg";
    private final Activity activity;

    TvBridge(Activity activity) { this.activity = activity; }

    @JavascriptInterface
    public void openGuide() {
        activity.runOnUiThread(() -> {
            String pkg = prefs().getString(KEY_GUIDE, null);
            if (pkg != null && launch(pkg)) return;
            prefs().edit().remove(KEY_GUIDE).apply();
            showPicker();
        });
    }

    @JavascriptInterface
    public void chooseGuide() {
        activity.runOnUiThread(this::showPicker);
    }

    private SharedPreferences prefs() {
        return activity.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    private boolean launch(String pkg) {
        PackageManager pm = activity.getPackageManager();
        Intent i = pm.getLeanbackLaunchIntentForPackage(pkg);
        if (i == null) i = pm.getLaunchIntentForPackage(pkg);
        if (i == null) return false;
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try { activity.startActivity(i); return true; } catch (Exception e) { return false; }
    }

    private void showPicker() {
        PackageManager pm = activity.getPackageManager();
        Map<String, String> apps = new LinkedHashMap<>();
        for (String cat : new String[]{Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER}) {
            Intent q = new Intent(Intent.ACTION_MAIN).addCategory(cat);
            for (ResolveInfo r : pm.queryIntentActivities(q, 0)) {
                String p = r.activityInfo.packageName;
                if (p.equals(activity.getPackageName())) continue;
                String label = String.valueOf(r.loadLabel(pm));
                // テレビ・番組表らしいものを先頭に
                apps.putIfAbsent(p, label);
            }
        }
        List<String[]> list = new ArrayList<>();
        for (Map.Entry<String, String> e : apps.entrySet()) list.add(new String[]{e.getKey(), e.getValue()});
        Collections.sort(list, (a, b) -> Integer.compare(score(b), score(a)) != 0
                ? Integer.compare(score(b), score(a)) : a[1].compareTo(b[1]));

        String[] labels = new String[list.size()];
        for (int i = 0; i < list.size(); i++) labels[i] = list.get(i)[1];

        new AlertDialog.Builder(activity)
                .setTitle("番組表を開くアプリを選んでください（次回からはこのアプリが開きます）")
                .setItems(labels, (d, which) -> {
                    String pkg = list.get(which)[0];
                    prefs().edit().putString(KEY_GUIDE, pkg).apply();
                    if (!launch(pkg)) Toast.makeText(activity, "開けませんでした", Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton("やめる", null)
                .show();
    }

    private static int score(String[] app) {
        String p = app[0].toLowerCase();
        String l = app[1];
        int s = 0;
        if (l.contains("番組") || l.contains("ガイド") || p.contains("guide") || p.contains("epg")) s += 4;
        if (l.contains("テレビ") || l.contains("TV") || p.contains("dtv") || p.contains("tvx")) s += 2;
        if (p.contains("sony")) s += 1;
        return s;
    }
}
