# -*- coding: utf-8 -*-
"""
test_stage7.py
---------------
اختبار شامل لـ importer.py العام (بدون أي جدول محدد سلفاً).
يحاكي واجهة pyodbc الحقيقية بالكامل: tables(), columns(), primaryKeys(),
execute(), fetchmany(), fetchone() - لضمان أن الاكتشاف التلقائي يعمل فعلياً.

شغّله بعد تحديث importer.py:
    python test_stage7.py
"""

import re
from collections import namedtuple

import mongomock

import config
import resume
from importer import (
    list_tables, list_columns, get_primary_key,
    clean_value, row_to_document, fetch_batches, bulk_insert,
    drop_collection, import_table, create_index_for_table, count_table_rows,
)

TableRow = namedtuple("TableRow", ["table_name", "table_type"])
ColumnRow = namedtuple("ColumnRow", ["column_name", "ordinal_position"])
PKRow = namedtuple("PKRow", ["column_name"])


# ============================================================
# محاكاة كاملة لواجهة pyodbc (وليس فقط fetchmany كما في المراحل السابقة)
# ============================================================
class FakeCursor:
    def __init__(self, schema):
        self.schema = schema  # dict: table_name -> {"type":..., "columns":[...], "pk":[...], "rows":[...]}
        self._rows = []
        self._pos = 0

    def tables(self, tableType=None):
        result = []
        for name, meta in self.schema.items():
            if tableType and meta["type"] != tableType:
                continue
            result.append(TableRow(table_name=name, table_type=meta["type"]))
        return result

    def columns(self, table=None):
        cols = self.schema[table]["columns"]
        return [ColumnRow(column_name=c, ordinal_position=i + 1) for i, c in enumerate(cols)]

    def primaryKeys(self, table=None):
        pk_cols = self.schema[table].get("pk", [])
        return [PKRow(column_name=c) for c in pk_cols]

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


