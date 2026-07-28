# -*- coding: utf-8 -*-
r"""
migrate.py
----------
الملف الرئيسي: يرحّل كل الجداول تلقائياً من ملف Access المحدد إلى قاعدة
بيانات MongoDB المحددة، دون الحاجة لتعريف أي جدول أو Mapping مسبقاً.

طريقة الاستخدام:
    python migrate.py --access-file "C:\path\to\database.accdb" --mongo-db sijil_sokani
    python migrate.py --access-file "C:\path\to\database.accdb" --mongo-db sijil_sokani --fresh
    python migrate.py --access-file "..." --mongo-db "..." --mongo-uri "mongodb://localhost:27017"

يمكن أيضاً ضبط القيم الافتراضية عبر متغيرات البيئة (بدل تكرار المعاملات في كل مرة):
    ACCESS_DB_PATH, MONGO_URI, MONGO_DB_NAME (راجع config.py)
"""

import argparse
import time

from tqdm import tqdm

import config
import importer
import resume
from logger import import_logger, error_logger


def discover_schema(access_conn):
    """اكتشاف كل الجداول ومفاتيحها الأساسية دفعة واحدة في بداية العملية."""
    tables = importer.list_tables(access_conn)
    schema = {}
    for table_name in tables:
        schema[table_name] = importer.get_primary_key(access_conn, table_name)
    return schema


def run_migration(access_conn, db, fresh=False, show_progress=True):
    """تنفيذ الترحيل الكامل لكل الجداول المكتشَفة. تُرجع dict بملخص النتائج."""
    import_logger.info("=" * 60)
    import_logger.info("بدء عملية الترحيل التلقائي (كل الجداول)")
    import_logger.info("=" * 60)

    if fresh:
        resume.reset_resume()
        import_logger.info("تم تفعيل --fresh: تجاهل أي تقدم سابق محفوظ")

    state = resume.load_resume()
    fresh_start = resume.is_fresh_state(state)

    schema = discover_schema(access_conn)
    table_names = list(schema.keys())
    import_logger.info("تم اكتشاف %s جدول في Access: %s", len(table_names), "، ".join(table_names))

    if fresh_start:
        import_logger.info("بداية جديدة بالكامل -> حذف كل Collections المطابقة لأسماء الجداول")
        for table_name in table_names:
            importer.drop_collection(db, table_name)
    else:
        import_logger.info("تم اكتشاف تقدم سابق غير مكتمل -> استكمال العمل من آخر نقطة")

    start_time = time.time()
    results = {}

    for table_name in table_names:
        primary_key = schema[table_name]
        already_done = resume.is_table_done(state, table_name)

        total_estimate = None
        if not already_done:
            total_estimate = importer.count_table_rows(access_conn, table_name)

        progress_bar = None
        if show_progress and not already_done:
            progress_bar = tqdm(
                total=total_estimate,
                initial=resume.get_table_offset(state, table_name),
                unit=" سجل",
                desc=f"استيراد {table_name}",
            )

        def progress_callback(tbl, processed, inserted, _bar=progress_bar):
            if _bar is not None:
                _bar.n = processed
                _bar.refresh()

        try:
            processed = importer.import_table(
                access_conn, db, table_name, state, resume,
                primary_key=primary_key, progress_callback=progress_callback,
            )
            results[table_name] = processed
        finally:
            if progress_bar is not None:
                progress_bar.close()

    import_logger.info("--- إنشاء الفهارس (المفتاح الأساسي لكل جدول إن وُجد) ---")
    for table_name in table_names:
        importer.create_index_for_table(db, table_name, schema[table_name])

    elapsed = time.time() - start_time
    import_logger.info("اكتملت عملية الترحيل بنجاح خلال %.1f ثانية. ملخص الجداول: %s", elapsed, results)
    import_logger.info("=" * 60)

    return {"tables": results, "elapsed_seconds": elapsed}


def main():
    parser = argparse.ArgumentParser(
        description="أداة ترحيل تلقائية لكل الجداول من Microsoft Access إلى MongoDB"
    )
    parser.add_argument("--access-file", default=config.DEFAULT_ACCESS_DB_PATH,
                         help="المسار الكامل لملف Access (.accdb أو .mdb)")
    parser.add_argument("--mongo-uri", default=config.DEFAULT_MONGO_URI,
                         help="سلسلة اتصال MongoDB (افتراضياً mongodb://localhost:27017)")
    parser.add_argument("--mongo-db", default=config.DEFAULT_MONGO_DB_NAME,
                         help="اسم قاعدة بيانات MongoDB الهدف (إجباري)")
    parser.add_argument("--fresh", action="store_true",
                         help="تجاهل أي تقدم سابق والبدء من الصفر (حذف كل البيانات القديمة)")
    args = parser.parse_args()

    if not args.mongo_db:
        print("خطأ: يجب تحديد اسم قاعدة بيانات MongoDB عبر --mongo-db (أو متغير البيئة MONGO_DB_NAME)")
        return

    try:
        access_conn = importer.get_access_connection(args.access_file)
    except Exception as exc:
        error_logger.error("فشل الاتصال بقاعدة بيانات Access (%s): %s", args.access_file, exc)
        print("تعذر الاتصال بقاعدة بيانات Access. راجع migration/logs/errors.log للتفاصيل.")
        return

    try:
        mongo_client = importer.get_mongo_client(args.mongo_uri)
        db = importer.get_mongo_db(args.mongo_db, client=mongo_client)
    except Exception as exc:
        error_logger.error("فشل الاتصال بـ MongoDB: %s", exc)
        print("تعذر الاتصال بـ MongoDB. تأكد أن الخدمة تعمل على العنوان المحدد.")
        access_conn.close()
        return

    try:
        run_migration(access_conn, db, fresh=args.fresh, show_progress=True)
    except KeyboardInterrupt:
        import_logger.info("تم إيقاف البرنامج يدوياً (Ctrl+C). التقدم محفوظ، أعد التشغيل للاستكمال.")
    except Exception as exc:
        error_logger.error("خطأ غير متوقع أوقف عملية الترحيل: %s", exc)
        import_logger.info("توقفت العملية بسبب خطأ. التقدم محفوظ، راجع logs/errors.log ثم أعد التشغيل.")
    finally:
        access_conn.close()


if __name__ == "__main__":
    main()