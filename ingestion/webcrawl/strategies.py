from abc import ABC, abstractmethod
import re
import logging
from dataclasses import dataclass
import os
import json
from .repositories import DomainRepository

@dataclass
class ProcessorResult:
    text: str | None
    status: str | None = "new"
    reject: bool = False
    metadata: dict | None = None

class SentenceProcessor(ABC):
    @abstractmethod
    def process(self, sentence: str, metadata: dict = None) -> ProcessorResult:
        pass

class QuoteNormalizer(SentenceProcessor):

    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        if sentence.startswith('"') and not sentence.endswith('"'):
            r.text = sentence.lstrip('"')
        return r

class DotCleaner(SentenceProcessor):
    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        r.text = re.sub(r'^\.\.+', '', sentence).strip()
        return r

class GujaratiFilter(SentenceProcessor):
    def __init__(self, threshold=0.6):
        self.threshold = threshold

    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        gujarati_chars = sum(1 for c in sentence if '\u0A80' <= c <= '\u0AFF')
        total_chars = sum(1 for c in sentence if c.isalpha())
        if total_chars == 0 or gujarati_chars / total_chars < self.threshold:
            logging.warning(f"[NON-GU] Skipping: {sentence[:80]}...")
            r.reject = True
        return r

class WordCountFilter(SentenceProcessor):
    def __init__(self, min_words=4, max_words=80):
        self.min_words = min_words
        self.max_words = max_words

    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        words = sentence.split()
        wc = len(words)
        if wc < self.min_words:
            logging.warning(f"[WORDS] Too short ({wc} words): {sentence}")
            r.reject = True
        if wc > self.max_words:
            logging.warning(f"[WORDS] Too long ({wc} words): {sentence[:80]}...")
            r.reject = True
        return r

class TruncatedSentenceFilter(SentenceProcessor):
    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        if re.search(r'\.\s*\.', sentence):   # matches ". ." or "..."
            logging.warning(f"[TRUNC] Skipping truncated sentence: {sentence[:80]}...")
            r.reject = True
        return r

class BalancedQuotesFilter(SentenceProcessor):
    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)

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
        r.text = modified_sentence.strip()
        return r

class PatternRejector(SentenceProcessor):
    def __init__(self, patterns):
        # compile regex patterns (case-insensitive)
        self.patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    def process(self, sentence, metadata: dict = None)  -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        for pat in self.patterns:
            if pat.search(sentence):
                logging.info(f"[AUTO-REJECT] '{sentence[:80]}...' matched {pat.pattern}")
                r.status = "rejected"
        return r

class SkipRootText(SentenceProcessor):
    """
    Skips inserting sentences if we are on the base_url page.
    Uses metadata['is_root'] flag from scraper.
    """
    def __init__(self, skip=True):
        self.skip = skip

    def process(self, sentence, metadata: dict = None) -> ProcessorResult:
        r = ProcessorResult(text=sentence)
        if self.skip and metadata and metadata.get("is_root"):
            logging.info("[SKIP-ROOT] Skipping sentence from base_url page")
            r.reject = True  # drop sentence
        return r


