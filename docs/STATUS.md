# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 devam ediyor. api + masking + veri üreteci + worker pipeline hazır. web hâlâ entry point'siz.
- **Aktif sprint:** Sprint 1
- **Repo durumu:** api + şema + migration + ingest/claims + masking v1 + worker (mask→classify→route, audit_trail'e yazıyor) uçtan uca çalışıyor. web iskeleti eksik kalan tek boşluk.
- **Son büyük olay:** Masking v1 (PR #8), sentence_splitter (PR #4), gt_generator şemaya uyarlandı (PR #7), compose servisleri (PR #6) merge edildi.
- **Sıradaki iş (BE):** web/ Vite iskeleti (S1-13) — worker artık kuyruk tüketiyor, uçtan uca demo bloke değil.

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
- [x] `data/text_generator.py` — e-posta üreteci (email kanalı), 5 sözlük, JSONL çıktı (emails.jsonl + enriched GT) — @muyesser10
- [x] `replay/replay.py` — emails.jsonl → /ingest replay (dry-run + gerçek mod, gt_id/received_at eşleme) — @muyesser10
- [x] `worker/extraction/schema.py` — extraction çıktı sözleşmesi (Pydantic): claim.json alanları + kanıt/güven/eksik alan blokları; claim.json senkron testi — @Cagri12345
- [x] **worker/main.py gerçek Redis tüketicisi + pipeline (S1-5)** — `claims:incoming`'den BRPOP ile id çekiyor, `masking` → deterministik yaralanma kuralıyla `classification` → `Claim` oluşturup `routing` adımlarını çalıştırıyor, her adımda `audit_trail`'e gerçek satır yazıyor — @nursenakyga
- [x] `worker/llm/client.py` — OpenAI istemcisi (instructor + Pydantic): iki kademe, seed, zaman aşımı, iki katmanlı retry, denetim izi logu — @Cagri12345

## HENÜZ YAPILMADI

- [ ] **web/ Vite entry point** (S1-13) — @bariss9/@nursenakyga. index.html, vite.config.ts, src/main.tsx yok → compose web servisi patlar.
- [ ] **Ham liste ekranı (S1-8)** — @bariss9, web iskeletine bağlı
- [ ] **extraction prompt (S1-15)** — @Cagri12345. Şema ve LLM istemcisi hazır; sırada `prompts/extraction_v1.txt`. prompts/ hâlâ boş.
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
- [x] Worker kuyruk tüketici pipeline (S1-5)
- [ ] LLM router (S1-15)
- [ ] web/ Vite iskeleti + Pano (S1-13/S1-8)
- [x] text_generator / e-posta üreteci (S1-2)
- [x] Türkçe cümle bölücü (S1-3)
- [x] e-posta üreteci (S1-2)
- [x] replay v1 (S1-10) — emails.jsonl → /ingest

- [ ] Sprint 1 demo



### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: başlamadı
### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|

| Frontend ekranları | web/ Vite iskeleti | @bariss9/@nursenakyga (S1-13) | package.json var, entry point yok |
| eval çalışması | GT metinleri (text_generator) | @muyesser10 | GT kayıtları var, metin yok |
| Backend ikilisi | LLM istemcisi + extraction | @Cagri12345 | şema hazır, istemci sırada |
| **MERGE BLOKERİ** | **eval kodu ↔ claim.json alan adı uyuşmazlığı** | **@MehmetTayyip** | **DS branch Türkçe alan adı kullanıyor (police_no/plaka), claim.json İngilizce. Eval GT'yi okuyamaz. Standup'ta çözülmeli.** |

---

## BİLİNEN SORUNLAR / RİSKLER

- **DS branch (feature/ds-analiz-kurulum) merge blokeri:** (1) Türkçe alan adları (dil kararı İngilizceydi), (2) eval/ → analiz/ yeniden adlandırılmış (CLAUDE.md dizin sahipliğine aykırı), (3) pandas/scikit-learn requirements'ta yok (CI patlar). Merge öncesi standup.
- **web servisi temiz makinede patlar:** entry point dosyaları eksik. S1-13 bunu çözecek.
- worker `depends_on` `service_started` (api'deki `service_healthy` değil); pipeline yazılınca DB hazır olmadan bağlanma riski — @nursenakyga.
- `.env.example` `postgresql://` ile başlıyor; kod `+psycopg`'ye çeviriyor. İleride düzeltme ekiple konuşulacak.
- Yerel Postgres çakışması (bariss9): db override ile 5433'te (kişisel).
- isim sözlüğü v0 Türkçe karaktersiz; "Hüseyin" eşleşmez — Sprint 2.
- OpenAI maliyeti/kotası — eval koşusu toplu çağrı yapar. `DEMO_OFFLINE` için artık yerel model yok, kayıtlı fixture gerekiyor (Sprint 4). Çalışan fallback katmanı henüz yazılmadı, sadece anahtarlar duruyor. Bkz. ADR-001.

---

## KARAR GEÇMİŞİ (kısa)

- İsimler İngilizce (endpoint/kod/dosya/**alan adları**); yorumlar İngilizce; prompt Türkçe; config ASCII.
- claim.json: damage_type 8 değer; source_references offset'li {quote,start,end}; status sistem alanı; city/district; estimated_amount nullable number; incident_date ISO.
- external_ref: GT eşleştirme için ingest'e opsiyonel alan. received_at override: GT'de sabit zaman.
- Masking: regex önce, isim sözlüğü sonra; plaka 1-3 harf; v0 sözlük ~42 isim.
- LLM sağlayıcı: OpenAI iki kademe (gpt-4o-mini / gpt-4o) — ADR-001. Eski sağlayıcı anahtarları `.env.example`'da fallback başlığı altında duruyor, kod okumuyor. **Embedding yerel 384 (değişmedi).** SQLAlchemy senkron (psycopg3); Python 3.11.

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*