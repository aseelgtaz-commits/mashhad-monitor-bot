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


def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase in text


def calculate_mahra_score(title: str, content: str = "") -> tuple[int, list[str]]:
    text = f"{title or ''} {content or ''}".strip()
    score = 0
    matched_words: list[str] = []

    for keyword in MAHRA_KEYWORDS_HIGH:
        pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            score += 10
            matched_words.append(keyword)

    for keyword in MAHRA_KEYWORDS_MEDIUM:
        if _contains_phrase(text, keyword):
            score += 12
            matched_words.append(keyword)

    if score > 0:
        for keyword in CONTEXT_KEYWORDS:
            if keyword in text:
                score += 2

    return score, list(dict.fromkeys(matched_words))


