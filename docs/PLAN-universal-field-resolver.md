# خطة التنفيذ: Universal Constrained-Field Resolver (L2)

> الهدف: نظام يكتب **أي قيمة ممكنة** في **أي حقل** عبر **أي باكند** بأمان — يكتشف نوع الحقل من الـ schema الحيّ، يحلّ القيمة البشرية إلى ما يقبله الحقل فعلاً (مفتاح enum / id مرجع / شكل مُنسَّق)، يتحقّق read-after-write، ويفشل بصراحة (fail-closed) بدل الكتابة الصامتة الخاطئة. هذا تعميم إصلاح F1 (verified كاذب) وF2 (الإسقاط الصامت) من "حقل واحد" إلى "كل الحقول".

---

## 0. المواصفات التي نبني عليها (مجمّعة)

### أ. تصنيف المعايير العالمية (من البحث) — النواة السبعة
كل نوع حقل في HTML5 / JSON Schema / OpenAPI / SQL-ISO / Odoo / Django / Protobuf يقع في ستة دلاء. النواة غير القابلة للاختزال (في كل المعايير):
`string · number/integer · boolean · date/datetime · enum/selection · reference/FK · array/multi`

| دلو | المعنى | استراتيجية الحلّ |
|---|---|---|
| **A. scalar حرّ** | text/number/bool | coercion فقط |
| **B. enum/selection** | قائمة ثابتة **على الحقل** | اجلب القيم → طابِق المصطلح → المفتاح المخزَّن |
| **C. مرجع علائقي** | يشير لسجل في موديل آخر (m2o/FK) | ابحث الموديل المرجعي بالاسم → record id |
| **D. متعدّد القيم** | m2m/array/tags | حُلّ كل عنصر (B/C) + cardinality |
| **E. scalar مُنسَّق** | date/email/url/tel/uuid/currency/geo | طبِّع للشكل الصارم، بلا بحث |
| **F. خاص** | binary/file/json/compute/readonly | ارفض المحسوب؛ مرّر/تيار للباقي |

### ب. مواصفات NIL في الكود (ما عندنا الآن)
- **الـ dispatch المُعلَن** `WriteVerb.op` (create/update/upsert/method/delete) — [odoo/translate.py](../adapters/odoo-crm-nil-adapter/src/odoo_crm_nil_adapter/translate.py).
- **قراءة الشكل** `SystemClient.schema(target)` يقرأ `fields_get` بـ `["string","type","required"]` فقط — [odoo/system.py:163](../adapters/odoo-crm-nil-adapter/src/odoo_crm_nil_adapter/system.py). و`describe` يكشف `targets{exists, fields:[{name,type,required}]}`.
- **التحقّق الحقلي** `_verify_and_diff` → `result.ssot.fields = [{field, before, requested, after, verified}]` (شُحن).
- **الـ resolver الحالي (L1)** `_resolve_reference` — **C فقط، يدوي** عبر `WriteVerb.references=(("country","country_id","res.country"),)`. [odoo/edge.py:115].
- **fail-closed** موجود: UNRESOLVED/AMBIGUOUS → SystemError → failed_terminal، بلا كتابة.
- **template drift** (دَيْن): القالب [_templates.py](../src/nilscript/cli/scaffold/_templates.py) ينقصه: resolver المرجع، upsert/dedup، before-image، op="method"، did_read، dispatch مُعلَن. وpocketbase ينقصه `ssot.fields`.

### الفجوة المؤكَّدة
عندنا **C يدوياً فقط**. ناقص: **B (selection — مثال "متاح")، D (multi)، E (تطبيع)**، والاكتشاف **التلقائي من الـ schema** بدل الإعلان لكل حقل.

---

## 1. المعمارية — أين يعيش كل جزء

ثلاث طبقات، صارمة:

| الطبقة | تملك | مكان |
|---|---|---|
| **المعيار/العقد** | الانضباط: "كل حقل مقيَّد يُحَل ضد قيمه الحيّة، لا يُكتَب خاماً، fail-closed"؛ وشكل `field_meta` | spec/docs + اختبارات المطابقة |
| **الـ edge العام** | الـ resolver المُوجَّه بالـ schema: يصنّف A–F ويوزّع؛ التحقّق؛ الفشل | `_templates.py` (يُولَّد لكل أدابتر) |
| **الأدابتر (primitives)** | إثراء `schema()` بالـ metadata؛ تنفيذ البحث/التطبيع الخاص بالباكند | `system.py` لكل أدابتر |

المبدأ: **الآلية تُعرَّف مرة** (القالب)، **التعداد primitive لكل باكند** (system.py)، **الإعلان اختياري للتجاوز** (translate.py).

---

## 2. الـ field_meta — العقد الذي يقود كل شيء

نوسّع `schema()` (وdescribe) ليُرجع لكل حقل، بدل `{name,type,required}`:

```python
{
  "name": "country_id",
  "type": "many2one",          # النوع الخام من الباكند
  "bucket": "reference",        # A/enum/reference/multi/format/special — يحسبه الأدابتر أو الـ edge
  "required": false,
  "readonly": false,            # F: لا يُكتَب
  "options": null,              # B: [{value, label, label_ar?}] من fields_get.selection
  "relation": "res.country",    # C: الموديل المرجعي
  "search_fields": ["name","code"],  # C: حقول البحث المرشَّحة
  "format": null,               # E: date|email|uuid|... (من type/format)
  "multi": false                # D: m2m/array
}
```

تعيين النوع الخام → bucket (جدول واحد في الـ edge العام، يغطّي أسماء كل المعايير من §0).

---

## 3. خوارزمية الحلّ (في الـ edge العام، لكل حقل يُكتَب)

