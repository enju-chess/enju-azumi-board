package com.enju.futariboard;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.webkit.WebView;

/** 一覧画面：表示ページを全画面で開くだけ */
public class MainActivity extends Activity {
    private WebView web;
    private final Handler handler = new Handler(Looper.getMainLooper());
    // 開きっぱなしでも1時間ごとに最新データへ更新
    private final Runnable reload = new Runnable() {
        @Override public void run() {
            if (web != null) web.reload();
            handler.postDelayed(this, 60 * 60 * 1000L);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        web = new WebView(this);
        Board.setup(web);
        web.addJavascriptInterface(new TvBridge(this), "TV");
        setContentView(web);
        web.loadUrl(Board.BASE);
        web.requestFocus();
    }

    @Override protected void onResume() {
        super.onResume();
        handler.postDelayed(reload, 60 * 60 * 1000L);
    }

    @Override protected void onPause() {
        handler.removeCallbacks(reload);
        super.onPause();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) { finish(); return true; }
        return super.onKeyDown(keyCode, event);
    }

    @Override protected void onDestroy() {
        if (web != null) { web.destroy(); web = null; }
        super.onDestroy();
    }
}
