"""
Turkish copy for the daily motivation message and plan status lines.

Kept in one module so wording can be tuned (or localized) without touching
business logic. Message composition is deterministic per (user, day) so the
same day always shows the same message across devices.
"""
import random
from datetime import date
from decimal import Decimal
from typing import Optional

WEEKDAYS_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
WEEKDAYS_LONG_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

CATEGORY_TR = {
    "salary": "Maaş", "freelance": "Serbest İş", "investment": "Yatırım", "gift": "Hediye",
    "other_income": "Diğer Gelir", "food_dining": "Yemek / Restoran", "groceries": "Market",
    "transportation": "Ulaşım", "housing": "Kira / Konut", "utilities": "Faturalar",
    "healthcare": "Sağlık", "entertainment": "Eğlence", "shopping": "Alışveriş", "education": "Eğitim",
    "travel": "Seyahat", "insurance": "Sigorta", "savings_transfer": "Birikim Transferi",
    "debt_payment": "Borç Ödemesi", "subscriptions": "Abonelikler", "other_expense": "Diğer Gider",
}


def category_label(value: str) -> str:
    return CATEGORY_TR.get(value, value.replace("_", " ").title())


QUOTES_TR = [
    "Damlaya damlaya göl olur.",
    "Bugün biriktirdiğin her kuruş, yarınki özgürlüğünün tuğlasıdır.",
    "Zenginlik çok kazanmak değil, kazandığından azını harcamaktır.",
    "Küçük adımlar, büyük mesafeler kat eder.",
    "Bütçe, paranın nereye gittiğini söylemektir; nereye gittiğini sonradan merak etmek değil.",
    "Disiplin, motivasyonun tükendiği yerde devreye girer.",
    "Bir hedefin yoksa her yol aynı yere çıkar. Hedefini yaz, parana yön ver.",
    "Sabır acıdır ama meyvesi tatlıdır.",
    "Ayakkabını ağzına göre değil, kesene göre seç.",
    "Bugünün küçük 'hayır'ları, yarının büyük 'evet'leridir.",
    "Para bir araçtır; yönünü sen belirlersin.",
    "Her gün %1 daha iyi olmak, yıl sonunda 37 kat fark yaratır.",
    "Ak akçe kara gün içindir.",
    "İhtiyaç ile istek arasındaki farkı bilen, cebini korur.",
    "Planlamak için harcadığın 5 dakika, ay sonunda sana günler kazandırır.",
    "Zorluklar seni durdurmak için değil, güçlendirmek için vardır.",
    "Başarı, her gün tekrarlanan küçük çabaların toplamıdır.",
    "Yarın için bugün bir adım at; gelecekteki sen teşekkür edecek.",
]


def fmt_money(value: Decimal, symbol: str) -> str:
    """Turkish-style money formatting: 1.250,50 ₺"""
    q = value.quantize(Decimal("0.01"))
    sign = "-" if q < 0 else ""
    whole, frac = f"{abs(q):.2f}".split(".")
    whole_grouped = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{whole_grouped},{frac} {symbol}"


def pick_quote(seed: str) -> str:
    return random.Random(seed).choice(QUOTES_TR)


def status_line(status: str, *, remaining_today: Decimal, today_allowance: Decimal, symbol: str) -> str:
    if status == "no_income":
        return "Bu dönem için gelir girilmedi. Plan sekmesinden maaşını / haftalık gelirini yaz, günlük limitini hesaplayalım."
    if status == "over":
        return "Bu dönemin harcanabilir bütçesi aşıldı. Kalan günlerde harcamayı en aza indirmeye odaklan."
    if status == "tight":
        if remaining_today < 0:
            return f"Bugünkü limitini {fmt_money(-remaining_today, symbol)} aştın. Sorun değil — yarın {fmt_money(today_allowance, symbol)} ile toparlarsın."
        return f"Bütçe daralıyor: bugün en fazla {fmt_money(today_allowance, symbol)} harcamaya çalış."
    return f"Bugün {fmt_money(remaining_today, symbol)} daha harcayabilirsin. Plan yolunda!"


def compose_daily_message(
    *,
    first_name: Optional[str],
    today: date,
    status: str,
    today_allowance: Decimal,
    remaining_total: Decimal,
    days_remaining: int,
    yesterday_planned: Optional[Decimal],
    yesterday_spent: Optional[Decimal],
    symbol: str,
    seed: str,
    period_word: str = "Ay",          # "Ay" or "Hafta" — matches the user's pay period
    reserved_total: Decimal = Decimal("0"),
) -> tuple[str, str, str]:
    """Return (title, body, quote) for the daily motivation message."""
    name = f" {first_name}" if first_name else ""
    weekday = WEEKDAYS_LONG_TR[today.weekday()]
    title = f"Günaydın{name}! ☀️ İyi {weekday}lar" if today.weekday() != 6 else f"Günaydın{name}! ☀️ İyi Pazarlar"

    parts: list[str] = []

    # 1) Yesterday's verdict
    if yesterday_planned is not None and yesterday_spent is not None and yesterday_planned > 0:
        diff = yesterday_planned - yesterday_spent
        if yesterday_spent == 0:
            parts.append("Dün hiç harcama yapmadın — sıfır gün! 🏆")
        elif diff >= 0:
            parts.append(f"Dün planının {fmt_money(diff, symbol)} altında kaldın 👏")
        else:
            parts.append(f"Dün planı {fmt_money(-diff, symbol)} aştın; bugün dengeleme günü 💪")

    # 2) Today's plan
    if status == "no_income":
        parts.append("Bu dönem için gelir bilgin yok. Plan sekmesinden gelirini gir, sana günlük bir limit çıkaralım.")
    elif status == "over":
        parts.append(
            f"{period_word}ın harcanabilir bütçesi aşıldı ({fmt_money(remaining_total, symbol)}). "
            f"Kalan {days_remaining} günde sadece zorunlu harcamalara odaklan."
        )
    else:
        parts.append(
            f"Bugün serbestçe harcayabileceğin: {fmt_money(today_allowance, symbol)}. "
            f"{period_word} sonuna {days_remaining} gün, kalan bütçe {fmt_money(remaining_total, symbol)}."
        )
        if reserved_total > 0:
            parts.append(f"Sabit giderlerin için {fmt_money(reserved_total, symbol)} ayrıldı.")

    body = " ".join(parts)
    quote = pick_quote(seed)
    return title, body, quote
