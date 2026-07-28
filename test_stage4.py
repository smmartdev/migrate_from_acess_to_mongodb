# -*- coding: utf-8 -*-
"""
test_stage4.py
---------------
اختبار شامل لـ importer.py بدون الحاجة لملف Access حقيقي أو خادم MongoDB حقيقي:

- Access يتم محاكاته بـ FakeCursor يطبّق فعلياً fetchmany() بنفس سلوك pyodbc.
- MongoDB يتم محاكاته بمكتبة mongomock (تطبيق حقيقي في الذاكرة لسلوك bulk_write،
  create_index بما فيها unique index، drop، إلخ) لذلك الاختبار واقعي جداً.

يغطي هذا الاختبار:
  1) drop_all_collections
  2) استيراد المحافظات والمناطق
  3) استيراد الأشخاص (تحويل الحقول + التواريخ + الأرقام)
  4) محاكاة انقطاع حقيقي أثناء استيراد الأشخاص ثم إعادة التشغيل (Resume)
     والتأكد من عدم فقدان أو تكرار أي سجل
  5) إنشاء الفهارس (بما فيها unique index) والتأكد من عدم وجود تكرار في idNumber

شغّله بعد إنشاء importer.py:
    python test_stage4.py

المتطلبات الإضافية لهذا الاختبار فقط (غير مطلوبة على السيرفر النهائي):
    pip install mongomock
"""

import datetime
import re

import mongomock

import config
import resume
from importer import (
    build_people_document,
    build_governorate_document,
    build_region_document,
    drop_all_collections,
    import_governorates,
    import_regions,
    import_people,
    create_indexes,
    fetch_batches,
    bulk_insert,
)


# ============================================================
# محاكاة Access: FakeCursor يطبّق fetchmany فعلياً كما يفعل pyodbc
# ============================================================
class FakeCursor:
    def __init__(self, tables):
        self.tables = tables  # dict: table_name -> list[tuple]
        self._rows = []
        self._pos = 0
        self.last_query = None

    def execute(self, query):
        self.last_query = query
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


class FakeConnection:
    def __init__(self, tables):
        self.tables = tables

    def cursor(self):
        return FakeCursor(self.tables)


# ============================================================
# بيانات تجريبية (25 شخص لاختبار عدة Batches، 3 محافظات، 3 مناطق)
# ============================================================
GOVERNORATES_ROWS = [
    (81, "غزة"),
    (82, "خانيونس"),
    (80, "رفح"),
]

REGIONS_ROWS = [
    (5700, "غزة"),
    (5300, "جباليا"),
    (5500, "خان يونس- البلد"),
]

PEOPLE_ROWS = [
    (
        410221000 + i,          # الهوية
        f"اسم{i}",               # الاسم
        "طلال",                  # الاب
        "السيد",                 # الجد
        "ابراهيم",               # العائلة
        "رضا",                   # اسم الام
        "1990-05-15",            # تاريخ الميلاد (نص، سيتم تحويله لـ datetime)
        "أنثى" if i % 2 == 0 else "ذكر",  # الجنس
        81,                      # رمز المحافظة
        5700,                    # رمز المنطقة
        "تل الهوى",              # الحي
    )
    for i in range(25)
]

FAKE_TABLES = {
    config.TABLE_GOVERNORATES: GOVERNORATES_ROWS,
    config.TABLE_REGIONS: REGIONS_ROWS,
    config.TABLE_PEOPLE: PEOPLE_ROWS,
}


def make_env():
    """تجهيز بيئة اختبار جديدة نظيفة (اتصال وهمي + قاعدة mongomock + resume نظيف)."""
    conn = FakeConnection(FAKE_TABLES)
    client = mongomock.MongoClient()
    db = client[config.MONGO_DB_NAME]
    resume.reset_resume()
    state = resume.load_resume()
    return conn, db, state


def main():
    original_batch_size = config.BATCH_SIZE
    config.BATCH_SIZE = 10  # لإجبار وجود عدة Batches (10 + 10 + 5) أثناء الاختبار

    try:
        run_tests()
    finally:
        config.BATCH_SIZE = original_batch_size  # إرجاع القيمة الأصلية دائماً


