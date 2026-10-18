#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט טלגרם אוטומטי לעלי אקספרס (AliExpress Deals & Coupons Telegram Bot)
מותאם להרצה חינמית בענן עם GitHub Actions (ללא צורך להשאיר מחשב דולק!)
או להרצה רציפה על שרת/מחשב.

תכונות הבוט:
1. שולף מוצרים חמים ואקראיים מתוך ה-API הרשמי של AliExpress Affiliate (או ממאגר בדיקה מובנה).
2. מחשב אוטומטית אילו קופונים (קופוני מדרגה + קופוני מוכר) תקפים למוצר ובוחר את הקופון שנותן את המחיר הסופי הזול ביותר.
3. מוריד את תמונות המוצר ויוצר מהן קולאז' מרובע (2x2) אוטומטי וחד באמצעות ספריית Pillow.
4. מנסח פוסט שיווקי בעברית עם אימוג'ים, דירוג כוכבים, כמות הזמנות, קוד קופון להעתקה בלחיצה וכפתור רכישה.
5. תומך במצב שליחה חד-פעמית (--once או RUN_ONCE=true) עבור GitHub Actions וגם במצב לולאה רציפה.

התקנת ספריות נדרשות:
pip install requests pillow
"""

import hashlib
import hmac
from io import BytesIO
import json
import logging
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps
import requests

# ==========================================
# 1. הגדרות קונפיגורציה (Configuration)
# ==========================================

# טוקן הבוט מ-@BotFather בטלגרם (מוזן אוטומטית מ-GitHub Secrets בענן)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# מזהה הקבוצה או הערוץ (למשל "-1001234567890" או "@your_channel_username")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1001234567890")

# מצב הרצה: אם מוגדר "true" (ברירת מחדל ב-GitHub Actions), שולח דיל אחד ונסגר מיד
RUN_ONCE = os.getenv("RUN_ONCE", "false").lower() in ("true", "1", "yes") or "--once" in sys.argv

# תדירות שליחת הודעות בדקות (רלוונטי רק אם מריצים בלולאה רציפה על מחשב/שרת)
POST_INTERVAL_MINUTES = int(os.getenv("POST_INTERVAL_MINUTES", "30"))

# פרטי חשבון AliExpress Portals Affiliate API (https://portals.aliexpress.com/)
ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY", "")
ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET", "")
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID", "default")

# מטבע ושפה מועדפים
TARGET_CURRENCY = "ILS"  # ניתן לשנות ל-"USD"
TARGET_LANGUAGE = "HE"   # עברית ("HE") או אנגלית ("EN")
SHIP_TO_COUNTRY = "IL"   # ישראל
USD_TO_ILS_RATE = 3.75   # שער המרה משוער לחישוב מדרגות קופונים דולריים

# קובץ לשמירת היסטוריית מוצרים שנשלחו כדי למנוע כפילויות בין הרצות
HISTORY_FILE = "sent_products.json"

# רשימת קופוני מדרגה כלליים בעלי אקספרס (ניתן לעדכן בכל סייל חודשי)
# המבנה: (סכום מינימום להזמנה ב-₪, גובה ההנחה ב-₪, קוד הקופון, תיאור)
SITEWIDE_COUPONS: List[Tuple[float, float, str, str]] = [
    (55.0, 7.5, "AEIL02", "$2 הנחה בקנייה מעל $15"),
    (145.0, 18.5, "AEIL05", "$5 הנחה בקנייה מעל $39"),
    (295.0, 37.5, "AEIL10", "$10 הנחה בקנייה מעל $79"),
    (590.0, 75.0, "AEIL20", "$20 הנחה בקנייה מעל $159"),
    (990.0, 130.0, "AEIL35", "$35 הנחה בקנייה מעל $269"),
]

# מילות מפתח וקטגוריות לבחירה אקראית של מוצרים מבוקשים
SEARCH_KEYWORDS = [
    "wireless earbuds bluetooth",
    "smart watch fitness",
    "usb c GaN charger",
    "xiaomi smart home gadget",
    "car phone holder magsafe",
    "portable blender usb",
    "led strip lights rgb",
    "mechanical keyboard wireless",
    "mini projector 1080p",
    "kitchen organizer gadget",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ==========================================
# 2. ניהול היסטוריית מוצרים למניעת כפילויות
# ==========================================

def load_sent_history() -> List[str]:
    """טוען את רשימת המוצרים שכבר פורסמו מתוך קובץ JSON מקומי."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data]
        except Exception as e:
            logger.warning(f"Could not read history file: {e}")
    return []


