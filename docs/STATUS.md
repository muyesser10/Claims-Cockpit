# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 devam ediyor. Backend (api) katmanı ayakta ve çalışıyor.
- **Aktif sprint:** Sprint 1
- **Repo durumu:** api servisi + veritabanı şeması + ingest/claims endpoint'leri hazır. external_ref (GT eşleştirme) eklendi. Worker/web/ollama henüz yok.
- **Son büyük olay:** api iskeleti, Alembic migration (6 tablo + external_ref, VECTOR 384), /ingest + /claims çalışıyor. LLM Engineer istekleri (external_ref, damage_type, source offset, received_at override) uygulandı.
- **Sıradaki iş (BE):** Masking v1 (regex + basit isim listesi).

---

## HAZIR OLANLAR

- [x] Dizin yapısı (scaffold)
- [x] `docker-compose.yml` — db + redis + **api çalışıyor**; worker/web/ollama hâlâ bekleniyor -> @nursenakyga
- [x] `.env.example` + `.env` (lokal)
- [x] CI (ruff + gitleaks) + izin düzeltmesi (pull-requests read)
- [x] `CLAUDE.md`, `docs/STATUS.md`, `CODEOWNERS`
- [x] **`schemas/claim.json`** — damage_type final (collision|single_vehicle|glass|hail|fire|theft|animal|other), source_references offset yapılı ({quote,start,end}), status sistem alanı, city/district, ISO tarih, nullable number
- [x] **Alembic migration** — 6 tablo + `external_ref` kolonu: raw_messages, claims, audit_trail, mask_mappings, claim_embeddings (**VECTOR 384**), users
- [x] **SQLAlchemy modelleri** + senkron DB session
- [x] **`/health`**, **`/ingest`** (external_ref + received_at override destekli), **`/claims`** endpoint'leri
- [x] Redis client + kuyruk (`claims:incoming`)
- [x] Pydantic modelleri

## HENÜZ YAPILMADI

- [ ] **Masking v1** (regex + isim listesi) — @bariss9, sıradaki
- [ ] source_references offset hesabı (pipeline `text.find(quote)` — worker gelince)
- [ ] Worker iskeleti + pipeline @nursenakyga — received_at'i extraction'a geçirecek
- [ ] LLM router @Cagri12345
- [ ] Sentetik veri + replay  @muyesser10
- [ ] `schemas/claim.json` nihai "dondu" işareti (external_ref eklendiği için hâlâ oturuyor)

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca  —  DURUM: devam ediyor
- [x] compose api servisi, api+db+redis healthy
- [x] FastAPI iskelet + `/health`
- [x] `schemas/claim.json` (LLM+DE geri bildirimiyle güncel)
- [x] Alembic migration (VECTOR 384 + external_ref)
- [x] `/ingest` + `/claims` endpoint'leri
- [x] schemas/claim.json donduruldu (Gün 2)
- [x] gt_generator gerçek şemayla (S1-1)
- [x] Türkçe cümle bölücü (S1-3)
- [x] e-posta üreteci (S1-2)
- [ ] Masking regex + isim sözlüğü v0 (BE — sıradaki)
- [ ] Worker pipeline v0 (Dev2)
- [ ] LLM router entegre (LLM Engineer)
- [ ] Vite + Pano iskelet
- [ ] Sprint 1 demo



### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: başlamadı
### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| Backend ikilisi | LLM router | @Cagri12345 | bekliyor |
| Backend ikilisi | Sentetik test verisi + replay | @muyesser10 | bekliyor |
| DS + LLM | Worker pipeline (received_at → extraction, offset hesabı) | @nursenakyga | bekliyor |

---

## BİLİNEN SORUNLAR / RİSKLER

- `.env.example` `DATABASE_URL` `postgresql://` ile başlıyor; kod psycopg v3 için `+psycopg`'ye çeviriyor (database.py + env.py `.replace`). İleride `.env.example`'ı doğrudan düzeltmek ekiple konuşulacak.
- Yerel Postgres çakışması (bariss9): db `docker-compose.override.yml` ile 5433'te (kişisel).
- Groq rate limit — router Gemini fallback devrede olmalı.

---

## KARAR GEÇMİŞİ (kısa)

- İsimler İngilizce (endpoint/kod/dosya); yorumlar İngilizce; prompt Türkçe; config ASCII.
- claim.json: damage_type 8 değer + single_vehicle + glass; source_references offset'li {quote,start,end} (offset'i pipeline hesaplar, LLM sadece quote verir); status sistem alanı; city/district; estimated_amount nullable number; incident_date ISO.
- external_ref: GT eşleştirme için ingest'e opsiyonel alan (raw_messages.external_ref). received_at override: GT'de sabit zaman verilebilir (eval tekrar edilebilirliği).
- Sıfır maliyet: Groq+Gemini+Ollama; embedding yerel 384.
- SQLAlchemy senkron (psycopg3); Python 3.11; migration hakkı backend ikilisinde.

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*