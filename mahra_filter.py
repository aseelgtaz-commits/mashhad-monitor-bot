import re

MAHRA_KEYWORDS_HIGH = [
    "المهرة", "محافظة المهرة", "المهرة اليمنية", "الغيضة", "الغيضه",
    "حوف", "حصوين", "قشن", "سيحوت", "المسيلة", "شحن", "حات",
    "نشطون", "صرفيت", "منعر", "محيفيف", "الفيدمي", "ضبوت", "فرتك", "العبري",
]

MAHRA_KEYWORDS_MEDIUM = [
    "منفذ شحن", "منفذ صرفيت", "ميناء نشطون", "جبل فرتك", "وادي المسيلة",
    "السلطة المحلية بالمهرة", "أمن المهرة", "شرطة المهرة",
]

CONTEXT_KEYWORDS = [
    "اليمن", "المحافظة", "السلطة المحلية", "الأمن", "الأحوال الجوية",
    "ميناء", "منفذ", "مديرية", "محافظة", "جمارك", "صيد", "إعصار", "طريق",
]

SCORE_THRESHOLD = 8


def _contains(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False
    if " " in keyword:
        return keyword.lower() in text.lower()
    return bool(re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text, re.IGNORECASE))


def calculate_mahra_score(title: str, content: str = "") -> tuple[int, list[str]]:
    text = f"{title or ''} {content or ''}".strip()
    score = 0
    matched_words: list[str] = []

    for keyword in MAHRA_KEYWORDS_HIGH:
        if _contains(text, keyword):
            score += 10
            matched_words.append(keyword)

    for keyword in MAHRA_KEYWORDS_MEDIUM:
        if _contains(text, keyword):
            score += 12
            matched_words.append(keyword)

    if score > 0:
        for keyword in CONTEXT_KEYWORDS:
            if _contains(text, keyword):
                score += 2

    return score, list(dict.fromkeys(matched_words))