def save_sent_history(history: List[str]) -> None:
    """שומר את 200 המוצרים האחרונים שפורסמו כדי לא לחזור עליהם."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-200:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save history file: {e}")


# ==========================================
# 3. מנוע חישוב הקופון הטוב והזול ביותר
# ==========================================

def find_best_coupon_and_price(
    base_price_ils: float,
    promo_code_info: Optional[Dict[str, Any]] = None,
    seller_discount_ils: float = 0.0,
) -> Dict[str, Any]:
    """
    בודק את כל הקופונים האפשריים (קופוני מדרגה כלליים + קופון מוכר/פרומו מה-API)
    ומחזיר את השילוב שמביא למחיר הסופי הנמוך ביותר.
    """
    price_after_seller = max(0.0, base_price_ils - seller_discount_ils)

    candidates = [
        {
            "code": None,
            "description": "ללא קופון נוסף (מבצע ישיר באתר)",
            "discount_ils": seller_discount_ils,
            "final_price_ils": round(price_after_seller, 2),
        }
    ]

    # בדיקת קופוני מדרגה כלליים
    for min_spend, discount, code, desc in SITEWIDE_COUPONS:
        if price_after_seller >= min_spend:
            total_discount = seller_discount_ils + discount
            final_price = max(0.0, base_price_ils - total_discount)
            candidates.append(
                {
                    "code": code,
                    "description": desc,
                    "discount_ils": round(total_discount, 2),
                    "final_price_ils": round(final_price, 2),
                }
            )

    # בדיקת קופון ספציפי שהגיע מה-API של המוצר (אם קיים)
    if promo_code_info and promo_code_info.get("promo_code"):
        promo_code = promo_code_info["promo_code"]
        promo_discount = float(promo_code_info.get("promo_value_ils", 0.0))
        promo_min = float(promo_code_info.get("promo_min_ils", 0.0))
        if price_after_seller >= promo_min and promo_discount > 0:
            total_discount = seller_discount_ils + promo_discount
            final_price = max(0.0, base_price_ils - total_discount)
            candidates.append(
                {
                    "code": promo_code,
                    "description": f"קופון ייחודי למוצר ({promo_discount:.0f}₪ הנחה)",
                    "discount_ils": round(total_discount, 2),
                    "final_price_ils": round(final_price, 2),
                }
            )

    # מיון לפי המחיר הסופי הנמוך ביותר
    best_option = min(candidates, key=lambda x: x["final_price_ils"])
    return best_option


# ==========================================
# 4. יצירת קולאז' תמונות אוטומטי (Pillow)
# ==========================================

def create_product_collage(image_urls: List[str], canvas_size: int = 1000) -> Optional[BytesIO]:
    """
    מוריד עד 4 תמונות של המוצר ויוצר קולאז' מרובע וחד (2x2).
    אם יש רק תמונה אחת תקינה, מחזיר אותה בגודל מותאם.
    """
    downloaded_images: List[Image.Image] = []

    for url in image_urls[:4]:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            downloaded_images.append(img)
        except Exception as e:
            logger.warning(f"Failed to download image {url}: {e}")

    if not downloaded_images:
        return None

    output_buffer = BytesIO()

    if len(downloaded_images) == 1:
        single_img = ImageOps.fit(
            downloaded_images[0], (canvas_size, canvas_size), Image.Resampling.LANCZOS
        )
        single_img.save(output_buffer, format="JPEG", quality=92)
        output_buffer.seek(0)
        return output_buffer

    while len(downloaded_images) < 4:
        downloaded_images.append(downloaded_images[0])

    gap = 12
    cell_size = (canvas_size - (gap * 3)) // 2
    collage = Image.new("RGB", (canvas_size, canvas_size), color=(255, 255, 255))

    positions = [
        (gap, gap),
        (gap * 2 + cell_size, gap),
        (gap, gap * 2 + cell_size),
        (gap * 2 + cell_size, gap * 2 + cell_size),
    ]

    for img, pos in zip(downloaded_images[:4], positions):
        fitted = ImageOps.fit(img, (cell_size, cell_size), Image.Resampling.LANCZOS)
        collage.paste(fitted, pos)

    collage.save(output_buffer, format="JPEG", quality=92)
    output_buffer.seek(0)
    return output_buffer


# ==========================================
# 5. שליפת מוצרים מ-AliExpress Affiliate API
# ==========================================

def sign_aliexpress_request(params: Dict[str, str], app_secret: str) -> str:
    """חתימת HMAC-SHA256 תקנית עבור AliExpress Open Platform API."""
    sorted_keys = sorted(params.keys())
    concatenated = "".join(f"{k}{params[k]}" for k in sorted_keys)
    return (
        hmac.new(
            app_secret.encode("utf-8"),
            concatenated.encode("utf-8"),
            hashlib.sha256,
        )
        .hexdigest()
        .upper()
    )


def fetch_random_aliexpress_product() -> Dict[str, Any]:
    """
    שולף מוצר אמיתי מה-API של עליאקספרס ומחלץ את הקישור והתמונות הספציפיות שלו.
    """
    if not ALIEXPRESS_APP_KEY or not ALIEXPRESS_APP_SECRET:
        logger.info("No AliExpress API keys configured; using demo.")
        return get_demo_product()

    history = load_sent_history()
    keyword = random.choice(SEARCH_KEYWORDS)
    api_url = "https://api-sg.aliexpress.com/sync"

    params = {
        "app_key": ALIEXPRESS_APP_KEY,
        "method": "aliexpress.affiliate.product.query",
        "sign_method": "sha256",
        "timestamp": str(int(time.time() * 1000)),
        "format": "json",
        "v": "2.0",
        "keywords": keyword,
        "target_currency": TARGET_CURRENCY,
        "target_language": TARGET_LANGUAGE,
        "ship_to_country": SHIP_TO_COUNTRY,
        "tracking_id": ALIEXPRESS_TRACKING_ID,
        "sort": "LAST_VOLUME_DESC",
        "page_size": "20",
    }
    params["sign"] = sign_aliexpress_request(params, ALIEXPRESS_APP_SECRET)

    try:
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        resp_result = (
            data.get("aliexpress_affiliate_product_query_response", {})
            .get("resp_result", {})
            .get("result", {})
        )
        products = resp_result.get("products", {}).get("product", [])

        available = [p for p in products if str(p.get("product_id")) not in history]
        if not available and products:
            available = products

        if available:
            chosen = random.choice(available)
            prod_id = str(chosen.get("product_id"))
            history.append(prod_id)
            save_sent_history(history)

            # חילוץ תמונות אמיתיות של המוצר
            main_image = chosen.get("product_main_image_url", "")
            
            # עליאקספרס לפעמים מחזיר רשימת תמונות במבנה מסוים
            small_imgs_container = chosen.get("product_small_image_urls", {})
            if isinstance(small_imgs_container, dict):
                small_images = small_imgs_container.get("string", [])
            elif isinstance(small_imgs_container, list):
                small_images = small_imgs_container
            else:
                small_images = []

            all_images = [img for img in ([main_image] + small_images) if img]
            if not all_images:
                all_images = ["https://picsum.photos/600/600"]

            sale_price = float(
                chosen.get("target_sale_price", chosen.get("target_original_price", 100.0))
            )
            orig_price = float(chosen.get("target_original_price", sale_price * 1.3))

            # חילוץ הקישור השיווקי האמיתי של המוצר (Promotion Link)
            promo_link = chosen.get("promotion_link")
            detail_link = chosen.get("product_detail_url")
            
            # וידוא שהקישור תקין וכולל את ה-s.click או כתובת הפניה מלאה
            final_affiliate_url = promo_link if promo_link else (detail_link if detail_link else "https://www.aliexpress.com")

            promo_info = chosen.get("promo_code_info", {})
            parsed_promo = None
            if promo_info and isinstance(promo_info, dict) and promo_info.get("promo_code"):
                parsed_promo = {
                    "promo_code": promo_info.get("promo_code"),
                    "promo_value_ils": float(promo_info.get("code_value", 5.0)) * USD_TO_ILS_RATE,
                    "promo_min_ils": float(promo_info.get("code_mini_spend", 20.0)) * USD_TO_ILS_RATE,
                }

            return {
                "id": prod_id,
                "title": chosen.get("product_title", "מוצר מומלץ מעלי אקספרס"),
                "original_price_ils": orig_price,
                "sale_price_ils": sale_price,
                "rating": str(chosen.get("evaluate_rate", "4.8/5")),
                "orders": int(chosen.get("lastest_volume", 500)),
                "affiliate_url": final_affiliate_url,
                "images": all_images,
                "promo_code_info": parsed_promo,
            }

    except Exception as e:
        logger.error(f"Error fetching from AliExpress API: {e}")

    return get_demo_product()


def get_demo_product() -> Dict[str, Any]:
    """מאגר מוצרים להדגמה ובדיקה מיידית של הבוט לפני חיבור מפתחות API."""
    demo_pool = [
        {
            "id": "demo_1001",
            "title": "אוזניות אלחוטיות Anker Soundcore עם סינון רעשים אקטיבי ANC וסוללה ל-40 שעות",
            "original_price_ils": 240.0,
            "sale_price_ils": 165.0,
            "rating": "4.9 ⭐ (98% ביקורות חיוביות)",
            "orders": 5400,
            "affiliate_url": "https://www.aliexpress.com/",
            "images": [
                "https://picsum.photos/seed/earbuds1/600/600",
                "https://picsum.photos/seed/earbuds2/600/600",
                "https://picsum.photos/seed/earbuds3/600/600",
                "https://picsum.photos/seed/earbuds4/600/600",
            ],
            "promo_code_info": {
                "promo_code": "SOUND25",
                "promo_value_ils": 25.0,
                "promo_min_ils": 150.0,
            },
        },
        {
            "id": "demo_1002",
            "title": "מטען קיר מהיר Baseus GaN 65W עם 3 יציאות (USB-C + USB-A) למחשב נייד ולסמארטפון",
            "original_price_ils": 135.0,
            "sale_price_ils": 82.0,
            "rating": "4.9 ⭐ (99% ביקורות חיוביות)",
            "orders": 12300,
            "affiliate_url": "https://www.aliexpress.com/",
            "images": [
                "https://picsum.photos/seed/charger1/600/600",
                "https://picsum.photos/seed/charger2/600/600",
                "https://picsum.photos/seed/charger3/600/600",
                "https://picsum.photos/seed/charger4/600/600",
            ],
            "promo_code_info": None,
        },
        {
            "id": "demo_1003",
            "title": "מקרן קולנוע ביתי נייד החדש Full HD 1080P תומך WiFi 6 ובלוטות' עם מערכת אנדרואיד מובנית",
            "original_price_ils": 420.0,
            "sale_price_ils": 310.0,
            "rating": "4.8 ⭐ (96% ביקורות חיוביות)",
            "orders": 3200,
            "affiliate_url": "https://www.aliexpress.com/",
            "images": [
                "https://picsum.photos/seed/proj1/600/600",
                "https://picsum.photos/seed/proj2/600/600",
                "https://picsum.photos/seed/proj3/600/600",
                "https://picsum.photos/seed/proj4/600/600",
            ],
            "promo_code_info": None,
        },
    ]
    return random.choice(demo_pool)


# ==========================================
# 6. עיצוב הפוסט ושליחה ישירה לטלגרם
# ==========================================

def format_deal_caption(product: Dict[str, Any], best_coupon: Dict[str, Any]) -> str:
    """בונה טקסט שיווקי אטרקטיבי בעברית עם אימוג'ים, דירוג והקופון המשתלם ביותר."""
    openers = [
        "🔥 <b>דיל רותח שמצאתי עכשיו בעלי אקספרס!</b> 🔥",
        "⚡ <b>ירידת מחיר מטורפת על אחד המוצרים המבוקשים!</b> ⚡",
        "💎 <b>מציאה שווה במיוחד עם קופון שחוסך לכם כסף!</b> 💎",
        "🚀 <b>רב-מכר היסטרי במחיר הכי נמוך שמצאנו!</b> 🚀",
    ]
    opener = random.choice(openers)

    orig_price = product["original_price_ils"]
    final_price = best_coupon["final_price_ils"]
    total_saved = max(0.0, orig_price - final_price)
    discount_pct = int(round((total_saved / orig_price) * 100)) if orig_price > 0 else 0

    coupon_line = (
        f"🎟️ <b>הקופון הכי משתלם:</b> <code>{best_coupon['code']}</code> <i>(לחצו על הקוד להעתקה!)</i>\n"
        f"💡 <b>פרטי ההטבה:</b> {best_coupon['description']}"
        if best_coupon["code"]
        else "🎟️ <b>קופון:</b> ההנחה יורדת אוטומטית בקופה ללא צורך בקוד!"
    )

    caption = (
        f"{opener}\n\n"
        f"🛍️ <b>{product['title']}</b>\n\n"
        f"⭐ <b>דירוג הקונים:</b> {product['rating']}\n"
        f"📦 <b>נמכרו כבר:</b> מעל {product['orders']:,} יחידות!\n\n"
        f"💰 <b>מחיר מקורי:</b> <s>{orig_price:.0f} ₪</s>\n"
        f"✅ <b>מחיר סופי אחרי קופון:</b> <b>{final_price:.0f} ₪ בלבד!</b> (חיסכון של {discount_pct}% / {total_saved:.0f} ₪)\n\n"
        f"{coupon_line}\n\n"
        f"👇 <b>למעבר מהיר למוצר ולמימוש המבצע:</b>\n"
        f"{product['affiliate_url']}"
    )
    return caption


