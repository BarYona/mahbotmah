#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט טלגרם אוטומטי לעלי אקספרס (AliExpress Deals & Coupons Telegram Bot)
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1001234567890")
RUN_ONCE = os.getenv("RUN_ONCE", "false").lower() in ("true", "1", "yes") or "--once" in sys.argv
POST_INTERVAL_MINUTES = int(os.getenv("POST_INTERVAL_MINUTES", "30"))

ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY", "")
ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET", "")
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID", "default")

TARGET_CURRENCY = "ILS"
TARGET_LANGUAGE = "HE"
SHIP_TO_COUNTRY = "IL"
USD_TO_ILS_RATE = 3.75

HISTORY_FILE = "sent_products.json"

SITEWIDE_COUPONS: List[Tuple[float, float, str, str]] = [
    (55.0, 7.5, "AEIL02", "$2 הנחה בקנייה מעל $15"),
    (145.0, 18.5, "AEIL05", "$5 הנחה בקנייה מעל $39"),
    (295.0, 37.5, "AEIL10", "$10 הנחה בקנייה מעל $79"),
    (590.0, 75.0, "AEIL20", "$20 הנחה בקנייה מעל $159"),
    (990.0, 130.0, "AEIL35", "$35 הנחה בקנייה מעל $269"),
]

SEARCH_KEYWORDS = [
    "ugreen usbc charger",
    "baseus car holder",
    "xiaomi smart gadget",
    "anker bluetooth earphone",
    "magsafe wireless charger",
    "smart watch bluetooth",
    "LED strip lights rgb",
    "mini portable blender",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

def load_sent_history() -> List[str]:
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
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-200:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save history file: {e}")

def find_best_coupon_and_price(
    base_price_ils: float,
    promo_code_info: Optional[Dict[str, Any]] = None,
    seller_discount_ils: float = 0.0,
) -> Dict[str, Any]:
    price_after_seller = max(0.0, base_price_ils - seller_discount_ils)

    candidates = [
        {
            "code": None,
            "description": "ללא קופון נוסף (מבצע ישיר באתר)",
            "discount_ils": seller_discount_ils,
            "final_price_ils": round(price_after_seller, 2),
        }
    ]

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

    best_option = min(candidates, key=lambda x: x["final_price_ils"])
    return best_option

def create_product_collage(image_urls: List[str], canvas_size: int = 1000) -> Optional[BytesIO]:
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

def sign_aliexpress_request(params: Dict[str, str], app_secret: str) -> str:
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

def get_demo_product() -> Dict[str, Any]:
    demo_pool = [
        {
            "id": "demo_1001",
            "title": "אוזניות אלחוטיות Anker Soundcore עם סינון רעשים אקטיבי ANC",
            "original_price_ils": 240.0,
            "sale_price_ils": 165.0,
            "rating": "4.9 ⭐",
            "orders": 5400,
            "affiliate_url": "https://s.click.aliexpress.com/e/_demo1001",
            "images": [
                "https://picsum.photos/seed/earbuds1/600/600",
            ],
            "promo_code_info": {
                "promo_code": "SOUND25",
                "promo_value_ils": 25.0,
                "promo_min_ils": 150.0,
            },
        }
    ]
    return random.choice(demo_pool)

def fetch_random_aliexpress_product() -> Dict[str, Any]:
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

            main_image = chosen.get("product_main_image_url", "")
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

            # שאיבת הקישור המקורי והאמיתי בדיוק כפי שה-API של עליאקספרס מייצר אותו (ללא שום מניפולציה)
            promotion_link = chosen.get("promotion_link", "")
            if promotion_link:
                final_affiliate_url = promotion_link
            else:
                final_affiliate_url = "https://www.aliexpress.com"

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

def format_deal_caption(product: Dict[str, Any], best_coupon: Dict[str, Any]) -> str:
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

    if best_coupon["code"]:
        coupon_line = "🎟️ <b>הקופון הכי משתלם:</b> <code>" + str(best_coupon['code']) + "</code> <i>(לחצו על הקוד להעתקה!)</i>\n💡 <b>פרטי ההטבה:</b> " + str(best_coupon['description'])
    else:
        coupon_line = "🎟️ <b>קופון:</b> ההנחה יורדת אוטומטית בקופה ללא צורך בקוד!"

    affiliate_url = product.get("affiliate_url", "https://www.aliexpress.com")

    caption = (
        opener + "\n\n" +
        "🛍️ <b>" + str(product['title']) + "</b>\n\n" +
        "⭐ <b>דירוג הקונים:</b> " + str(product['rating']) + "\n" +
        "📦 <b>נמכרו כבר:</b> מעל " + f"{product['orders']:,}" + " יחידות!\n\n" +
        "💰 <b>מחיר מקורי:</b> <s>" + f"{orig_price:.0f}" + " ₪</s>\n" +
        "✅ <b>מחיר סופי אחרי קופון:</b> <b>" + f"{final_price:.0f}" + " ₪ בלבד!</b> (חיסכון של " + str(discount_pct) + "% / " + f"{total_saved:.0f}" + " ₪)\n\n" +
        coupon_line + "\n\n" +
        affiliate_url
    )
    return caption

def send_deal_to_telegram(chat_id: str) -> bool:
    product = fetch_random_aliexpress_product()
    best_coupon = find_best_coupon_and_price(
        base_price_ils=product["sale_price_ils"],
        promo_code_info=product.get("promo_code_info"),
    )
    
    caption = format_deal_caption(product, best_coupon)
    
    if len(caption) > 1023:
        caption = caption[:1000] + "..."

    collage_io = create_product_collage(product.get("images", []))

    base_api = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN

    try:
        if collage_io:
            resp = requests.post(
                base_api + "/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={"photo": ("collage.jpg", collage_io, "image/jpeg")},
                timeout=30,
            )
            resp.raise_for_status()
        else:
            resp = requests.post(
                base_api + "/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                },
                timeout=30,
            )
            resp.raise_for_status()

        logger.info("Successfully sent deal to chat " + str(chat_id) + "!")
        return True

    except Exception as e:
        logger.error("Failed to send deal to Telegram: " + str(e))
        return False

def main() -> None:
    if RUN_ONCE:
        success = send_deal_to_telegram(TELEGRAM_CHAT_ID)
        sys.exit(0 if success else 1)

    while True:
        send_deal_to_telegram(TELEGRAM_CHAT_ID)
        time.sleep(POST_INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
