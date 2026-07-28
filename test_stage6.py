# -*- coding: utf-8 -*-
"""
test_stage6.py
--------------
اختبار config.py و resume.py بعد إعادة الهيكلة العامة (بدون أي جدول محدد سلفاً).

شغّل هذا الملف بعد تحديث config.py و resume.py:
    python test_stage6.py
"""

import os

import config
import resume

# ---- config.py ----
assert config.DEFAULT_MONGO_URI == "mongodb://localhost:27017"
assert config.BATCH_SIZE == 20000
assert "MSys" in config.SYSTEM_TABLE_PREFIXES
assert not hasattr(config, "TABLE_PEOPLE"), "لا يجب أن يبقى أي اسم جدول قديم في config.py"
assert not hasattr(config, "PEOPLE_FIELD_MAPPING"), "لا يجب أن يبقى أي Mapping قديم في config.py"
print("الخطوة 1: config.py أصبح عاماً بالكامل بدون أي أسماء جداول أو Mapping قديم")

# ---- resume.py: بداية جديدة مع جداول عشوائية بأسماء مختلفة تماماً ----
resume.reset_resume()
state = resume.load_resume()
assert resume.is_fresh_state(state) is True
print("الخطوة 2: الحالة الافتراضية فارغة تماماً (لا توجد أي جداول مسبقة)")

# جدول عربي، وجدول إنجليزي، وجدول بأرقام - للتأكد أن الأداة عامة فعلاً
random_tables = ["Sgaza", "بيانات_الموظفين", "Orders2024", "جدول أسماء غريبة !@#"]

for t in random_tables:
    assert resume.get_table_offset(state, t) == 0
    assert resume.is_table_done(state, t) is False

state = resume.update_table_offset(state, random_tables[0], 5000)
state = resume.update_table_offset(state, random_tables[1], 300)
state = resume.mark_table_done(state, random_tables[2])

reloaded = resume.load_resume()
assert resume.get_table_offset(reloaded, random_tables[0]) == 5000
assert resume.get_table_offset(reloaded, random_tables[1]) == 300
assert resume.is_table_done(reloaded, random_tables[2]) is True
assert resume.is_table_done(reloaded, random_tables[3]) is False
assert resume.is_fresh_state(reloaded) is False
print("الخطوة 3: تتبع التقدم يعمل بشكل صحيح لأي عدد وأي أسماء جداول (عربي/إنجليزي/رموز)")

resume.reset_resume()
assert not os.path.exists(config.RESUME_FILE)
print("الخطوة 4: reset_resume() يعمل بشكل صحيح")

print()
print("OK: config.py و resume.py أصبحا عامّين بالكامل ويعملان بنجاح مع أي جداول")