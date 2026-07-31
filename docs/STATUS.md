# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 uçtan uca çalışıyor. api + masking + veri üreteci + worker pipeline + web (Pano canlı liste) hazır.
- **Aktif sprint:** Sprint 1 (bitişe yakın). Sprint 2'den bir DE işi zaten merge oldu (S2-DE-1).
- **Repo durumu:** 6 servis ayakta, uçtan uca akıyor. /ingest → Redis → worker (5 adım) → /claims → Pano ekranı (3sn polling) çalışıyor.
- **Son büyük olay:** Worker gerçek pipeline (PR #12), OpenAI LLM istemcisi + ADR-001, Pano ham liste ekranı (S1-8), masking hatalarının audit_trail'e yazılması.
- **Sıradaki iş (BE):** Sorun/borç temizliği — CLAUDE.md §2/§4'ün ADR-001'e göre güncellenmesi (router artık üçlü değil), source_references offset, DS merge blokerinin çözümü.

---

## HAZIR OLANLAR

- [x] Dizin yapısı (scaffold)
- [x] `docker-compose.yml` — 6 servis tanımlı (db+redis healthy); worker gerçek pipeline; web bind mount + anonymous node_modules volume (live-reload çalışıyor)
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
- [x] **Masking hata izleme** — `mask_all` başarısızsa `audit_trail`'e `masking_error` step yazılıyor (sessiz fallback kapatıldı) — @bariss9
- [x] `worker/parser/sentence_splitter` — Türkçe kısaltma/ondalık koruyan bölücü — @muyesser10
- [x] `data/gt_generator.py` — claim.json uyumlu GT üreteci (İngilizce alanlar, TR PII, yaralanma→kritik) — @muyesser10
- [x] `data/text_generator.py` — e-posta üreteci (email kanalı), 5 sözlük, JSONL çıktı (emails.jsonl + enriched GT) — @muyesser10
- [x] `replay/replay.py` — emails.jsonl → /ingest replay (dry-run + gerçek mod, gt_id/received_at eşleme) — @muyesser10
- [x] `worker/extraction/schema.py` — extraction çıktı sözleşmesi (Pydantic): claim.json alanları + kanıt/güven/eksik alan blokları; claim.json senkron testi — @Cagri12345
- [x] **worker/main.py gerçek Redis tüketicisi + pipeline (S1-5)** — `claims:incoming`'den BRPOP ile id çekiyor, `masking` → deterministik yaralanma kuralıyla `classification` → `Claim` oluşturup `routing` adımlarını çalıştırıyor, her adımda `audit_trail`'e gerçek satır yazıyor — @nursenakyga
- [x] `worker/llm/client.py` — OpenAI istemcisi (instructor + Pydantic): iki kademe, seed, zaman aşımı, iki katmanlı retry, denetim izi logu — @Cagri12345. **NOT: pipeline'a henüz bağlı değil** — classification hâlâ deterministik keyword kuralı.
- [x] **Canlı LLM doğrulaması + şema optimizasyonu** — gerçek gpt-4o çağrısı yapıldı: `create_with_completion` doğrulandı, `source_references` düz metne çevrildi. Mesaj başına 3 istek → 1, 7.343 → 1.554 token, 14,8 → 8,7 sn — @Cagri12345
- [x] **web/ Vite entry point** (S1-13) — @bariss9/@nursenakyga. index.html, vite.config.ts, src/main.tsx
- [x] **Ham liste ekranı (S1-8)** — @bariss9. Pano'da claims tablosu, urgency'e göre sıralama + kritik/yüksek vurgu, `/api/claims` 3sn polling (`useClaims` hook + `ClaimsTable` component)

## HENÜZ YAPILMADI

- [ ] **extraction prompt (S1-15)** — @Cagri12345. Şema ve LLM istemcisi hazır; sırada `prompts/extraction_v1.txt`. prompts/ hâlâ boş.
- [ ] **LLM istemcisini pipeline'a bağlama** — client.py hazır ama worker onu çağırmıyor; classification/extraction hâlâ deterministik/eksik.
- [ ] **eval/ (S1-9)** — @MehmetTayyip. feature/ds-analiz-kurulum branch'inde var ama MERGE BLOKERİ (aşağıya bak).
- [ ] **Çalışan fallback katmanı** — OpenAI birincil, Groq/Gemini/Ollama config'i duruyor ama kod yok (ADR-001 açık maddesi, @bariss9 + @nursenakyga).
- [ ] isim sözlüğü 5K'ya genişletme + Türkçe karakter normalizasyonu (Sprint 2 — masking v2)
- [ ] source_references offset hesabı (extraction pipeline'a bağlanınca)
- [ ] **CLAUDE.md §2/§4 güncellemesi** — hâlâ eski üçlü router'ı anlatıyor; ADR-001'e göre güncellenmeli 
- [ ] `schemas/claim.json` nihai "dondu" işareti

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca  —  DURUM: bitişe yakın
- [x] compose 6 servis (hepsi çalışıyor)
- [x] FastAPI iskelet + `/health`
- [x] `schemas/claim.json`
- [x] Alembic migration (VECTOR 384 + external_ref)
- [x] `/ingest` + `/claims` + `/claims/{id}`
- [x] **Masking v1 (S1-4)**
- [x] GT üreteci (S1-1)
- [x] Worker kuyruk tüketici pipeline (S1-5)
- [ ] LLM router (S1-15) — ADR-001 ile OpenAI istemcisine dönüştü; client.py var, pipeline'a bağlama kaldı
- [x] web/ Vite iskeleti (S1-13)
- [x] Pano ham liste ekranı (S1-8)
- [x] text_generator / e-posta üreteci (S1-2)
- [x] Türkçe cümle bölücü (S1-3)
- [x] replay v1 (S1-10) — emails.jsonl → /ingest
- [ ] eval (S1-9) — DS merge blokeri
- [ ] Sprint 1 demo

### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: erken başladı
- [x] S2-DE-1 — counterparty_exists artık damage_type'a bağlı (merge oldu) — @muyesser10
- [ ] Diğer Sprint 2 işleri henüz açılmadı

### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| Backend ikilisi | LLM istemcisinin pipeline'a bağlanması | @Cagri12345 | client.py hazır, worker entegrasyonu sırada |
| Backend ikilisi | extraction (prompt + extractor) | @Cagri12345 | şema + istemci merge edildi, canlı doğrulandı; sırada `prompts/extraction_v1.txt` |
| source_references offset | extraction adımının pipeline'a girmesi | @Cagri12345 / BE | quote üretiliyor, start/end hesabı yok |
| **MERGE BLOKERİ** | **eval kodu ↔ claim.json alan adı uyuşmazlığı** | **@MehmetTayyip** | **DS branch Türkçe alan adı kullanıyor (police_no/plaka), claim.json İngilizce. Eval GT'yi okuyamaz. Standup'ta çözülmeli.** |

---

## BİLİNEN SORUNLAR / RİSKLER

- **DS branch (feature/ds-analiz-kurulum) merge blokeri:** (1) Türkçe alan adları (dil kararı İngilizceydi), (2) eval/ → analiz/ yeniden adlandırılmış (CLAUDE.md dizin sahipliğine aykırı), (3) pandas/scikit-learn requirements'ta yok (CI patlar). Merge öncesi standup.
- **CLAUDE.md §2/§4 güncel değil:** ADR-001 üçlü router yerine OpenAI'ye geçti ama CLAUDE.md hâlâ eskiyi anlatıyor. Yanlış yönlendirme riski. @bariss9 güncelleyecek.
- worker `depends_on` `service_started` (api'deki `service_healthy` değil); DB hazır olmadan bağlanma riski — @nursenakyga.
- `.env.example` `postgresql://` ile başlıyor; kod `+psycopg`'ye çeviriyor. İleride düzeltme ekiple konuşulacak.
- Yerel Postgres çakışması (bariss9): db override ile 5433'te (kişisel).
- isim sözlüğü v0 Türkçe karaktersiz; "Hüseyin" eşleşmez — Sprint 2.
- OpenAI maliyeti ölçüldü: extraction mail başına ~1.550 token / ~8,7 sn (gpt-4o, tek istek). 46 maillik eval koşusu ~$0.20. `DEMO_OFFLINE` için yerel model yok, kayıtlı fixture gerekiyor (Sprint 4). Çalışan fallback katmanı henüz yazılmadı, sadece anahtarlar duruyor. Bkz. ADR-001.
- `data/dictionaries/opening_templates.txt` 12. satırda "dün" sabit yazılı ve gövdedeki gerçek tarihle çelişiyor — 46 mailin 5'i (GT-000001/3/57/76/99). `make_date_phrase` doğru çalışıyor, sorun yalnız bu şablonda. @muyesser10'a iletildi.
- `injury` / `counterparty_exists`: metin sessizse GT `false`, extraction sözleşmesi `null` diyor. Eval normalizasyonunda `null` = `false` eşlenecek; şema değişmiyor (bilgi kaybı olmasın).

---

## KARAR GEÇMİŞİ (kısa)

- İsimler İngilizce (endpoint/kod/dosya/**alan adları**); yorumlar İngilizce; prompt Türkçe; config ASCII.
- claim.json: damage_type 8 değer; source_references offset'li {quote,start,end}; status sistem alanı; city/district; estimated_amount nullable number; incident_date ISO.
- external_ref: GT eşleştirme için ingest'e opsiyonel alan. received_at override: GT'de sabit zaman.
- Masking: regex önce, isim sözlüğü sonra; plaka 1-3 harf; v0 sözlük ~42 isim. Hata olursa audit_trail'e masking_error yazılıyor.
- extraction `source_references`: LLM'den düz alıntı metni (`dict[str, str]`). `{quote,start,end}` nihai kayıt şekli olarak `claim.json`'da kalıyor, offset'i pipeline hesaplar. Ölçüm: sarmalayıcı nesne mesaj başına 2 fazla LLM çağrısına yol açıyordu.
- LLM sağlayıcı: OpenAI iki kademe (gpt-4o-mini / gpt-4o) — ADR-001. Eski sağlayıcı anahtarları `.env.example`'da fallback başlığı altında duruyor, kod okumuyor. **Embedding yerel 384 (değişmedi).** SQLAlchemy senkron (psycopg3); Python 3.11.
- web servisi: bind mount + anonymous node_modules volume ile live-reload (S1-8 sırasında eklendi).

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*