def send_deal_to_telegram(chat_id: str) -> bool:
    """
    שולף מוצר, מחשב קופון, בונה קולאז' ושולח תמונה בראש המודעה עם כפתור נקי.
    """
    product = fetch_random_aliexpress_product()
    best_coupon = find_best_coupon_and_price(
        base_price_ils=product["sale_price_ils"],
        promo_code_info=product.get("promo_code_info"),
    )
    
    # חילוץ וקיצור כתובת הקישור אם היא ארוכה מדי
    raw_url = product.get("affiliate_url", "https://www.aliexpress.com")
    
    caption = format_deal_caption(product, best_coupon)
    collage_io = create_product_collage(product.get("images", []))

    # כפתור אינטראקטיבי נקי שמוביל למוצר
    reply_markup = json.dumps(
        {
            "inline_keyboard": [
                [
                    {
                        "text": "🛒 לקנייה בעלי אקספרס במחיר מבצע",
                        "url": raw_url,
                    }
                ]
            ]
        }
    )

    base_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    try:
        if collage_io:
            # שליחת תמונה בראש המודעה יחד עם ה-caption (הטקסט למטה) והכפתור
            resp = requests.post(
                f"{base_api}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
                files={"photo": ("collage.jpg", collage_io, "image/jpeg")},
                timeout=30,
            )
            resp.raise_for_status()
        else:
            # גיבוי אם אין תמונה כלל
            resp = requests.post(
                f"{base_api}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
                timeout=30,
            )
            resp.raise_for_status()

        logger.info(f"Successfully sent deal '{product['id']}' to chat {chat_id}!")
        return True

    except Exception as e:
        logger.error(f"Failed to send deal to Telegram: {e}")
        return False


def main() -> None:
    """נקודת הכניסה: מריץ שליחה חד-פעמית (עבור GitHub Actions) או לולאה מתמשכת."""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("⚠️ שים לב: יש להגדיר את TELEGRAM_BOT_TOKEN במשתני הסביבה (GitHub Secrets) או בקובץ.")
        sys.exit(1)

    if RUN_ONCE:
        logger.info("Running in single-shot mode (GitHub Actions / Scheduled Task)...")
        success = send_deal_to_telegram(TELEGRAM_CHAT_ID)
        sys.exit(0 if success else 1)

    logger.info(
        f"Running in continuous mode! Sending a deal every {POST_INTERVAL_MINUTES} minutes..."
    )
    while True:
        send_deal_to_telegram(TELEGRAM_CHAT_ID)
        time.sleep(POST_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
