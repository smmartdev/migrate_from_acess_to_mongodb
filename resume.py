# -*- coding: utf-8 -*-
"""
resume.py
---------
آلية استكمال العمل (Resume) - نسخة عامة تدعم أي عدد من الجداول بأي أسماء،
وليس فقط جداول محددة سلفاً.

شكل resume.json الجديد:
{
  "tables": {
    "Sgaza": {"offset": 140000, "done": false},
    "المحافظات": {"offset": 17, "done": true},
    "أي_جدول_آخر": {"offset": 0, "done": false}
  }
}
"""

import json
import os

import config


def _default_state():
    return {"tables": {}}


def load_resume():
    """تحميل حالة الاستكمال، أو حالة افتراضية فارغة إذا لم يوجد الملف أو كان تالفاً."""
    if not os.path.exists(config.RESUME_FILE):
        return _default_state()
    try:
        with open(config.RESUME_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_state()

    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        return _default_state()
    return data


def save_resume(state):
    """حفظ آمن (كتابة لملف مؤقت ثم استبدال الملف الأصلي) لتفادي التلف عند انقطاع الكهرباء."""
    tmp_file = config.RESUME_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, config.RESUME_FILE)


def _table_entry(state, table_name):
    return state["tables"].setdefault(table_name, {"offset": 0, "done": False})


def is_table_done(state, table_name):
    return bool(state["tables"].get(table_name, {}).get("done", False))


def get_table_offset(state, table_name):
    return int(state["tables"].get(table_name, {}).get("offset", 0))


def update_table_offset(state, table_name, offset):
    entry = _table_entry(state, table_name)
    entry["offset"] = int(offset)
    save_resume(state)
    return state


def mark_table_done(state, table_name):
    entry = _table_entry(state, table_name)
    entry["done"] = True
    save_resume(state)
    return state


def is_fresh_state(state):
    """
    هل هذه بداية جديدة فعلياً (لا يوجد أي تقدم محفوظ لأي جدول)؟
    ملاحظة: بعد اكتمال تشغيل سابق بنجاح، تبقى الجداول موجودة بحالة done=True،
    لذلك is_fresh_state ترجع False (وهذا مقصود: لا نريد حذف بيانات مكتملة
    عند إعادة تشغيل عادية بدون --fresh).
    """
    return not state.get("tables")


def reset_resume():
    """حذف resume.json بالكامل للبدء من الصفر (يُستخدم مع --fresh)."""
    if os.path.exists(config.RESUME_FILE):
        os.remove(config.RESUME_FILE)