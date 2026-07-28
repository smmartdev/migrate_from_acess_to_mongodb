# -*- coding: utf-8 -*-
"""
test_stage2.py
--------------
اختبار سريع للتأكد من أن logger.py يعمل بشكل صحيح.
شغّل هذا الملف مباشرة بعد إنشاء logger.py:

    python test_stage2.py

بعد التشغيل تحقق يدوياً من وجود الملفين التاليين وأن بهما محتوى:
    logs/import.log
    logs/errors.log
"""

import os

import config
from logger import import_logger, error_logger

import_logger.info("رسالة تجريبية 1: بدء اختبار نظام التسجيل")
import_logger.info("رسالة تجريبية 2: تم استيراد 100 سجل بنجاح")
error_logger.error("رسالة تجريبية 3: هذا خطأ وهمي لأغراض الاختبار فقط")

assert os.path.exists(config.IMPORT_LOG_FILE), "لم يتم إنشاء ملف import.log"
assert os.path.exists(config.ERROR_LOG_FILE), "لم يتم إنشاء ملف errors.log"

with open(config.IMPORT_LOG_FILE, encoding="utf-8") as f:
    import_content = f.read()

with open(config.ERROR_LOG_FILE, encoding="utf-8") as f:
    error_content = f.read()

assert "رسالة تجريبية 1" in import_content, "المحتوى المتوقع غير موجود في import.log"
assert "رسالة تجريبية 3" in error_content, "المحتوى المتوقع غير موجود في errors.log"

print()
print("OK: logger.py يعمل بنجاح، وتم إنشاء logs/import.log و logs/errors.log بالمحتوى الصحيح")