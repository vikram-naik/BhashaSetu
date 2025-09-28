# 🌉 BhashaSetu (भाषा सेतु)

**BhashaSetu** means *“Bridge of Languages”* in Sanskrit/Hindi.  
It is a **translation warehouse** — a structured database and tooling ecosystem for collecting, normalizing, and serving bilingual & monolingual corpora with provenance, metrics, and versioning.  

The goal is to create a **foundation for high-quality English ↔ Japanese machine translation** (and extensible to other languages in future).

---

## 🚀 Vision

- **Central Repository**: Store sentences, translations, sources, domains, and evaluation metrics in one normalized, auditable database.  
- **Provenance First**: Every text linked back to its origin — book, tweet, video, corpus — with licensing & authorship preserved.  
- **Human + Machine**: Store both human and synthetic translations, clearly marked.  
- **Versioned & Auditable**: Support historical edits, multiple versions, and active/archived status.  
- **Benchmark-Ready**: Attach COMET, chrF, BLEU, MQM or qualitative scores to each translation for transparent evaluation.  
- **Accessible**: Future UI for browsing, searching, editing, and contributing translations.  

---

## 🗄️ Database Schema Overview

Key entities in **BhashaSetu**:

- **Sentence**: Atomic text in a given language.  
- **Source**: Origin of the text (book, tweet, video, article, etc.).  
- **Domain**: Broad category (spoken, news, literary, technical).  
- **Translation**: Link between source & target sentences with method (human/MT/LLM).  
- **Method Lookup**: Registry of translation systems or annotators.  
- **Metric**: Registry of evaluation metrics (BLEU, chrF, COMET, MQM).  
- **Translation Metric**: Scores assigned to a translation (numeric or qualitative).  

Schema supports:  
- Multiple references per source sentence.  
- Multiple translation methods for the same sentence pair.  
- Versioning (`version`, `is_active`, `last_updated_on`).  
- Audit trail for every entity.

📌 See [`/schema`](schema/) for full Postgres DDL.

---

## 📂 Repository Structure
``` text
BhashaSetu/
│
├── schema/ # SQL DDL + migrations
│ └── bhashasetu.sql
│
├── ingestion/ # Scripts to fetch & clean corpora (OPUS, JParaCrawl, etc.)
│ └── ingest_opus.py
│
├── ui/ # Future web UI for browsing, editing, annotating
│ └── (placeholder)
│
├── docs/ # Documentation & diagrams
│ └── ER-diagram.png
│
└── README.md # Project overview
```

---

## 🛠️ Roadmap

**Phase 1 – Core DB**
- [x] Design normalized schema (sentences, sources, domains, translations, metrics).  
- [ ] Implement Postgres migrations + seed reference data.  
- [ ] Load initial corpora (JParaCrawl, TED, JESC, KFTT, Tatoeba).  

**Phase 2 – Ingestion & Cleaning**
- [ ] Scripts to normalize, deduplicate, and align corpora.  
- [ ] Back-translation pipeline (monolingual → synthetic parallel).  

**Phase 3 – Evaluation**
- [ ] Integrate COMET + chrF scoring for stored translations.  
- [ ] Store human MQM evaluations.  

**Phase 4 – UI**
- [ ] Web interface to search, filter, and browse corpus.  
- [ ] Editing + annotation UI for human contributors.  

**Phase 5 – Model Training**
- [ ] Export clean parallel data subsets for Marian/mBART fine-tuning.  
- [ ] Release open models trained on BhashaSetu.  

---

## 📜 License

- Schema & ingestion scripts: MIT License.  
- Data: respect **source corpus licenses** (OPUS, JParaCrawl, TED, etc.).  
- Always include attribution when redistributing aligned corpora.

---

## 🙌 Contributing

We welcome contributions to:  
- Add ingestion scripts for new corpora.  
- Add new metrics or evaluation scripts.  
- Expand UI features.  

---

✨ **BhashaSetu = Building the bridge of languages, one sentence at a time.**
