#!/usr/bin/env python3
"""タスクのデータ（平文JSON）を合言葉で暗号化して data/tasks.enc.json に書き出す。

使い方:
  TASKS_PASSCODE=合言葉 python3 scripts/encrypt_tasks.py 平文.json

・平文はリポジトリに置かないこと（公開されるため）
・暗号方式: PBKDF2-SHA256（30万回）で鍵を作り、AES-256-GCMで暗号化
  （テレビ側はブラウザ標準のWeb Crypto APIで同じ手順で復号する）
"""
import base64, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 300_000

def main():
    passcode = os.environ.get("TASKS_PASSCODE")
    if not passcode or len(sys.argv) != 2:
        sys.exit("TASKS_PASSCODE と平文ファイルを指定してください")
    plain = open(sys.argv[1], "rb").read()
    json.loads(plain)  # 正しいJSONか確認
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(passcode.encode())
    ct = AESGCM(key).encrypt(iv, plain, None)
    b64 = lambda b: base64.b64encode(b).decode()
    out = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "tasks.enc.json")
    json.dump(out, open(path, "w"), indent=1)
    print("wrote", path, len(ct), "bytes")

if __name__ == "__main__":
    main()
