# タスク同期の手順（Claude用・毎朝）

Claude Docs のドキュメント「坂井家 プライベート予定・タスク」
（https://claude.ai/code/artifact/042df918-e26e-4200-9c33-cb01037a7874）を読み、
テレビ用に暗号化して `data/tasks.enc.json` を更新する。

## 重要：平文を公開しない
- このリポジトリは公開されている。**平文のタスクJSONは絶対にコミットしない**
- 平文はスクラッチ（作業用一時フォルダ）に書き、`scripts/encrypt_tasks.py` で暗号化したものだけをコミットする
- 合言葉はスケジュールされたタスクの指示文にだけ書かれている。リポジトリに書かない

## 手順
1. Claude Docs の read で上記ドキュメントを読む
2. 次の形の平文JSONを作る（キー名は固定）
   - `updated_at`：実行日時（+09:00）
   - `tasks`：「予約・手配タスク」の未完了項目。`title`（短く）、`detail`（補足）、`urgent`（冒頭の「いちばん急ぐ」に挙がっているもの・期限が2週間以内のものは true）
   - `done`：完了・予約済みになった項目
   - `schedule`：「確定している予定」の表と、本文中の誕生日・記念日。`date_from`・`date_to`（YYYY-MM-DD）、`title`、`status`
   - `wishlist`：「行きたい場所リスト」。`title`、`dates`、`memo`
3. `TASKS_PASSCODE=<合言葉> python3 scripts/encrypt_tasks.py <平文JSONのパス>` を実行
4. `data/tasks.enc.json` だけをコミット（メッセージ「タスク同期 YYYY-MM-DD」）して main にプッシュ。内容が前回と同じなら何もしない
