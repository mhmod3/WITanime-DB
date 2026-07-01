# WITanime DB

السلام عليكم ورحمة الله وبركاته.
<details>
<summary><strong> ما هذه ؟</strong></summary>

قاعدة بيانات مفتوحة المصدر لتحديث روابط البث والتحميل لحلقات الأنمي. تُخزّن البيانات في ملفات `JSON` منفصلة لكل أنمي، مع تحديث دوري آلي لضمان صلاحية الروابط.
</details>

## نموذج ملف JSON

    {
        "Shingeki no Kyojin": {
            "anime_url": "https://whatever.whatever/anime/shingeki-no-kyojin/",
            "type": "TV",
            "mal_id": "16498",
            "1": {
                "streaming_links": [
                    {"url": "https://...", "quality": "FHD"},
                    {"url": "https://...", "quality": "HD"}
                ],
                "downloading_links": [
                    {"url": "https://...", "quality": "FHD"},
                    {"url": "https://...", "quality": "SD"}
                ]
            },
            "2": {
                "streaming_links": [
                    {"url": "https://...", "quality": "unknown"}
                ],
                "downloading_links": []
            }
        }
    }

- **anime_url**: الرابط الأساسي للأنمي على المصدر.
- **type**: نوع العرض (TV, Movie, OVA, إلخ).
- **mal_id**: المعرف الرسمي من MyAnimeList.
- **أرقام الحلقات (1, 2, ...)**: تحتوي كل حلقة على قائمتين للروابط (بث وتحميل)، كل رابط يحتوي على:
  - **url**: رابط الفيديو أو التحميل.
  - **quality**: جودة الفيديو (FHD, HD, SD, multi, أو unknown في حال عدم توفرها).

## آلية التحديث الدوري
  
 ستحدث الروابط بشكل دوري كل 24 ساعة.

---

# الأسئلة الشائعة (FAQ)

<details>
<summary><strong>1. ما هو الغرض الأساسي من المشروع؟</strong></summary>

توفير مصدر موثوق ومُحدّث تلقائيًا لروابط مشاهدة وتحميل حلقات الأنمي، لتسهيل دمجها في تطبيقات الطرف الثالث أو للاستخدام الشخصي.
</details>



<details>
<summary><strong>2. كيف أبلغ عن رابط معطل أو خطأ في التصنيف؟</strong></summary>

افتح Issue في GitHub مع ذكر اسم الأنمي و `mal_id`، وسيُعالَج خلال دورة التحديث التالية (أقل من ٢٤ ساعة).
</details>

<details>
<summary><strong>3. كيف يمكن استعمال هذه المشروع </strong></summary>

فقط اذهب الى [Releases](https://github.com/mhmod3/WITanime-DB/releases) وبعدها حمل الملف المضغوط وستصبح عندك قاعدة البيانات متوفرة.
</details>

<details>
<summary><strong>4. ‫لماذا لا توفر الملفات التي تعمل بها Scrap للموقع ؟‬ </strong></summary>

‫وذالك لان من الممكن ان مالك الموقع يكتشف كيفية عمل كود الـ Scrap ويغير من طريقة عمل الموقع‬
</details>

<details>
<summary><strong>5. ‫من اين احصل على ملفات الـ Scraping ؟‬ </strong></summary>

‫‫تواصل معي على [تيليجرام‬‬](http://t.me/liM7mod)
</details>


<details>
<summary><strong>6.‫هل استعملت AI في كتابة ملف .md هذه ؟ ‬</strong></summary>

نعم لاني مكسل الصراحة.
</details>

---  
**ملاحظة**: جميع الروابط مستوردة من مصادر عامة، المشروع لا يستضيف اي شيء على خوادمه الخاصة المشروع يعمل كمحرك بحث, اذا كانت لديك مشكله اذهب الى المواقع التي تستضيف الملف وقدم شكواك.
---
اذا استفدت من المشروع ولو بشكل بسيط لا تنسى دعمي بنجمة (⭐)
