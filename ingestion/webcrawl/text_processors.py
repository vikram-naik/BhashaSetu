# ============================
# Sentence Processor Strategies
# ============================

import logging
import re


class SentenceProcessor:
    def process(self, sentence: str) -> str | None:
        raise NotImplementedError

class QuoteNormalizer(SentenceProcessor):
    def process(self, sentence):
        if sentence.startswith('"') and not sentence.endswith('"'):
            return sentence.lstrip('"')
        return sentence

class DotCleaner(SentenceProcessor):
    def process(self, sentence):
        return re.sub(r'^\.\.+', '', sentence).strip()

class GujaratiFilter(SentenceProcessor):
    def __init__(self, threshold=0.6):
        self.threshold = threshold

    def process(self, sentence):
        gujarati_chars = sum(1 for c in sentence if '\u0A80' <= c <= '\u0AFF')
        total_chars = sum(1 for c in sentence if c.isalpha())
        if total_chars == 0 or gujarati_chars / total_chars < self.threshold:
            logging.warning(f"[NON-GU] Skipping: {sentence}")
            return None
        return sentence

class Deduplicator(SentenceProcessor):
    def __init__(self, conn):
        self.conn = conn

    def process(self, sentence):
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM staging_sentences WHERE sentence=? LIMIT 1", (sentence,))
        if cur.fetchone():
            return None
        return sentence

class LengthFilter(SentenceProcessor):
    def __init__(self, min_len=5, max_len=500):
        self.min_len = min_len
        self.max_len = max_len

    def process(self, sentence):
        length = len(sentence)
        if length < self.min_len or length > self.max_len:
            logging.warning(f"[LEN] Skipping sentence (len={length}): {sentence[:80]}...")
            return None
        return sentence

class StopwordFilter(SentenceProcessor):
    def __init__(self, stopwords=None):
        self.stopwords = set(stopwords or [])

    def process(self, sentence):
        tokens = sentence.split()
        if all(tok in self.stopwords for tok in tokens):
            logging.warning(f"[STOPWORD] Skipping: {sentence}")
            return None
        return sentence

class DigitHeavyFilter(SentenceProcessor):
    def __init__(self, max_digit_ratio=0.5):
        self.max_digit_ratio = max_digit_ratio

    def process(self, sentence):
        digits = sum(1 for c in sentence if c.isdigit())
        total = len(sentence)
        if total == 0:
            return None
        if digits / total > self.max_digit_ratio:
            logging.warning(f"[DIGIT] Skipping numeric-heavy sentence: {sentence}")
            return None
        return sentence
    
# ============================
# Factory Pattern
# ============================

class ProcessorFactory:
    registry = {
        "QuoteNormalizer": QuoteNormalizer,
        "DotCleaner": DotCleaner,
        "GujaratiFilter": GujaratiFilter,
        "Deduplicator": Deduplicator,
        "LengthFilter": LengthFilter,
        "StopwordFilter": StopwordFilter,
        "DigitHeavyFilter": DigitHeavyFilter
    }

    @classmethod
    def build_processors(cls, config, conn=None):
        processors = []
        for name, params in config.items():
            if name not in cls.registry:
                logging.warning(f"Unknown processor: {name}, skipping")
                continue
            klass = cls.registry[name]
            if name == "Deduplicator":   # requires DB connection
                processors.append(klass(conn))
            elif isinstance(params, dict):
                processors.append(klass(**params))
            else:
                processors.append(klass())
        return processors