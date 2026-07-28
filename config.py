# -*- coding: utf-8 -*-
"""
config.py
---------
إعدادات عامة فقط. لا يحتوي هذا الملف على أي اسم جدول أو أي Mapping محدد مسبقاً،
لأن الأداة أصبحت تكتشف كل الجداول والأعمدة تلقائياً من ملف Access المُمرَّر.

يمكن تجاوز أي قيمة افتراضية هنا عبر معاملات سطر الأوامر في migrate.py
(مثل --access-file و --mongo-db) أو عبر متغيرات البيئة الموضحة أدناه.
"""

import os

# =========================================================
# 1) مسارات المشروع
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOGS_DIR = os.path.join(BASE_DIR, "logs")
IMPORT_LOG_FILE = os.path.join(LOGS_DIR, "import.log")
ERROR_LOG_FILE = os.path.join(LOGS_DIR, "errors.log")

RESUME_FILE = os.path.join(BASE_DIR, "resume.json")

# =========================================================
# 2) القيم الافتراضية للاتصال (قابلة للتجاوز عبر --access-file / --mongo-db)
# =========================================================
DEFAULT_ACCESS_DB_PATH = os.environ.get("ACCESS_DB_PATH", r"C:\path\to\database.accdb")
DEFAULT_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
# لا قيمة افتراضية لاسم قاعدة البيانات عمداً: يجب تحديدها صراحة لتفادي الكتابة بالخطأ فوق قاعدة أخرى
DEFAULT_MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "")

# =========================================================
# 3) إعدادات الأداء
# =========================================================
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", 20000))
BATCH_SIZE_MAX = 50000

# =========================================================
# 4) جداول يتم تجاهلها دائماً (جداول نظام Access الداخلية)
# =========================================================
SYSTEM_TABLE_PREFIXES = ("MSys", "~")