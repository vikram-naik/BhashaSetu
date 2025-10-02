import re
import logging

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
            logging.warning(f"[NON-GU] Skipping: {sentence[:80]}...")
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

class WordCountFilter(SentenceProcessor):
    def __init__(self, min_words=4, max_words=80):
        self.min_words = min_words
        self.max_words = max_words

    def process(self, sentence):
        words = sentence.split()
        wc = len(words)
        if wc < self.min_words:
            logging.warning(f"[WORDS] Too short ({wc} words): {sentence}")
            return None
        if wc > self.max_words:
            logging.warning(f"[WORDS] Too long ({wc} words): {sentence[:80]}...")
            return None
        return sentence

class TruncatedSentenceFilter(SentenceProcessor):
    def process(self, sentence):
        if re.search(r'\.\s*\.', sentence):   # matches ". ." or "..."
            logging.warning(f"[TRUNC] Skipping truncated sentence: {sentence[:80]}...")
            return None
        return sentence

import logging

class BalancedQuotesFilter(SentenceProcessor):
    def process(self, sentence):
        # Use a copy of the original sentence for modifications
        modified_sentence = sentence
        
        # Define quote groups for targeted removal
        DOUBLE_QUOTES = ['"', '“', '”']
        SINGLE_QUOTES = ["'", '‘', '’']

        # --- Double Quotes Logic ---
        
        # Normalize double quotes to straight for accurate count
        normalized_double = modified_sentence.replace("“", '"').replace("”", '"')
        double_count = normalized_double.count('"')

        if double_count % 2 != 0:
            logging.warning(f"[QUOTE] Fixing unbalanced double quotes: {modified_sentence[:80]}...")
            
            # Find the last position of *any* double quote character
            last_index = -1
            for char in DOUBLE_QUOTES:
                rfind_index = modified_sentence.rfind(char)
                if rfind_index > last_index:
                    last_index = rfind_index
            
            # Surgically remove the character at the last found index
            if last_index != -1:
                modified_sentence = modified_sentence[:last_index] + modified_sentence[last_index+1:]

        # --- Single Quotes Logic ---
        
        # Normalize single quotes to straight for accurate count (on the potentially modified string)
        normalized_single = modified_sentence.replace("‘", "'").replace("’", "'")
        single_count = normalized_single.count("'")
        
        if single_count % 2 != 0:
            logging.warning(f"[QUOTE] Fixing unbalanced single quotes: {modified_sentence[:80]}...")
            
            # Find the last position of *any* single quote character
            last_index = -1
            for char in SINGLE_QUOTES:
                rfind_index = modified_sentence.rfind(char)
                if rfind_index > last_index:
                    last_index = rfind_index
            
            # Surgically remove the character at the last found index
            if last_index != -1:
                modified_sentence = modified_sentence[:last_index] + modified_sentence[last_index+1:]

        return modified_sentence.strip()

class BalancedQuotesFilter1(SentenceProcessor):
    def process(self, sentence):
        # Normalize fancy quotes to straight for counting
        normalized = (
            sentence.replace("“", '"')
                    .replace("”", '"')
                    .replace("‘", "'")
                    .replace("’", "'")
        )

        # Fix unbalanced double quotes
        double_count = normalized.count('"')
        if double_count % 2 != 0:
            logging.warning(f"[QUOTE] Fixing unbalanced double quotes: {sentence[:80]}...")
            # Remove first occurrence of unmatched double quote
            sentence = sentence.replace("“", "").replace("”", "").replace('"', "", 1)

        # Fix unbalanced single quotes
        single_count = normalized.count("'")
        if single_count % 2 != 0:
            logging.warning(f"[QUOTE] Fixing unbalanced single quotes: {sentence[:80]}...")
            sentence = sentence.replace("‘", "").replace("’", "").replace("'", "", 1)

        return sentence.strip()


# Factory
class ProcessorFactory:
    registry = {
        "QuoteNormalizer": QuoteNormalizer,
        "DotCleaner": DotCleaner,
        "GujaratiFilter": GujaratiFilter,
        "Deduplicator": Deduplicator,
        "WordCountFilter": WordCountFilter,
        "TruncatedSentenceFilter": TruncatedSentenceFilter,
        "BalancedQuotesFilter": BalancedQuotesFilter
    }

    @classmethod
    def build_processors(cls, config, conn=None):
        processors = []
        for name, params in config.items():
            if name not in cls.registry:
                logging.warning(f"Unknown processor: {name}, skipping")
                continue
            klass = cls.registry[name]
            if name == "Deduplicator":
                processors.append(klass(conn))
            elif isinstance(params, dict):
                processors.append(klass(**params))
            else:
                processors.append(klass())
        return processors
