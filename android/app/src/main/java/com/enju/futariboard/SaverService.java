package com.enju.futariboard;

import android.content.Intent;
import android.service.dreams.DreamService;
import android.view.KeyEvent;
import android.webkit.WebView;

/** スクリーンセーバー：?mode=saver のページを表示。リモコンのボタンで一覧画面を開く */
public class SaverService extends DreamService {
    private WebView web;

    @Override
    public void onAttachedToWindow() {
        super.onAttachedToWindow();
        setInteractive(true);
        setFullscreen(true);
        setScreenBright(true);
        web = new WebView(this);
        Board.setup(web);
        setContentView(web);
        web.loadUrl(Board.BASE + "?mode=saver");
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        if (event.getAction() == KeyEvent.ACTION_UP) {
            int k = event.getKeyCode();
            if (k == KeyEvent.KEYCODE_DPAD_CENTER || k == KeyEvent.KEYCODE_ENTER) {
                Intent i = new Intent(this, MainActivity.class);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
            }
            finish();
        }
        return true;
    }

    @Override
    public void onDetachedFromWindow() {
        if (web != null) { web.destroy(); web = null; }
        super.onDetachedFromWindow();
    }
}
