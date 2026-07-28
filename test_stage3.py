# -*- coding: utf-8 -*-
"""
test_stage3.py
--------------
اختبار شامل لآلية الاستكمال (resume.py).
شغّل هذا الملف مباشرة بعد إنشاء resume.py:

    python test_stage3.py
"""

import os

import config
import resume

# 0) تنظيف أي resume.json قديم قبل بدء الاختبار
resume.reset_resume()
assert not os.path.exists(config.RESUME_FILE), "resume.json لم يُحذف بشكل صحيح"

# 1) التحميل الأول يجب أن يعطي الحالة الافتراضية (بداية جديدة)
state = resume.load_resume()
assert state["governorates"]["done"] is False
assert state["regions"]["done"] is False
assert state["people"]["offset"] == 0
assert state["people"]["done"] is False
print("الخطوة 1: الحالة الافتراضية صحيحة عند عدم وجود resume.json")

# 2) تعليم governorates بأنها اكتملت، والتأكد أن هذا يُحفظ فعلياً على القرص
state = resume.mark_stage_done(state, "governorates")
assert os.path.exists(config.RESUME_FILE), "لم يتم إنشاء resume.json بعد أول حفظ"
reloaded = resume.load_resume()
assert reloaded["governorates"]["done"] is True
print("الخطوة 2: تعليم governorates كمكتملة تم حفظه بنجاح في resume.json")

# 3) تحديث offset جدول الأشخاص عدة مرات (محاكاة تقدم الاستيراد دفعة بعد دفعة)
state = resume.update_people_offset(state, 20000)
state = resume.update_people_offset(state, 40000)
reloaded = resume.load_resume()
assert reloaded["people"]["offset"] == 40000, "لم يتم حفظ آخر offset بشكل صحيح"
print("الخطوة 3: تحديث offset جدول الأشخاص يعمل ويُحفظ بشكل صحيح (آخر قيمة = 40000)")

# 4) محاكاة انقطاع البرنامج ثم إعادة التشغيل: يجب أن يبدأ من offset=40000 وليس من الصفر
fresh_state = resume.load_resume()
assert resume.get_people_offset(fresh_state) == 40000
assert resume.is_stage_done(fresh_state, "governorates") is True
assert resume.is_stage_done(fresh_state, "regions") is False
print("الخطوة 4: محاكاة إعادة التشغيل بعد انقطاع -> تم الاستكمال من offset=40000 بنجاح")

# 5) اختبار ملف تالف (JSON غير صالح) -> يجب ألا يتوقف البرنامج، بل يبدأ حالة افتراضية آمنة
with open(config.RESUME_FILE, "w", encoding="utf-8") as f:
    f.write("{this is not valid json")
safe_state = resume.load_resume()
assert safe_state["people"]["offset"] == 0
print("الخطوة 5: التعامل مع ملف resume.json تالف يعمل بأمان (رجوع لحالة افتراضية)")

# 6) إعادة الضبط الكامل (reset_resume) للبدء من الصفر عند إعادة بناء القاعدة بالكامل
resume.reset_resume()
assert not os.path.exists(config.RESUME_FILE)
print("الخطوة 6: reset_resume() يحذف resume.json بنجاح")

print()
print("OK: resume.py يعمل بنجاح بجميع الحالات (بداية جديدة، حفظ تقدم، استكمال، ملف تالف، إعادة ضبط)")