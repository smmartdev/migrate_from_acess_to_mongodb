# -*- coding: utf-8 -*-
"""
importer.py
-----------
منطق الترحيل العام: يكتشف كل الجداول والأعمدة والمفتاح الأساسي تلقائياً
من ملف Access، وينقلها إلى MongoDB بدون أي Mapping أو أسماء محددة مسبقاً.

- اسم الـ Collection في MongoDB = نفس اسم الجدول في Access.
- أسماء الحقول في المستند = نفس أسماء الأعمدة في Access كما هي.
- إن وُجد مفتاح أساسي بسيط (عمود واحد) لجدول ما:
    * يُستخدم في ORDER BY لضمان ترتيب ثابت بين عمليات التشغيل (ضروري لصحة Resume).
    * يُنشأ عليه فهرس فريد (Unique Index) في نهاية الترحيل.
  إن لم يوجد (بلا مفتاح، أو مفتاح مركّب من أكثر من عمود)، يتم تسجيل تحذير
  في اللوج لأن دقة الاستكمال (Resume) بعد انقطاع في منتصف هذا الجدول تحديداً
  غير مضمونة 100% (لأن Access لا يضمن ترتيباً ثابتاً بدون ORDER BY).
"""

import datetime
import decimal

from pymongo import InsertOne

import config
from logger import import_logger, error_logger


# ============================================================
# 1) الاتصال بقواعد البيانات
# ============================================================

def get_access_connection(access_db_path):
    """فتح اتصال بأي ملف Access عبر مساره الكامل."""
    import pyodbc
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        r"DBQ=" + access_db_path + ";"
    )
    return pyodbc.connect(conn_str)


def get_mongo_client(mongo_uri=None):
    from pymongo import MongoClient
    return MongoClient(mongo_uri or config.DEFAULT_MONGO_URI)


def get_mongo_db(mongo_db_name, client=None):
    client = client or get_mongo_client()
    return client[mongo_db_name]


# ============================================================
# 2) اكتشاف الجداول والأعمدة والمفتاح الأساسي تلقائياً
# ============================================================

def list_tables(access_conn):
    """إرجاع أسماء كل الجداول الحقيقية (Base Tables) في Access، باستثناء جداول النظام."""
    cursor = access_conn.cursor()
    tables = []
    for row in cursor.tables(tableType="TABLE"):
        name = row.table_name
        if any(name.startswith(prefix) for prefix in config.SYSTEM_TABLE_PREFIXES):
            continue
        tables.append(name)
    return tables


def list_columns(access_conn, table_name):
    """إرجاع أسماء أعمدة جدول معيّن بالترتيب الصحيح (حسب ordinal_position)."""
    cursor = access_conn.cursor()
    rows = list(cursor.columns(table=table_name))
    rows.sort(key=lambda r: getattr(r, "ordinal_position", 0))
    return [row.column_name for row in rows]


def get_primary_key(access_conn, table_name):
    """
    إرجاع اسم عمود المفتاح الأساسي إن وُجد وكان بسيطاً (عمود واحد فقط).
    في حال عدم وجوده، أو كان مركّباً من عدة أعمدة، يرجع None.

    بعض تعريفات ODBC (خصوصاً Microsoft Access Driver القديم/32-bit) لا تدعم
    دالة SQLPrimaryKeys إطلاقاً وترمي استثناء (IM001) بدل إرجاع نتيجة فارغة.
    هذا لا يعني أن الجدول بلا مفتاح فعلياً، فقط أن السائق لا يدعم استعلامه؛
    لذلك نتعامل معه بأمان كـ "غير معروف" (None) بدل إيقاف الترحيل بالكامل.
    """
    try:
        cursor = access_conn.cursor()
        pk_columns = [row.column_name for row in cursor.primaryKeys(table=table_name)]
    except Exception as exc:
        error_logger.error(
            "تعذر الاستعلام عن المفتاح الأساسي لجدول %s (السائق/Driver لا يدعم SQLPrimaryKeys "
            "على الأرجح): %s -> سيُعامل الجدول كأنه بلا مفتاح أساسي معروف",
            table_name, exc,
        )
        return None

    if len(pk_columns) == 1:
        return pk_columns[0]
    return None


# ============================================================
# 3) تنظيف القيم وتحويل الصفوف إلى مستندات MongoDB
# ============================================================

