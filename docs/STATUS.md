# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut). Uzun
> geçmiş yazma; "şu an ne durumda + sırada ne var + neler bloke" yeterli. Detaylı günlük
> kayıt için `docs/standups/` kullan.

---

## ÖZET (bir bakışta)

- **Faz:** Kurulum tamamlandı, Sprint 1 henüz **başlamadı**.
- **Aktif sprint:** — (Sprint 1 başlamak üzere)
- **Repo durumu:** Saf iskelet (scaffold). Gerçek kod yok; klasörler `.gitkeep` ile boş.
- **Son büyük olay:** Scaffold + CI + compose + .env.example kuruldu (repo sahibi tarafından).
- **Sıradaki iş:** Sprint 1 Gün 1 — compose'da api/worker/web servislerini aç, FastAPI iskelet + `/health`, Vite kurulum.

---

## HAZIR OLANLAR (scaffold)

- [x] Dizin yapısı (api, worker, web, migrations, prompts, data, replay, eval, schemas, monitoring, docs)
- [x] `docker-compose.yml` — db + redis tanımlı ve healthcheck'li; api/worker/web **yorum satırında** (Sprint 1'de açılacak)
- [x] `.env.example` — LLM router (Groq+Gemini+Ollama), embedding (384), DB, Redis, JWT, DEMO_OFFLINE hepsi tanımlı
- [x] `pyproject.toml` — ruff (line-length 100, py311) + pytest yapılandırması
- [x] `requirements.txt` — temel bağımlılıklar (fastapi, sqlalchemy, alembic, psycopg3, redis, httpx)
- [x] CI (`.github/workflows/ci.yml`) — ruff lint + format + pytest + gitleaks secret taraması
- [x] Şablonlar — ADR, standup, issue (bug/task), PR template
- [x] `CLAUDE.md` + `docs/STATUS.md` (bu dosya)
- [x] `CODEOWNERS` gerçek kullanıcı adlarıyla dolduruldu (5 kişi)

## HENÜZ YAPILMADI

- [ ] `schemas/claim.json` **oluşturulmadı** (Sprint 1 Gün 2 şema oturumunda donacak)
- [ ] Hiçbir Python/TS kodu yazılmadı
- [ ] Migration yok
- [ ] Prompt'lar yok
- [ ] Sentetik veri yok

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca  —  DURUM: başlamadı
Hedef: `docker compose up` ile tüm servisler ayakta; `/ingest` → Redis → worker pipeline (v0)
→ Postgres → Pano'da görünür. Şema Gün 2'de donar.

- [ ] compose api/worker/web servisleri açıldı, hepsi healthy
- [ ] FastAPI iskelet + `/health`
- [ ] Vite + shadcn + Layout + 5 rota
- [ ] `schemas/claim.json` donduruldu (Gün 2)
- [ ] Alembic migration 0001 (VECTOR(384) dahil)
- [ ] `/ingest` + `/ihbarlar` endpoint'leri
- [ ] worker pipeline v0 (masking→classification→extraction→validation stub'ları)
- [ ] LLM router entegre, ilk gerçek çağrılar
- [ ] Pano iskelet, canlı veri akıyor
- [ ] Sprint 1 demo

### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: başlamadı
### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

Kim kimi bekliyor (güncel tut — biri teslim edince satırı kaldır/işaretle):

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| Backend ikilisi | LLM router (`worker/llm_router`) + adapter'ler | LLM Engineer | bekliyor |
| Backend ikilisi | Sentetik test verisi (20-30 metin) | Data Engineer | bekliyor |
| LLM + DS | `schemas/claim.json` donması | Backend ikilisi (Gün 2 oturumu) | bekliyor |
| Frontend | `/istatistik/ozet` OpenAPI şeması | Backend (Sprint 2) | henüz sırada değil |
| DS | `denetim_izi` tablosuna erişim | Backend | henüz sırada değil |

---

## BİLİNEN SORUNLAR / RİSKLER

- Groq rate limit (30 req/dk) — yoğun eval'de router'ın Gemini fallback'i devrede olmalı.
- Windows kullanıcı adında Türkçe karakter olan geliştiricilerde SSH sorunu olabildi; HTTPS+token veya düzgün yol ile klonlama tercih edildi.

---

## KARAR GEÇMİŞİ (kısa — detay `docs/decisions/` ADR'lerde)

- Sıfır maliyet stratejisi: bulut premium LLM yerine Groq+Gemini+Ollama üçlü router. (scaffold'da yansıtıldı)
- Embedding yerel (sentence-transformers, 384) — text-embedding değil.
- SQLAlchemy senkron (psycopg3) — async değil.
- Python 3.11.

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*
