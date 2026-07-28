# -*- coding: utf-8 -*-
"""
test_stage8.py
---------------
اختبار شامل لـ migrate.py العام (run_migration) بمحاكاة كاملة لواجهة pyodbc
(تماماً كما في test_stage7.py) لضمان أن الاكتشاف التلقائي للجداول يعمل
من البداية للنهاية عبر الملف الرئيسي فعلياً.

شغّله بعد تحديث migrate.py:
    python test_stage8.py
"""

import re
from collections import namedtuple

import mongomock

import config
import resume
import importer
from migrate import run_migration

TableRow = namedtuple("TableRow", ["table_name", "table_type"])
ColumnRow = namedtuple("ColumnRow", ["column_name", "ordinal_position"])
PKRow = namedtuple("PKRow", ["column_name"])


class FakeCursor:
    def __init__(self, schema):
        self.schema = schema
        self._rows = []
        self._pos = 0

    def tables(self, tableType=None):
        return [
            TableRow(table_name=name, table_type=meta["type"])
            for name, meta in self.schema.items()
            if not tableType or meta["type"] == tableType
        ]

    def columns(self, table=None):
        cols = self.schema[table]["columns"]
        return [ColumnRow(column_name=c, ordinal_position=i + 1) for i, c in enumerate(cols)]

    def primaryKeys(self, table=None):
        return [PKRow(column_name=c) for c in self.schema[table].get("pk", [])]

    def execute(self, query):
        match = re.search(r"FROM \[([^\]]+)\]", query)
        table_name = match.group(1)
        rows = list(self.schema[table_name]["rows"])
        if "ORDER BY" in query:
            rows = sorted(rows, key=lambda r: r[0])
        self._rows = rows
        self._pos = 0

    def fetchmany(self, size):
        chunk = self._rows[self._pos: self._pos + size]
        self._pos += size
        return chunk

    def fetchone(self):
        return (len(self._rows),)


class FakeConnection:
    def __init__(self, schema):
        self.schema = schema

    def cursor(self):
        return FakeCursor(self.schema)

    def close(self):
        pass


SCHEMA = {
    "Sgaza": {
        "type": "TABLE",
        "columns": ["الهوية", "الاسم"],
        "pk": ["الهوية"],
        "rows": [(410221000 + i, f"اسم{i}") for i in range(23)],
    },
    "المحافظات": {
        "type": "TABLE",
        "columns": ["رقم المحافظة", "اسم المحافظة"],
        "pk": ["رقم المحافظة"],
        "rows": [(81, "غزة"), (82, "خانيونس"), (80, "رفح")],
    },
    "MSysACEs": {
        "type": "SYSTEM TABLE",
        "columns": ["x"],
        "pk": [],
        "rows": [("x",)],
    },
}


def main():
    original_batch_size = config.BATCH_SIZE
    config.BATCH_SIZE = 10
    try:
        run_tests()
    finally:
        config.BATCH_SIZE = original_batch_size


def run_tests():
    conn = FakeConnection(SCHEMA)

    # -----------------------------------------------------
    # 1) تشغيل كامل من الصفر عبر run_migration (يمثل تشغيل migrate.py فعلياً)
    # -----------------------------------------------------
    client = mongomock.MongoClient()
    db = client["test_generic_db"]
    resume.reset_resume()

    result = run_migration(conn, db, fresh=True, show_progress=True)

    assert db["Sgaza"].count_documents({}) == 23
    assert db["المحافظات"].count_documents({}) == 3
    assert "MSysACEs" not in db.list_collection_names()
    assert result["tables"]["Sgaza"] == 23
    assert "الهوية_unique" in db["Sgaza"].index_information()
    print("الخطوة 1: تشغيل كامل تلقائي عبر run_migration نجح -> اكتُشفت الجداول واستُوردت والفهارس أُنشئت")

    # -----------------------------------------------------
    # 2) إعادة تشغيل بدون --fresh يجب ألا يكرر شيئاً (Idempotency)
    # -----------------------------------------------------
    run_migration(conn, db, fresh=False, show_progress=False)
    assert db["Sgaza"].count_documents({}) == 23
    print("الخطوة 2: إعادة تشغيل عادية بعد الاكتمال لا تكرر أي بيانات")

    # -----------------------------------------------------
    # 3) محاكاة انقطاع فعلي أثناء استيراد Sgaza ثم استكمال عبر run_migration
    # -----------------------------------------------------
    resume.reset_resume()
    client2 = mongomock.MongoClient()
    db2 = client2["test_generic_db2"]

    cursor = conn.cursor()
    cols = importer.list_columns(conn, "Sgaza")
    first_batch = next(importer.fetch_batches(cursor, "Sgaza", cols, batch_size=10, order_by="الهوية"))
    importer.bulk_insert(db2["Sgaza"], first_batch)

    state = resume.load_resume()
    resume.update_table_offset(state, "Sgaza", 10)

    assert db2["Sgaza"].count_documents({}) == 10
    print("الخطوة 3أ: تمت محاكاة انقطاع حقيقي بعد أول 10 سجلات من Sgaza فقط")

    # إعادة التشغيل بدون --fresh: يجب اكتشاف الجداول تلقائياً من جديد، وعدم حذف شيء، والاستكمال
    result3 = run_migration(conn, db2, fresh=False, show_progress=True)

    total = db2["Sgaza"].count_documents({})
    distinct_ids = db2["Sgaza"].distinct("الهوية")
    assert total == 23, f"توقعنا 23، وجدنا {total}"
    assert len(distinct_ids) == 23, "يوجد تكرار بعد الاستكمال!"
    assert db2["المحافظات"].count_documents({}) == 3  # جدول لم يُلمس بعد -> يُستورد بالكامل الآن
    print("الخطوة 3ب: استكمال حقيقي عبر migrate.py -> 23 سجل بدون تكرار، وبقية الجداول استُوردت تلقائياً")

    print()
    print("OK: migrate.py العام يعمل بنجاح بجميع السيناريوهات (اكتشاف تلقائي كامل، تشغيل، إعادة تشغيل، استكمال)")


if __name__ == "__main__":
    main()