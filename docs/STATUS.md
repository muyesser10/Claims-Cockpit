# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 devam ediyor. api + masking + veri üreteci hazır. 6 servis tanımlı ama worker boş döngü, web entry point'siz.
- **Aktif sprint:** Sprint 1
- **Repo durumu:** api + şema + migration + ingest/claims + masking v1 çalışıyor. Compose'a worker/web/ollama servisleri eklendi ama worker kuyruk tüketmiyor, web iskeleti eksik.
- **Son büyük olay:** Masking v1 (PR #8), sentence_splitter (PR #4), gt_generator şemaya uyarlandı (PR #7), compose servisleri (PR #6) merge edildi.
- **Sıradaki iş (BE):** web/ Vite iskeleti (S1-13) + worker/main.py'yi gerçek kuyruk tüketicisine çevirmek (nursena ile).

---

## HAZIR OLANLAR

- [x] Dizin yapısı (scaffold)
- [x] `docker-compose.yml` — 6 servis tanımlı (db+redis healthy); **worker boş döngü**, **web entry point'siz** (temiz makinede web patlar)
- [x] `.env.example` + `.env` (lokal)
- [x] CI (ruff + gitleaks)
- [x] `CLAUDE.md`, `docs/STATUS.md`, `CODEOWNERS`
- [x] **`schemas/claim.json`** — damage_type final (8 değer), source_references offset yapılı, status sistem alanı, city/district, ISO tarih, nullable number
- [x] **Alembic migration** — 6 tablo + external_ref (VECTOR 384); tek head, çakışma yok
- [x] **SQLAlchemy modelleri** + senkron DB session
- [x] **`/health`**, **`/ingest`** (external_ref + received_at override), **`/claims`** (status/urgency filtre + sayfalama), **`/claims/{id}`** (detay)
- [x] Redis client + kuyruk (`claims:incoming`)
- [x] Pydantic modelleri
- [x] **Masking v1** (`worker/masking/`) — regex (TC/phone/plate/IBAN) + isim sözlüğü v0 (~42) + `mask_all` pipeline + testler — @bariss9
- [x] `worker/parser/sentence_splitter` — Türkçe kısaltma/ondalık koruyan bölücü — @muyesser10
- [x] `data/gt_generator.py` — claim.json uyumlu GT üreteci (İngilizce alanlar, TR PII, yaralanma→kritik) — @muyesser10

## HENÜZ YAPILMADI

- [ ] **worker/main.py gerçek Redis tüketicisi** (S1-5) — @nursenakyga. Şu an time.sleep döngüsü; masking/sentence_splitter yazıldı ama çağrılmıyor. **Sprint 1 "uçtan uca" hedefinin en kritik boşluğu.**
- [ ] **web/ Vite entry point** (S1-13) — @bariss9/@nursenakyga. index.html, vite.config.ts, src/main.tsx yok → compose web servisi patlar.
- [ ] **Ham liste ekranı (S1-8)** — @bariss9, web iskeletine bağlı
- [ ] **data/ text_generator** — @muyesser10. GT kayıtları var ama okunacak ihbar metni yok (damage_description None). Üretilmiş jsonl henüz yok.
- [ ] **LLM router (S1-15)** — @Cagri12345. worker/llm_router yok, prompts/ boş. Tek satır kod yok.
- [ ] **eval/ (S1-9)** — @MehmetTayyip. feature/ds-analiz-kurulum branch'inde var ama MERGE BLOKERİ (aşağıya bak).
- [ ] isim sözlüğü 5K'ya genişletme + Türkçe karakter normalizasyonu (Sprint 2 — masking v2)
- [ ] source_references offset hesabı (worker pipeline gelince)
- [ ] `schemas/claim.json` nihai "dondu" işareti

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca  —  DURUM: devam ediyor
- [x] compose 6 servis tanımlı (worker/web içerik eksik)
- [x] FastAPI iskelet + `/health`
- [x] `schemas/claim.json`
- [x] Alembic migration (VECTOR 384 + external_ref)


- [x] `/ingest` + `/claims` + `/claims/{id}`
- [x] **Masking v1 (S1-4)**
- [x] GT üreteci (S1-1)
- [ ] Worker kuyruk tüketici pipeline (S1-5) — **en kritik, uçtan uca bunu bekliyor**
- [ ] LLM router (S1-15)
- [ ] web/ Vite iskeleti + Pano (S1-13/S1-8)
- [ ] text_generator (ihbar metinleri)
- [x] Türkçe cümle bölücü (S1-3)
- [x] e-posta üreteci (S1-2)

- [ ] Sprint 1 demo



### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: başlamadı
### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| Uçtan uca demo | worker/main.py kuyruk tüketicisi (masking'i çağıracak) | @nursenakyga (S1-5) | masking hazır, pipeline bekliyor |
| Frontend ekranları | web/ Vite iskeleti | @bariss9/@nursenakyga (S1-13) | package.json var, entry point yok |
| eval çalışması | GT metinleri (text_generator) | @muyesser10 | GT kayıtları var, metin yok |
| Backend ikilisi | LLM router | @Cagri12345 | hiç başlamadı |
| **MERGE BLOKERİ** | **eval kodu ↔ claim.json alan adı uyuşmazlığı** | **@MehmetTayyip** | **DS branch Türkçe alan adı kullanıyor (police_no/plaka), claim.json İngilizce. Eval GT'yi okuyamaz. Standup'ta çözülmeli.** |

---

## BİLİNEN SORUNLAR / RİSKLER

- **DS branch (feature/ds-analiz-kurulum) merge blokeri:** (1) Türkçe alan adları (dil kararı İngilizceydi), (2) eval/ → analiz/ yeniden adlandırılmış (CLAUDE.md dizin sahipliğine aykırı), (3) pandas/scikit-learn requirements'ta yok (CI patlar). Merge öncesi standup.
- **web servisi temiz makinede patlar:** entry point dosyaları eksik. S1-13 bunu çözecek.
- worker `depends_on` `service_started` (api'deki `service_healthy` değil); pipeline yazılınca DB hazır olmadan bağlanma riski — @nursenakyga.
- `.env.example` `postgresql://` ile başlıyor; kod `+psycopg`'ye çeviriyor. İleride düzeltme ekiple konuşulacak.
- Yerel Postgres çakışması (bariss9): db override ile 5433'te (kişisel).
- isim sözlüğü v0 Türkçe karaktersiz; "Hüseyin" eşleşmez — Sprint 2.
- Groq rate limit — router Gemini fallback devrede olmalı.

---

## KARAR GEÇMİŞİ (kısa)

- İsimler İngilizce (endpoint/kod/dosya/**alan adları**); yorumlar İngilizce; prompt Türkçe; config ASCII.
- claim.json: damage_type 8 değer; source_references offset'li {quote,start,end}; status sistem alanı; city/district; estimated_amount nullable number; incident_date ISO.
- external_ref: GT eşleştirme için ingest'e opsiyonel alan. received_at override: GT'de sabit zaman.
- Masking: regex önce, isim sözlüğü sonra; plaka 1-3 harf; v0 sözlük ~42 isim.
- Sıfır maliyet: Groq+Gemini+Ollama; embedding yerel 384. SQLAlchemy senkron (psycopg3); Python 3.11.

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*