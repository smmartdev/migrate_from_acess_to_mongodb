# -*- coding: utf-8 -*-
"""
test_stage5.py
---------------
اختبار شامل لـ migrate.py (بالتحديد دالة run_migration، وهي المنطق الكامل
بدون فتح اتصالات حقيقية) عبر محاكاة Access وMongoDB تماماً كما في test_stage4.py.

يغطي 3 سيناريوهات كاملة:
  1) تشغيل كامل من الصفر (Fresh Run): يجب أن يستورد كل شيء وينشئ الفهارس.
  2) إعادة التشغيل بعد الاكتمال (Idempotency): يجب ألا يكرر أي بيانات.
  3) الاستكمال بعد انقطاع جزئي حقيقي أثناء استيراد الأشخاص (Resume).

شغّله بعد إنشاء migrate.py:
    python test_stage5.py

يحتاج نفس متطلبات اختبار المرحلة 4:
    pip install pymongo mongomock tqdm
"""

import re

import mongomock

import config
import resume
from migrate import run_migration


# ============================================================
# نفس محاكاة Access المستخدمة في test_stage4.py (مع دعم fetchone لـ COUNT(*))
# ============================================================
class FakeCursor:
    def __init__(self, tables):
        self.tables = tables
        self._rows = []
        self._pos = 0

    def execute(self, query):
        match = re.search(r"FROM \[([^\]]+)\]", query)
        table_name = match.group(1)
        rows = list(self.tables[table_name])
        if "ORDER BY" in query:
            rows = sorted(rows, key=lambda r: r[0])
        self._rows = rows
        self._pos = 0

    def fetchmany(self, size):
        chunk = self._rows[self._pos: self._pos + size]
        self._pos += size
        return chunk

    def fetchone(self):
        # يُستخدم فقط لاستعلامات SELECT COUNT(*)
        return (len(self._rows),)


class FakeConnection:
    def __init__(self, tables):
        self.tables = tables

    def cursor(self):
        return FakeCursor(self.tables)

    def close(self):
        pass


GOVERNORATES_ROWS = [(81, "غزة"), (82, "خانيونس"), (80, "رفح")]
REGIONS_ROWS = [(5700, "غزة"), (5300, "جباليا"), (5500, "خان يونس- البلد")]
PEOPLE_ROWS = [
    (
        410221000 + i, f"اسم{i}", "طلال", "السيد", "ابراهيم", "رضا",
        "1990-05-15", "أنثى" if i % 2 == 0 else "ذكر", 81, 5700, "تل الهوى",
    )
    for i in range(25)
]

FAKE_TABLES = {
    config.TABLE_GOVERNORATES: GOVERNORATES_ROWS,
    config.TABLE_REGIONS: REGIONS_ROWS,
    config.TABLE_PEOPLE: PEOPLE_ROWS,
}


def main():
    original_batch_size = config.BATCH_SIZE
    config.BATCH_SIZE = 10
    try:
        run_tests()
    finally:
        config.BATCH_SIZE = original_batch_size


def run_tests():
    conn = FakeConnection(FAKE_TABLES)
    client = mongomock.MongoClient()
    db = client[config.MONGO_DB_NAME]
    resume.reset_resume()

    # -----------------------------------------------------
    # 1) تشغيل كامل من الصفر
    # -----------------------------------------------------
    result = run_migration(conn, db, fresh=True, show_progress=True)

    assert db[config.COLLECTION_GOVERNORATES].count_documents({}) == 3
    assert db[config.COLLECTION_REGIONS].count_documents({}) == 3
    assert db[config.COLLECTION_PEOPLE].count_documents({}) == 25
    assert result["people_count"] == 25

    idx_names = db[config.COLLECTION_PEOPLE].index_information().keys()
    assert "idNumber_unique" in idx_names
    print("الخطوة 1: تشغيل كامل من الصفر نجح -> 3 محافظات + 3 مناطق + 25 شخص + الفهارس")

    # -----------------------------------------------------
    # 2) إعادة التشغيل بعد الاكتمال يجب ألا يكرر شيئاً (Idempotency)
    # -----------------------------------------------------
    result2 = run_migration(conn, db, fresh=False, show_progress=False)
    assert db[config.COLLECTION_PEOPLE].count_documents({}) == 25
    assert db[config.COLLECTION_GOVERNORATES].count_documents({}) == 3
    print("الخطوة 2: إعادة تشغيل migrate.py بعد الاكتمال لا يكرر أي بيانات (تخطي كامل)")

    # -----------------------------------------------------
    # 3) محاكاة انقطاع فعلي في منتصف استيراد الأشخاص ثم إعادة التشغيل
    # -----------------------------------------------------
    resume.reset_resume()
    client2 = mongomock.MongoClient()
    db2 = client2[config.MONGO_DB_NAME]

    # نستورد المحافظات والمناطق يدوياً فقط (محاكاة أنها اكتملت في تشغيل سابق)
    import importer
    state = resume.load_resume()
    importer.import_governorates(conn, db2, state, resume)
    importer.import_regions(conn, db2, state, resume)

    # محاكاة إدخال أول Batch فقط من الأشخاص (10 سجلات) ثم "انقطاع الكهرباء"
    cursor = conn.cursor()
    people_collection = db2[config.COLLECTION_PEOPLE]
    batches = importer.fetch_batches(
        cursor, config.TABLE_PEOPLE, config.PEOPLE_ACCESS_COLUMNS,
        batch_size=10, order_by="الهوية",
    )
    first_batch = next(batches)
    docs = [importer.build_people_document(row) for row in first_batch]
    importer.bulk_insert(people_collection, docs)
    resume.update_people_offset(state, 10)

    assert db2[config.COLLECTION_PEOPLE].count_documents({}) == 10
    print("الخطوة 3أ: تمت محاكاة انقطاع حقيقي بعد أول 10 سجلات فقط من الأشخاص")

    # "إعادة تشغيل البرنامج" -> يجب أن يكمل تلقائياً بدون --fresh وبدون حذف أي شيء
    result3 = run_migration(conn, db2, fresh=False, show_progress=True)

    total = db2[config.COLLECTION_PEOPLE].count_documents({})
    distinct_ids = db2[config.COLLECTION_PEOPLE].distinct("idNumber")
    assert total == 25, f"توقعنا 25 سجل بعد الاستكمال، وجدنا {total}"
    assert len(distinct_ids) == 25, "يوجد تكرار في idNumber بعد الاستكمال!"
    assert db2[config.COLLECTION_GOVERNORATES].count_documents({}) == 3
    idx_names2 = db2[config.COLLECTION_PEOPLE].index_information().keys()
    assert "idNumber_unique" in idx_names2
    print("الخطوة 3ب: بعد إعادة التشغيل بدون --fresh -> اكتمل الاستيراد تلقائياً (25 سجل، بدون تكرار)")

    print()
    print("OK: migrate.py يعمل بنجاح بجميع السيناريوهات (تشغيل كامل، إعادة تشغيل آمنة، استكمال بعد انقطاع)")


if __name__ == "__main__":
    main()