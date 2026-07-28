# -*- coding: utf-8 -*-
"""
logger.py
---------
نظام تسجيل الأحداث (Logging) الموحّد للمشروع.

يوفر هذا الملف Logger جاهزين للاستخدام مباشرة من أي ملف آخر:

    from logger import import_logger, error_logger

    import_logger.info("بدء استيراد جدول الأشخاص")
    error_logger.error("فشل إدخال السجل رقم 123: duplicate key")

- import_logger  -> يكتب إلى logs/import.log وإلى الشاشة أيضاً (مراحل التنفيذ، عدد السجلات، التقدم)
- error_logger   -> يكتب إلى logs/errors.log فقط (الأخطاء والاستثناءات)
"""

import logging
import os

import config


def _ensure_logs_dir():
    """التأكد من وجود مجلد logs قبل إنشاء أي ملف داخله."""
    os.makedirs(config.LOGS_DIR, exist_ok=True)


def _build_logger(name, log_file, level, also_console):
    """
    دالة داخلية مشتركة لبناء أي Logger (تفادياً لتكرار الكود).
    تتأكد أيضاً من عدم إضافة نفس الـ Handlers أكثر من مرة إذا تم
    استدعاء الدالة أكثر من مرة (مهم عند إعادة تحميل الوحدة في بعض البيئات).
    """
    _ensure_logs_dir()

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    if also_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    return logger


def get_import_logger():
    """Logger عام لمراحل التنفيذ والتقدم -> logs/import.log + الشاشة."""
    return _build_logger(
        name="import_logger",
        log_file=config.IMPORT_LOG_FILE,
        level=logging.INFO,
        also_console=True,
    )


def get_error_logger():
    """Logger مخصص للأخطاء فقط -> logs/errors.log (بدون شاشة لتفادي الإزعاج)."""
    return _build_logger(
        name="error_logger",
        log_file=config.ERROR_LOG_FILE,
        level=logging.ERROR,
        also_console=False,
    )


# جاهزين للاستيراد المباشر من أي ملف آخر في المشروع
import_logger = get_import_logger()
error_logger = get_error_logger()