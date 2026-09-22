import re

MAHRA_KEYWORDS_HIGH = [
    "المهرة", "محافظة المهرة", "المهرة اليمنية", "الغيضة", "الغيضه",
    "حوف", "حصوين", "قشن", "سيحوت", "المسيلة", "شحن", "حات",
    "نشطون", "صرفيت", "منعر", "محيفيف", "الفيدمي", "ضبوت", "فرتك", "العبري"
]

MAHRA_KEYWORDS_MEDIUM = [
    "منفذ شحن", "منفذ صرفيت", "ميناء نشطون", "جبل فرتك", "وادي المسيلة",
    "السلطة المحلية بالمهرة", "أمن المهرة", "شرطة المهرة"
]

CONTEXT_KEYWORDS = [
    "اليمن", "المحافظة", "السلطة المحلية", "الأمن", "الأحوال الجوية",
    "ميناء", "منفذ", "مديرية", "محافظة", "جمارك", "صيد", "إعصار", "طريق"
]

SCORE_THRESHOLD = 8

def calculate_mahra_score(title: str, content: str = "") -> tuple[int, list]:
    text = f"{title} {content}".strip()
    score = 0
    matched_words = []

    for kw in MAHRA_KEYWORDS_HIGH:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            score += 10
            matched_words.append(kw)

    for kw in MAHRA_KEYWORDS_MEDIUM:
        if kw in text:
            score += 12
            matched_words.append(kw)

    if score > 0:
        for kw in CONTEXT_KEYWORDS:
            if kw in text:
                score += 2

    return score, list(set(matched_words))