# ============================================================
# بيانات تجريبية: جدول أشخاص (مفتاح أساسي بسيط)، جدول محافظات (مفتاح أساسي)،
# جدول سجل زيارات بلا مفتاح أساسي إطلاقاً، وجدول نظام يجب تجاهله
# ============================================================
SCHEMA = {
    "Sgaza": {
        "type": "TABLE",
        "columns": ["الهوية", "الاسم", "الجنس"],
        "pk": ["الهوية"],
        "rows": [(410221000 + i, f"اسم{i}", "أنثى" if i % 2 == 0 else "ذكر") for i in range(23)],
    },
    "المحافظات": {
        "type": "TABLE",
        "columns": ["رقم المحافظة", "اسم المحافظة"],
        "pk": ["رقم المحافظة"],
        "rows": [(81, "غزة"), (82, "خانيونس"), (80, "رفح")],
    },
    "سجل_الزيارات": {
        "type": "TABLE",
        "columns": ["اسم الزائر", "التاريخ"],
        "pk": [],  # بلا مفتاح أساسي إطلاقاً
        "rows": [(f"زائر{i}", "2024-01-01") for i in range(12)],
    },
    "MSysObjects": {
        "type": "SYSTEM TABLE",
        "columns": ["Name"],
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
    # 1) اكتشاف الجداول: يجب استثناء جدول النظام تلقائياً
    # -----------------------------------------------------
    tables = list_tables(conn)
    assert set(tables) == {"Sgaza", "المحافظات", "سجل_الزيارات"}
    assert "MSysObjects" not in tables
    print("الخطوة 1: list_tables اكتشف 3 جداول حقيقية واستثنى جدول النظام تلقائياً")

    # -----------------------------------------------------
    # 2) اكتشاف الأعمدة بالترتيب الصحيح
    # -----------------------------------------------------
    cols = list_columns(conn, "Sgaza")
    assert cols == ["الهوية", "الاسم", "الجنس"]
    print("الخطوة 2: list_columns يرجع أسماء الأعمدة بالترتيب الصحيح")

    # -----------------------------------------------------
    # 3) اكتشاف المفتاح الأساسي (موجود / غير موجود)
    # -----------------------------------------------------
    assert get_primary_key(conn, "Sgaza") == "الهوية"
    assert get_primary_key(conn, "المحافظات") == "رقم المحافظة"
    assert get_primary_key(conn, "سجل_الزيارات") is None
    print("الخطوة 3: get_primary_key يكتشف المفتاح الأساسي بشكل صحيح (أو None عند غيابه)")

    # -----------------------------------------------------
    # 4) clean_value: تحويل Decimal (نفس الخطأ الحقيقي الذي واجهناه سابقاً)
    # -----------------------------------------------------
    import decimal
    assert clean_value(decimal.Decimal("2")) == 2
    assert isinstance(clean_value(decimal.Decimal("2")), int)
    assert clean_value(decimal.Decimal("2.5")) == 2.5
    assert clean_value("   نص بمسافات   ") == "نص بمسافات"
    assert clean_value("   ") is None
    assert clean_value(None) is None
    print("الخطوة 4: clean_value يحوّل Decimal بشكل صحيح (يمنع تكرار الخطأ الذي واجهناه فعلياً)")

    # -----------------------------------------------------
    # 5) استيراد كامل لكل الجداول من الصفر + إنشاء الفهارس
    # -----------------------------------------------------
    client = mongomock.MongoClient()
    db = client["test_db"]
    resume.reset_resume()
    state = resume.load_resume()

    for t in tables:
        drop_collection(db, t)

    schema_pk = {t: get_primary_key(conn, t) for t in tables}
    for t in tables:
        import_table(conn, db, t, state, resume, primary_key=schema_pk[t])

    assert db["Sgaza"].count_documents({}) == 23
    assert db["المحافظات"].count_documents({}) == 3
    assert db["سجل_الزيارات"].count_documents({}) == 12

    sample = db["Sgaza"].find_one({"الهوية": 410221000})
    assert sample["الاسم"] == "اسم0"
    assert sample["الجنس"] == "أنثى"
    print("الخطوة 5: استيراد كل الجداول (بأسماء وحقول عربية مختلفة تماماً) نجح بالكامل")

    for t in tables:
        create_index_for_table(db, t, schema_pk[t])

    assert "الهوية_unique" in db["Sgaza"].index_information()
    assert "رقم المحافظة_unique" in db["المحافظات"].index_information()
    # سجل_الزيارات بلا مفتاح أساسي -> لا فهرس فريد له، ويجب ألا يفشل البرنامج
    assert "_id_" in db["سجل_الزيارات"].index_information()
    print("الخطوة 6: الفهارس الفريدة أُنشئت للجداول التي لها مفتاح أساسي فقط، بدون أي خطأ للجدول الآخر")

    # -----------------------------------------------------
    # 7) محاكاة انقطاع واستكمال حقيقي على جدول Sgaza (23 سجل، batch=10)
    # -----------------------------------------------------
    client2 = mongomock.MongoClient()
    db2 = client2["test_db2"]
    resume.reset_resume()
    state2 = resume.load_resume()

    cursor = conn.cursor()
    first_batch = next(fetch_batches(cursor, "Sgaza", cols, batch_size=10, order_by="الهوية"))
    inserted = bulk_insert(db2["Sgaza"], first_batch)
    assert inserted == 10
    resume.update_table_offset(state2, "Sgaza", 10)

    fresh_state = resume.load_resume()
    import_table(conn, db2, "Sgaza", fresh_state, resume, primary_key="الهوية")

    total = db2["Sgaza"].count_documents({})
    distinct_ids = db2["Sgaza"].distinct("الهوية")
    assert total == 23, f"توقعنا 23، وجدنا {total}"
    assert len(distinct_ids) == 23, "يوجد تكرار بعد الاستكمال!"
    print("الخطوة 7: محاكاة انقطاع واستكمال حقيقي على جدول Sgaza -> 23 سجل بدون تكرار أو فقدان")

    print()
    print("OK: importer.py العام يعمل بنجاح بجميع السيناريوهات (اكتشاف تلقائي، استيراد، فهارس، استكمال)")


if __name__ == "__main__":
    main()