```
لكل (field, value) في native:
  meta = field_meta[field]
  switch meta.bucket:
    A scalar   → coerce(value, type)                      # "5"→5
    E format   → normalize(value, meta.format)            # ISO-8601 / E.164 / hex / uuid
    B enum     → resolve_option(meta.options, value)      # "متاح" → "available"
    C reference→ resolve_reference(meta.relation, meta.search_fields, value)  # "قطر" → 190
    D multi    → [resolve عنصراً عنصراً] + تحقّق العدد
    F special  → readonly/compute ⇒ ارفض؛ binary/json ⇒ مرّر كما هو
  أي عدم تطابق ⇒ ارفع UNRESOLVED/AMBIGUOUS  (لا كتابة)
ثم: اكتب native المحلولة → read-after-write → ssot.fields (موجود)
```

`resolve_option` و`resolve_reference` يطابقان: id/مفتاح خام يمرّ؛ رمز قصير؛ تطابق اسم تام (case-insensitive) يُفضَّل؛ صفر→UNRESOLVED، متعدّد→AMBIGUOUS.

---

## 4. التغييرات الملموسة بالملف

### P1 — إثراء الـ schema (آمن، قراءة فقط)
- **system.py** (odoo): `schema()` يطلب `fields_get` بـ `["string","type","required","selection","relation","readonly"]`، ويبني `field_meta` أعلاه. (selection→options، relation→reference + search_fields افتراضية `["name","code","display_name"]`.)
- **edge `describe`**: يكشف `field_meta` الكامل لكل target → الوكيل/الواجهة يرى القيم المتاحة (يغلق ثغرة "كيف أرى القائمة" + الـ 404).
- اختبار: describe يُرجع options لحقل selection وrelation لحقل m2o.

### P2 — الـ resolver العام B + C (القلب)
- **edge** (القالب أولاً، ثم odoo): دالة `resolve_field(client, meta, value)` تتفرّع بالـ bucket. تستبدل حلقة `verb.references` اليدوية: الآن **كل حقل يُكتَب** يُحَل تلقائياً حسب `field_meta` — بلا إعلان.
- `WriteVerb.references`/`supported_args` تبقى **تجاوزات اختيارية** (لو الأدابتر يريد قسر حقل أو search_fields مخصّصة).
- يعمّم `_resolve_reference` الحالي ويضيف `resolve_option` (selection).
- اختبارات: "متاح"→مفتاح selection؛ "قطر"→id؛ unresolved→failed_terminal بلا كتابة؛ ssot.fields يُظهر before→after.

### P3 — D (multi) + E (تطبيع)
- D: m2m/one2many — حُلّ كل عنصر، صياغة أوامر الباكند (Odoo `(6,0,[ids])`).
- E: `normalize()` للـ date/datetime/email/url/tel(E.164)/uuid/monetary. fail على شكل غير مطابق.
- اختبارات لكل نوع.

### P4 — إصلاح template drift (توحيد)
- ارفع القدرات الستّ المحبوسة + الـ resolver الجديد + `field_meta` إلى **_templates.py**.
- وحّد `WriteVerb` الكامل في القالب.
- أعِد توليد **pocketbase demo + example** → يلتقطان كل شيء (وينتهي تراجع `ssot.fields`).
- اختبار: scaffold لأدابتر جديد يُولّد مع الـ resolver العام جاهزاً.

### P5 — العقد + المطابقة كمواصفة
- وثّق الانضباط وشكل `field_meta` في docs/spec.
- اختبارات مطابقة تعمل ضد **FakeSystem** (يدعم selection/relation) — تصبح المواصفة التنفيذية.

---

## 5. الترتيب والتسليم (كل مرحلة قابلة للشحن وحدها)

| # | المخرج | المخاطرة | يفتح |
|---|---|---|---|
| **P1** | field_meta + describe يكشف القيم | منخفضة (قراءة) | رؤية القوائم؛ يغلق 404 |
| **P2** | resolver B+C تلقائي schema-driven | متوسطة (مسار كتابة) | "متاح" + الدولة بلا إعلان |
| **P3** | D + E | متوسطة | m2m/tags + تطبيع |
| **P4** | رفع للقالب + إعادة توليد | متوسطة | الكل لكل الأدابترات |
| **P5** | spec + conformance | منخفضة | المعيار موثّق |

كل مرحلة: TDD (RED→GREEN)، PR منفصل، squash-merge، ثم نشر.

---

## 6. غير-أهداف وضوابط (مهمّة)
- **لا نكتب F المحسوب/القراءة-فقط** — نرفضه صراحةً (ليس عطلاً، حماية).
- **لا نخمّن عند الغموض** — AMBIGUOUS يطلب توضيحاً، لا يختار.
- **لا نثق براية verified** — التحقّق دائماً قراءة فعلية من SSOT (ssot.fields).
- **لا نكسر استقلال الأدابتر على PyPI** — التوحيد عبر **توليد من قالب واحد**, لا اعتماد مكتبة مجاورة.
- **الكيرنل يبقى محايداً** — لا يعدّد القيم؛ يملك الانضباط فقط. التعداد primitive في الأدابتر.

---

## 7. معيار النجاح
الوكيل يقول طبيعياً ("اجعله متاح" / "بدر قطري" / "وسمه VIP و2 آخرين") فالنظام:
1. يكتشف نوع كل حقل من الـ schema،
2. يجلب القيم المتاحة ويحلّ المصطلح للقيمة الفعلية،
3. يكتب ويتحقّق حقلاً بحقل،
4. يفشل بصراحة لو لم يطابق — بلا كتابة صامتة خاطئة.

عبر **أي باكند**، بـ resolver **واحد** معرَّف **مرة**.
