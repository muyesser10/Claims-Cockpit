# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 devam ediyor. Backend (api) katmanı ayakta ve çalışıyor.
- **Aktif sprint:** Sprint 1
- **Repo durumu:** api servisi + veritabanı şeması + ingest/claims endpoint'leri hazır. Worker/web/ollama henüz yok.
- **Son büyük olay:** api iskeleti, Alembic migration (6 tablo, VECTOR 384), /ingest + /claims endpoint'leri çalışıyor.
- **Sıradaki iş (BE):** Masking v1 (regex + basit isim listesi) — worker'ın kullanacağı maskeleme kuralları.

---

## HAZIR OLANLAR

- [x] Dizin yapısı (scaffold)
- [x] `docker-compose.yml` — db + redis healthcheck'li; **api servisi açıldı ve çalışıyor**; worker/web/ollama hâlâ yorumlu
- [x] `.env.example` + `.env` (lokal)
- [x] CI (ruff + gitleaks) + izin düzeltmesi (pull-requests read)
- [x] `CLAUDE.md`, `docs/STATUS.md`, `CODEOWNERS` (gerçek kullanıcı adları)
- [x] **`schemas/claim.json`** — taslak hazır, Müyesser geri bildirimiyle güncellendi (damage_type eklendi, status çıkarıldı, city/district, tipler netleşti). Ekip nihai onayı bekliyor.
- [x] **Alembic migration** — 6 tablo oluştu: raw_messages, claims, audit_trail, mask_mappings, claim_embeddings (**VECTOR 384**), users
- [x] **SQLAlchemy modelleri** (`api/models/db.py`) + senkron DB session (`api/database.py`)
- [x] **`/health`** endpoint
- [x] **`/ingest`** endpoint — ham mesaj → Postgres + Redis kuyruğu (202)
- [x] **`/claims`** endpoint — sayfalı liste + tek kayıt + filtre (status/urgency)
- [x] Redis client + kuyruk (`claims:incoming`)
- [x] Pydantic request/response modelleri

## HENÜZ YAPILMADI

- [ ] **Masking v1** (regex + isim listesi) — BE, sıradaki
- [ ] Worker iskeleti + pipeline (Dev2)
- [ ] LLM router (LLM Engineer)
- [ ] Sentetik veri + replay (Data Engineer)
- [ ] `schemas/claim.json` nihai ekip onayı + "dondu" işareti

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca  —  DURUM: devam ediyor
- [x] compose api servisi açıldı, api+db+redis healthy
- [x] FastAPI iskelet + `/health`
- [x] `schemas/claim.json` taslağı
- [x] Alembic migration 0001 (VECTOR 384 dahil)
- [x] `/ingest` + `/claims` endpoint'leri
- [ ] Masking regex + isim sözlüğü v0 (BE — sıradaki)
- [ ] Worker pipeline v0 (Dev2)
- [ ] LLM router entegre (LLM Engineer)
- [ ] Vite + Pano iskelet (Sprint 2'ye kayabilir)
- [ ] Sprint 1 demo

### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: başlamadı
### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| Backend ikilisi | LLM router (`worker/llm_router`) | LLM Engineer (@Cagri12345) | bekliyor |
| Backend ikilisi | Sentetik test verisi (20-30 metin) | Data Engineer (@muyesser10) | bekliyor |
| LLM + DS | `schemas/claim.json` nihai onay + dondu | Ekip | taslak hazır, onay bekliyor |
| Backend ikilisi | worker pipeline (masking/validation'ı çağıracak) | Dev2 (@nursenakyga) | bekliyor |
| Backend ikilisi | `worker/parser/sentence_splitter` review | @muyesser10 (PR açık) | review bekliyor |

---

## BİLİNEN SORUNLAR / RİSKLER

- `.env.example`'daki `DATABASE_URL` `postgresql://` ile başlıyor; kod psycopg v3 için `postgresql+psycopg://`'ye çeviriyor (database.py + env.py'de `.replace`). İleride `.env.example`'ı doğrudan `+psycopg` yapmak ekiple konuşulacak.
- Yerel Postgres çakışması: bariss9'un makinesinde ayrı Postgres 5432'yi tutuyor; `docker-compose.override.yml` ile db 5433'e alındı (kişisel, commit'lenmez).
- Groq rate limit (30 req/dk) — yoğun eval'de router'ın Gemini fallback'i devrede olmalı.

---

## KARAR GEÇMİŞİ (kısa)

- Endpoint/dosya/kod isimleri **İngilizce**; yorumlar İngilizce; prompt'lar Türkçe; config dosyaları ASCII.
- claim.json: damage_type enum eklendi, status sistem alanı (GT'de yok), incident_location → city/district, estimated_amount nullable number, incident_date ISO string.
- Sıfır maliyet: Groq + Gemini + Ollama router; embedding yerel (384).
- SQLAlchemy senkron (psycopg3). Python 3.11 (container). Migration üretme hakkı backend ikilisinde.
- Backend+Frontend 2 kişi (domain-split).

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*