class DomainClassifier(SentenceProcessor):
    """
    Language-aware rule-based domain classifier.

    Loads domain keyword rules from external JSON files based on the language
    defined in config param for processor {'lang': 'gu'}.
    Produces metadata (domain_code, domain_name, confidence, source),
    leaving DB persistence to DBVisitor.
    """

    def __init__(self, lang):
        self.lang = lang
        self.rules = self._load_rules(self.lang)
        logging.info(f"[DomainClassifier] Loaded {len(self.rules)} domain rules for lang: {self.lang}")

    # ----------------------------------------------------------
    # Load rules from domain_rules/<lang>_domains.json
    # ----------------------------------------------------------
    def _load_rules(self, lang):
        base_dir = os.path.join(os.path.dirname(__file__), "..", "domain_rules")
        file_path = os.path.join(base_dir, f"{lang}_domains.json")

        if not os.path.exists(file_path):
            logging.warning(f"[DomainClassifier] No rules for '{lang}', using English fallback.")
            file_path = os.path.join(base_dir, "en_domains.json")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # normalize to lowercase for keyword matching
            rules = {
                code: {
                    "name": entry["name"],
                    "keywords": [kw.lower() for kw in entry.get("keywords", [])]
                }
                for code, entry in data.items()
            }
            return rules
        except Exception as e:
            logging.error(f"[DomainClassifier] Failed to load rules for '{lang}': {e}")
            return {}

    # ----------------------------------------------------------
    # Process each sentence and return domain metadata
    # ----------------------------------------------------------
    def process(self, sentence, metadata=None) -> ProcessorResult:
        if not self.rules:
            return ProcessorResult(
                text=sentence,
                metadata={
                    "domain_code": "misc",
                    "domain_name": "Miscellaneous",
                    "source": "rule_based"
                }
            )

        s_lower = sentence.lower()

        for code, entry in self.rules.items():
            if any(k in s_lower for k in entry["keywords"]):
                domain_name = entry["name"]
                logging.debug(f"[DomainClassifier] Matched domain '{domain_name}' for: {sentence[:80]}...")
                return ProcessorResult(
                    text=sentence,
                    metadata={
                        "domain_code": code,
                        "domain_name": domain_name,
                        "source": "rule_based",
                        "confidence": 1.0  # placeholder, can adjust later
                    }
                )

        # fallback
        misc_entry = self.rules.get("misc", {"name": "Miscellaneous"})
        return ProcessorResult(
            text=sentence,
            metadata={
                "domain_code": "misc",
                "domain_name": misc_entry["name"],
                "source": "rule_based",
                "confidence": 0.0
            }
        )

# Factory
class ProcessorFactory:
    registry = {
        "QuoteNormalizer": QuoteNormalizer,
        "DotCleaner": DotCleaner,
        "GujaratiFilter": GujaratiFilter,
        "WordCountFilter": WordCountFilter,
        "TruncatedSentenceFilter": TruncatedSentenceFilter,
        "BalancedQuotesFilter": BalancedQuotesFilter,
        "PatternRejector": PatternRejector,
        "SkipRootText": SkipRootText,
        "DomainClassifier": DomainClassifier
    }

    @classmethod
    def build_processors(cls, config):
        processors = []
        for name, params in config.items():
            if name not in cls.registry:
                logging.warning(f"Unknown processor: {name}, skipping")
                continue
            klass = cls.registry[name]
            if isinstance(params, dict):
                processors.append(klass(**params))
            else:
                processors.append(klass())
        return processors

class SentenceSplitterFactory:
    @staticmethod
    def build(tokenizer_conf):
        ttype = tokenizer_conf.get("type", "regex")
        lang = tokenizer_conf.get("lang", "gu")

        if ttype == "indic":
            # Lazy import
            def splitter(text):
                try:
                    from indicnlp.tokenize.sentence_tokenize import sentence_split
                    return sentence_split(text, lang=lang)
                except Exception as e:
                    logging.warning(f"Indic NLP failed, fallback to regex: {e}")
                    return [s.strip() for s in re.split(r'(?<=[।?!\.])', text) if s.strip()]
            return splitter

        elif ttype == "stanza":
            # Lazy load stanza pipeline (only once)
            _nlp = {"pipe": None}
            def splitter(text):
                try:
                    if _nlp["pipe"] is None:
                        import stanza
                        _nlp["pipe"] = stanza.Pipeline(lang=lang, processors="tokenize", use_gpu=True)
                    doc = _nlp["pipe"](text)
                    return [s.text for s in doc.sentences]
                except Exception as e:
                    logging.warning(f"Stanza failed, fallback to regex: {e}")
                    return [s.strip() for s in re.split(r'(?<=[।?!\.])', text) if s.strip()]
            return splitter

        else:  # regex fallback
            def splitter(text):
                return [s.strip() for s in re.split(r'(?<=[।?!\.])', text) if s.strip()]
            return splitter



