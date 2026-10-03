package com.enju.futariboard;

import android.annotation.SuppressLint;
import android.graphics.Color;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** 一覧画面とスクリーンセーバーで共通のWebView設定 */
final class Board {
    static final String BASE = "https://enju-chess.github.io/enju-azumi-board/web/";

    private Board() {}

    @SuppressLint("SetJavaScriptEnabled")
    static void setup(WebView web) {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        // 毎回最新のデータを読む
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        web.setBackgroundColor(Color.parseColor("#14161B"));
        web.setWebViewClient(new WebViewClient());
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
    }
}
