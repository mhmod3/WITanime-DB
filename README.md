# WITanime DB

قاعدة بيانات مفتوحة المصدر لتحديث روابط البث والتحميل لحلقات الأنمي. تُخزّن البيانات في ملفات `JSON` منفصلة لكل أنمي، مع تحديث دوري آلي لضمان صلاحية الروابط.

## هيكل المشروع

    WITanime-DB/
    ├── data/
    │   ├── Gamers.json
    │   ├── AttackOnTitan.json
    │   └── ...

## نموذج ملف JSON

    {
        "Shingeki no Kyojin": {
            "anime_url": "https://witanime.you/anime/shingeki-no-kyojin/",
            "type": "TV",
            "mal_id": "16498",
            "1": {
                "streaming_links": [
                    "https://yonaplay.net/embed.php?id=12902",
                    "https://hgcloud.to/e/0kd9wfyzafb9"
                ],
                "downloading_links": [
                    "https://www.mediafire.com/file/yihxl43a65hjiqp/%5BWitanime.com%5D_SNK_EP_01_BD-FHD.mp4/file",
                    "https://workupload.com/file/qBWfFcaC9h6"
                ]
            },
            "2": {
                "streaming_links": [
                    "https://yonaplay.net/embed.php?id=12903",
                    "https://hgcloud.to/e/lsik0grdlrmi"
                ],
                "downloading_links": [
                    "https://www.mediafire.com/file/c9pmbsqn6a2afvi/%5BWitanime.com%5D_SNK_EP_02_BD-FHD.mp4/file",
                    "https://workupload.com/file/nhJ4kmuyUrx"
                ]
            }
        }
    }

- **anime_url**: الرابط الأساسي للأنمي على المصدر.
- **type**: نوع العرض (TV, Movie, OVA, إلخ).
- **mal_id**: المعرف الرسمي من MyAnimeList.
- **أرقام الحلقات (1, 2, ...)**: تحتوي كل حلقة على قائمتين للروابط (بث وتحميل).

## آلية التحديث الدوري
  
 ستحدث الروابط بشكل دوري كل 24 ساعة.

---

# الأسئلة الشائعة (FAQ)

<details>
<summary><strong>1. ما هو الغرض الأساسي من المشروع؟</strong></summary>

توفير مصدر موثوق ومُحدّث تلقائيًا لروابط مشاهدة وتحميل حلقات الأنمي، لتسهيل دمجها في تطبيقات الطرف الثالث أو مواقع المعجبين.
</details>



<details>
<summary><strong>2. كيف أبلغ عن رابط معطل أو خطأ في التصنيف؟</strong></summary>

افتح Issue في GitHub مع ذكر اسم الأنمي و `mal_id`، وسيُعالَج خلال دورة التحديث التالية (أقل من ٢٤ ساعة).
</details>

<details>
<summary><strong>3.‫هل استعملت AI في كتابة ملف .md هذه ؟ ‬</strong></summary>

نعم لاني مكسل الصراحة.
</details>

---  
**ملاحظة**: جميع الروابط مستوردة من مصادر عامة، المشروع لا يستضيف اي شيء على خوادمه الخاصة المشروع يعمل كمحرك بحث, اذا كانت لديك مشكله اذهب الى المواقع التي تستضيف الملف وقدم شكواك.
