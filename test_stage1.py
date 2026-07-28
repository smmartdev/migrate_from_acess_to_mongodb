# -*- coding: utf-8 -*-
"""
test_stage1.py
--------------
اختبار سريع للتأكد من أن config.py يعمل بشكل صحيح.
شغّل هذا الملف مباشرة بعد إنشاء config.py:

    python test_stage1.py
"""

import config

print("MONGO_URI       =", config.MONGO_URI)
print("MONGO_DB_NAME   =", config.MONGO_DB_NAME)
print("BATCH_SIZE      =", config.BATCH_SIZE)
print("TABLE_PEOPLE    =", config.TABLE_PEOPLE)
print("PEOPLE_ACCESS_COLUMNS =", config.PEOPLE_ACCESS_COLUMNS)
print("LOGS_DIR        =", config.LOGS_DIR)
print()
print("OK: config.py تم تحميله بنجاح بدون أي أخطاء")