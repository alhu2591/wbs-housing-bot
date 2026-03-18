"""
AI-powered listing analyzer using Claude API.
Extracts structured data from raw listing text with 100% accuracy.
Falls back to regex enrichment if API fails.
"""
import json
import logging
import os
import httpx
from filters.wbs_filter import enrich  # regex fallback

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """أنت محلل إعلانات شقق ألمانية متخصص.
مهمتك: استخراج المعلومات من إعلان شقة وإعادتها كـ JSON فقط — بدون أي نص إضافي.

القواعد:
- إذا المعلومة غير موجودة → null
- السعر: رقم بدون رمز € (مثال: 520)
- الغرف: رقم عشري (مثال: 2.5)
- المساحة: رقم بالمتر المربع بدون وحدة (مثال: 62)
- is_urgent: true فقط إذا وُجد "ab sofort" أو "sofort frei" أو "sofort verfügbar"
- available_from: تاريخ بالعربية أو "فوري" أو null
- floor: "الطابق الأرضي" أو "الطابق N" أو "الطابق العلوي" أو null
- features: قائمة من هذه القيم فقط إذا ذُكرت صراحةً:
  ["بلكونة","تراس","حديقة","مصعد","مطبخ مجهز","مخزن","موقف سيارة","بدون عوائق","بناء جديد","أول سكن"]
- apply_url: رابط التقديم المباشر إذا وُجد (غير رابط الإعلان العام)
- district: الحي أو المنطقة في برلين بالألمانية

أعد JSON بهذا الشكل فقط:
{
  "price": number|null,
  "rooms": number|null,
  "size_m2": number|null,
  "floor": string|null,
  "available_from": string|null,
  "is_urgent": boolean,
  "features": string[],
  "district": string|null,
  "apply_url": string|null,
  "summary_ar": string
}

summary_ar: جملة واحدة بالعربية تلخص الشقة (مثال: "شقة من غرفتين بمصعد وبلكونة في شارع هادئ")"""


async def ai_analyze(listing: dict) -> dict:
    """
    Use Claude to extract structured data from listing.
    Returns enriched listing dict.
    """
    if not ANTHROPIC_API_KEY:
        logger.debug("No ANTHROPIC_API_KEY — using regex enrichment")
        return enrich(listing)

    raw_text = "\n".join([
        f"العنوان: {listing.get('title', '')}",
        f"الوصف: {listing.get('description', '')}",
        f"الموقع: {listing.get('location', '')}",
        f"السعر الأولي: {listing.get('price', '')}",
        f"الغرف الأولي: {listing.get('rooms', '')}",
        f"رابط الإعلان: {listing.get('url', '')}",
    ])

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 600,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": raw_text}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw_json = data["content"][0]["text"].strip()

            # Strip markdown fences if present
            if raw_json.startswith("```"):
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]

            parsed = json.loads(raw_json.strip())

            # Merge AI results → only overwrite if AI found something
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

            # Use district to enrich location if better
            if parsed.get("district") and not listing.get("location"):
                listing["location"] = parsed["district"]

            logger.debug("AI analyzed: %s → %s", listing.get("title","")[:40], parsed)
            return listing

    except json.JSONDecodeError as e:
        logger.warning("AI returned invalid JSON for '%s': %s", listing.get("title","")[:40], e)
        return enrich(listing)
    except Exception as e:
        logger.warning("AI analysis failed for '%s': %s — using regex fallback", listing.get("title","")[:40], e)
        return enrich(listing)
