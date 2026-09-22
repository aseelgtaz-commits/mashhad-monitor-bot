import re

# 1. الكلمات المفتاحية والأوزان (Scoring System)
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

# الحد الأدنى للدرجة لاعتبار الخبر متعلقاً بالمهرة
SCORE_THRESHOLD = 8

def calculate_mahra_score(title: str, content: str = "") -> tuple[int, list]:
    """
    تحسب درجة صلة النص بمحافظة المهرة وتستخرج الكلمات التي تم العثور عليها.
    """
    text = f"{title} {content}".strip()
    score = 0
    matched_words = []

    # فحص الكلمات ذات الأولوية العالية (+10)
    for kw in MAHRA_KEYWORDS_HIGH:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            score += 10
            matched_words.append(kw)

    # فحص العبارات المركبة المتوسطة (+12)
    for kw in MAHRA_KEYWORDS_MEDIUM:
        if kw in text:
            score += 12
            matched_words.append(kw)

    # فحص الكلمات السياقية (+2) إذا وُجدت كلمة من المهرة
    if score > 0:
        for kw in CONTEXT_KEYWORDS:
            if kw in text:
                score += 2

    return score, list(set(matched_words))

def is_mahra_related(title: str, content: str = "", min_score: int = SCORE_THRESHOLD) -> bool:
    """
    تعيد True إذا كان الخبر متعلقاً بالمهرة بناءً على الحد الأدنى للدرجات.
    """
    score, _ = calculate_mahra_score(title, content)
    return score >= min_score