def run_tests():
    # -----------------------------------------------------
    # 0) اختبار دوال التحويل النقية (بدون أي DB)
    # -----------------------------------------------------
    sample_row = dict(zip(config.PEOPLE_ACCESS_COLUMNS, PEOPLE_ROWS[0]))
    doc = build_people_document(sample_row)
    assert doc["idNumber"] == 410221000
    assert isinstance(doc["idNumber"], int)
    assert doc["birthDate"] == datetime.datetime(1990, 5, 15)
    assert isinstance(doc["birthDate"], datetime.datetime)
    assert doc["mohafzaCode"] == 81
    assert doc["area"] == "تل الهوى"
    assert "governorateName" not in doc and "regionName" not in doc
    print("الخطوة 0: build_people_document يحوّل الحقول والتاريخ والأرقام بشكل صحيح")

    gov_doc = build_governorate_document(dict(zip(["رقم المحافظة", "اسم المحافظة"], GOVERNORATES_ROWS[0])))
    assert gov_doc == {"code": 81, "name": "غزة"}
    print("الخطوة 0ب: build_governorate_document يعمل بشكل صحيح")

    # -----------------------------------------------------
    # 1) drop_all_collections يعمل حتى لو الـ Collections غير موجودة أصلاً
    # -----------------------------------------------------
    conn, db, state = make_env()
    drop_all_collections(db)
    print("الخطوة 1: drop_all_collections تعمل بدون أخطاء")

    # -----------------------------------------------------
    # 2) استيراد المحافظات والمناطق والتأكد من العدد والمحتوى
    # -----------------------------------------------------
    import_governorates(conn, db, state, resume)
    import_regions(conn, db, state, resume)

    assert db[config.COLLECTION_GOVERNORATES].count_documents({}) == 3
    assert db[config.COLLECTION_REGIONS].count_documents({}) == 3
    gaza = db[config.COLLECTION_GOVERNORATES].find_one({"code": 81})
    assert gaza["name"] == "غزة"
    assert resume.is_stage_done(state, "governorates") is True
    assert resume.is_stage_done(state, "regions") is True
    print("الخطوة 2: استيراد المحافظات (3) والمناطق (3) نجح بالكامل والمحتوى صحيح")

    # تشغيل الاستيراد مرة ثانية للتأكد أن Resume يتخطاها بدون تكرار
    import_governorates(conn, db, state, resume)
    assert db[config.COLLECTION_GOVERNORATES].count_documents({}) == 3
    print("الخطوة 2ب: إعادة استدعاء import_governorates لا يكرر البيانات بفضل Resume")

    # -----------------------------------------------------
    # 3) محاكاة انقطاع حقيقي أثناء استيراد الأشخاص بعد أول Batch (10 سجلات)
    # -----------------------------------------------------
    cursor = conn.cursor()
    people_collection = db[config.COLLECTION_PEOPLE]

    batches_gen = fetch_batches(
        cursor, config.TABLE_PEOPLE, config.PEOPLE_ACCESS_COLUMNS,
        batch_size=10, order_by="الهوية",
    )
    first_batch = next(batches_gen)
    assert len(first_batch) == 10

    first_docs = [build_people_document(row) for row in first_batch]
    inserted = bulk_insert(people_collection, first_docs)
    assert inserted == 10

    # هنا "ينقطع البرنامج" - نحفظ آخر offset فقط، ولا نكمل القراءة من batches_gen
    state = resume.update_people_offset(state, 10)
    print("الخطوة 3: تمت محاكاة انقطاع البرنامج بعد إدخال أول 10 سجلات، وتم حفظ offset=10")

    # -----------------------------------------------------
    # 4) "إعادة تشغيل" البرنامج: تحميل resume.json من جديد ثم استدعاء import_people
    # -----------------------------------------------------
    fresh_state = resume.load_resume()
    assert resume.get_people_offset(fresh_state) == 10
    assert resume.is_stage_done(fresh_state, "people") is False

    import_people(conn, db, fresh_state, resume)

    total_people = db[config.COLLECTION_PEOPLE].count_documents({})
    distinct_ids = db[config.COLLECTION_PEOPLE].distinct("idNumber")

    assert total_people == 25, f"توقعنا 25 سجل، وجدنا {total_people}"
    assert len(distinct_ids) == 25, "يوجد تكرار أو نقص في idNumber بعد الاستكمال!"
    assert resume.is_stage_done(resume.load_resume(), "people") is True
    print("الخطوة 4: بعد الاستكمال (Resume) -> 25 سجل بالضبط بدون تكرار أو فقدان")

    # -----------------------------------------------------
    # 5) إنشاء الفهارس والتأكد من عمل unique index بدون أخطاء (يثبت عدم وجود تكرار)
    # -----------------------------------------------------
    create_indexes(db)
    index_names = db[config.COLLECTION_PEOPLE].index_information().keys()
    assert "idNumber_unique" in index_names
    assert "fullname_compound_idx" in index_names
    gov_index_names = db[config.COLLECTION_GOVERNORATES].index_information().keys()
    assert "code_unique" in gov_index_names
    print("الخطوة 5: تم إنشاء جميع الفهارس (بما فيها unique) بنجاح -> لا يوجد أي تكرار في idNumber")

    print()
    print("OK: importer.py يعمل بنجاح بجميع السيناريوهات (استيراد، تحويل بيانات، انقطاع/استكمال، فهارس)")


if __name__ == "__main__":
    main()