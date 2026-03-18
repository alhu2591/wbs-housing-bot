"""
AI-powered listing analyzer — Claude Haiku.
Semaphore-limited (max 3 concurrent), with regex fallback.
"""
import asyncio
import json
import logging
import os

import httpx
from filters.wbs_filter import enrich

logger     = logging.getLogger(__name__)
_semaphore = asyncio.Semaphore(3)   # Max 3 concurrent AI calls

SYSTEM_PROMPT = """أنت محلل إعلانات شقق ألمانية متخصص.
مهمتك: استخراج المعلومات من إعلان شقة وإعادتها كـ JSON فقط — بدون أي نص إضافي.

القواعد الصارمة:
- القيم الناقصة → null (لا تخمن)
- price: رقم بالكامل بدون € مثل 520 (الإيجار الشامل Warmmiete إذا وُجد)
- rooms: رقم عشري مثل 2 أو 2.5
- size_m2: مساحة بالمتر المربع كرقم فقط
- floor: "الطابق الأرضي" أو "الطابق 1..10" أو "الطابق العلوي" أو null
- is_urgent: true فقط عند وجود "ab sofort"/"sofort frei"/"sofort verfügbar"
- available_from: تاريخ بالعربية مثل "أبريل 2025" أو "فوري" أو null
- features: قائمة من هذه القيم الثابتة فقط عند ذكرها صراحةً:
  ["بلكونة","تراس","حديقة","مصعد","مطبخ مجهز","مخزن","موقف سيارة","بدون عوائق","بناء جديد","أول سكن","غسالة","حمام إضافي"]
- apply_url: رابط التقديم المباشر إذا كان مختلفاً عن رابط الإعلان (نادراً ما يوجد)
- district: الحي بالألمانية مثل "Spandau" أو "Mitte" (من العنوان أو الوصف)
- summary_ar: جملة واحدة بالعربية الفصيحة تصف الشقة باختصار مفيد

تنسيق الإخراج — JSON فقط بلا أي نص آخر:
{"price":520,"rooms":2,"size_m2":62,"floor":"الطابق 3","is_urgent":true,"available_from":"فوري","features":["بلكونة","مصعد"],"district":"Spandau","apply_url":null,"summary_ar":"شقة غرفتين مع بلكونة ومصعد"}"""


async def ai_analyze(listing: dict) -> dict:
    """Enrich listing via Claude Haiku. Falls back to regex on any failure."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return enrich(listing)

    raw_text = (
        f"العنوان: {listing.get('title','')}\n"
        f"الوصف: {listing.get('description','')}\n"
        f"الموقع: {listing.get('location','')}\n"
        f"السعر الأولي: {listing.get('price','')}\n"
        f"الغرف الأولي: {listing.get('rooms','')}\n"
        f"الرابط: {listing.get('url','')}"
    )

    async with _semaphore:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model":      "claude-haiku-4-5-20251001",
                        "max_tokens": 512,
                        "system":     SYSTEM_PROMPT,
                        "messages":   [{"role": "user", "content": raw_text}],
                    },
                )
                resp.raise_for_status()

            raw_json = resp.json()["content"][0]["text"].strip()
            # Strip markdown fences if present
            if "```" in raw_json:
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]
            raw_json = raw_json.strip()

            parsed: dict = json.loads(raw_json)

            # Merge: only overwrite if AI found a real value
            for key in ("price", "rooms", "size_m2", "floor",
                        "available_from", "is_urgent", "features",
                        "district", "apply_url", "summary_ar"):
                val = parsed.get(key)
                if val is not None and val != [] and val != "":
                    listing[key] = val

            # Compute price/m²
            p = listing.get("price")
            s = listing.get("size_m2")
            listing["price_per_m2"] = round(p / s, 1) if p and s else None

            # Use district to improve location if empty
            if parsed.get("district") and not listing.get("location"):
                listing["location"] = parsed["district"]

        except json.JSONDecodeError:
            logger.warning("AI bad JSON for '%s' — regex fallback",
                           str(listing.get("title", ""))[:40])
            return enrich(listing)
        except Exception as e:
            logger.warning("AI failed for '%s': %s — regex fallback",
                           str(listing.get("title", ""))[:40], e)
            return enrich(listing)

    return listing
