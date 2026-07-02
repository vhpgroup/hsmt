# -*- coding: utf-8 -*-
"""Cache SQLite theo hash thông số + lưu/mở project JSON. Chạy lại cùng nội dung = 0 credit."""
import json, os, sqlite3, time

APPDIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~/.config"), "hsmt")
os.makedirs(APPDIR, exist_ok=True)
DB = os.path.join(APPDIR, "cache.db")
CFG = os.path.join(APPDIR, "config.json")


def _conn():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT, ts REAL)")
    return c


def get(key, ttl_days=30):
    c = _conn()
    row = c.execute("SELECT v, ts FROM kv WHERE k=?", (key,)).fetchone()
    c.close()
    if row and time.time() - row[1] < ttl_days * 86400:
        return json.loads(row[0])
    return None


def put(key, value):
    c = _conn()
    c.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)", (key, json.dumps(value, ensure_ascii=False), time.time()))
    c.commit(); c.close()


def clear():
    c = _conn(); c.execute("DELETE FROM kv"); c.commit(); c.close()


def load_config():
    if os.path.exists(CFG):
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def save_project(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_project(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