def clean_value(value):
    """
    تحويل قيمة قادمة من Access إلى قيمة متوافقة مع BSON/MongoDB:
    - None يبقى None
    - decimal.Decimal (شائع جداً في حقول Access الرقمية) -> int أو float عادي
      (BSON لا يدعم decimal.Decimal مباشرة؛ محاولة إدخاله كانت تُفشل bulk_write بالكامل)
    - النصوص: إزالة المسافات الزائدة، والنص الفارغ -> None
    - باقي الأنواع (datetime, int, float, bool, bytes) تبقى كما هي لأنها مدعومة أصلاً في BSON
    """
    if value is None:
        return None
    if isinstance(value, decimal.Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def row_to_document(row, columns):
    """تحويل صف Access كامل إلى مستند MongoDB، بنفس أسماء أعمدة Access كما هي."""
    return {col: clean_value(row[i]) for i, col in enumerate(columns)}


# ============================================================
# 4) القراءة بدفعات (fetchmany فقط) والكتابة (bulk_write فقط)
# ============================================================

def fetch_batches(cursor, table_name, columns, batch_size=None, order_by=None):
    """Generator يقرأ جدولاً كاملاً دفعة تلو الأخرى باستخدام fetchmany فقط (ممنوع fetchall)."""
    batch_size = batch_size or config.BATCH_SIZE

    columns_sql = ", ".join(f"[{c}]" for c in columns)
    query = f"SELECT {columns_sql} FROM [{table_name}]"
    if order_by:
        query += f" ORDER BY [{order_by}]"

    cursor.execute(query)

    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        yield [row_to_document(row, columns) for row in rows]


def count_table_rows(access_conn, table_name):
    """عدد صفوف الجدول الكلي (لعرض شريط تقدم تقريبي فقط)، أو None عند الفشل."""
    try:
        cursor = access_conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
        row = cursor.fetchone()
        return int(row[0]) if row else None
    except Exception as exc:
        error_logger.error("تعذر حساب عدد سجلات %s: %s", table_name, exc)
        return None


def bulk_insert(collection, documents):
    """إدخال دفعة عبر bulk_write + InsertOne + ordered=False فقط. يرجع عدد المُدخل فعلياً."""
    if not documents:
        return 0

    operations = [InsertOne(doc) for doc in documents]

    try:
        result = collection.bulk_write(operations, ordered=False)
        return result.inserted_count
    except Exception as exc:
        error_logger.error(
            "خطأ أثناء bulk_write في %s | نوع الخطأ: %s | عدد المستندات في الدفعة: %s | التفاصيل: %s",
            collection.name, type(exc).__name__, len(documents), exc,
        )
        details = getattr(exc, "details", None)
        if details and "nInserted" in details:
            return details["nInserted"]
        return 0


# ============================================================
# 5) استيراد جدول واحد (عام تماماً - يُستخدم لأي جدول بأي اسم)
# ============================================================

def drop_collection(db, collection_name):
    db[collection_name].drop()
    import_logger.info("تم حذف Collection: %s", collection_name)


def import_table(access_conn, db, table_name, state, resume_module,
                  primary_key=None, progress_callback=None):
    """
    استيراد جدول واحد بالكامل من Access إلى MongoDB (Collection بنفس اسم الجدول)،
    مع دعم كامل لـ Resume بغض النظر عن اسم الجدول أو حجمه أو أعمدته.
    يرجع عدد السجلات التي تمت قراءتها في هذا التشغيل.
    """
    if resume_module.is_table_done(state, table_name):
        import_logger.info("تخطي %s: مستوردة مسبقاً بالكامل (Resume)", table_name)
        return 0

    start_offset = resume_module.get_table_offset(state, table_name)
    if start_offset:
        import_logger.info("استكمال استيراد %s من السجل رقم %s", table_name, start_offset)

    if primary_key is None:
        import_logger.info(
            "تنبيه: الجدول %s ليس له مفتاح أساسي بسيط -> ترتيب القراءة قد لا يكون "
            "ثابتاً 100%% بين عمليات التشغيل. يُفضّل عدم مقاطعة استيراد هذا الجدول تحديداً.",
            table_name,
        )

    cursor = access_conn.cursor()
    columns = list_columns(access_conn, table_name)
    collection = db[table_name]

    processed = 0
    total_inserted = 0

    for batch in fetch_batches(cursor, table_name, columns, order_by=primary_key):
        batch_start = processed
        processed += len(batch)

        if batch_start + len(batch) <= start_offset:
            continue

        skip_within_batch = max(0, start_offset - batch_start)
        docs = batch[skip_within_batch:]

        inserted = bulk_insert(collection, docs)
        total_inserted += inserted

        if inserted != len(docs):
            error_logger.error(
                "جدول %s | دفعة عند offset=%s: قراءة %s سجل، إدخال %s فقط -> راجع الأخطاء أعلاه",
                table_name, processed, len(docs), inserted,
            )

        resume_module.update_table_offset(state, table_name, processed)

        if progress_callback:
            progress_callback(table_name, processed, inserted)

    resume_module.mark_table_done(state, table_name)

    actual_count = collection.count_documents({})
    import_logger.info(
        "اكتمل استيراد %s: قراءة %s سجل، إدخال %s سجل في هذا التشغيل، العدد الفعلي الحالي = %s",
        table_name, processed, total_inserted, actual_count,
    )
    if actual_count == 0 and processed > 0:
        import_logger.info(
            "*** تحذير خطير: الجدول %s قُرئ منه %s سجل لكنه فارغ فعلياً في MongoDB! "
            "راجع logs/errors.log فوراً. ***",
            table_name, processed,
        )
    return processed


def create_index_for_table(db, table_name, primary_key):
    """إنشاء فهرس فريد على المفتاح الأساسي إن وُجد (بعد الاستيراد فقط)."""
    if not primary_key:
        return
    try:
        db[table_name].create_index(primary_key, unique=True, name=f"{primary_key}_unique")
        import_logger.info("تم إنشاء فهرس فريد على %s.%s", table_name, primary_key)
    except Exception as exc:
        error_logger.error("تعذر إنشاء فهرس فريد على %s.%s: %s", table_name, primary_key, exc)