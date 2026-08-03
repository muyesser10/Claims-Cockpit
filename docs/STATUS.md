# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 bitti (eval hariç). Sprint 2 aktif — kuyruk backend + onay ekranı + validation + unmask + extraction pipeline hazır.
- **Aktif sprint:** Sprint 2. (Sprint 1'den sadece eval S1-9 açık — DS merge blokeri.)
- **Repo durumu:** 6 servis ayakta, uçtan uca akıyor. /ingest → Redis → worker (mask→classify→route→extract→validate) → /claims + /queue → Pano (donut/il barı) + Kuyruk (onay ekranı) çalışıyor.
- **Son büyük olay:** S2-7 onay kuyruğu ekranı (düzenle + onayla/reddet + diff), extraction+validation pipeline entegrasyonu, S2-8 Pano analitik.
- **Sıradaki iş (BE):** S2-5 masking v2 (5K isim). Borç: CLAUDE.md §2/§4 güncellemesi (ADR-001), DS merge blokeri.

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
- [x] **`/queue`** (S2-4 + S2-7) — insan onay kuyruğu: `GET /queue` (urgency sıralı, FIFO), `POST /queue/{id}/approve` (opsiyonel `edits` ile operatör düzenlemesi + diff audit) → approved, `POST /queue/{id}/reject` → archived; sadece in_human_review geçişi (aksi 409), audit_trail'e from/to + edits diff yazılıyor — @bariss9
- [x] Redis client + kuyruk (`claims:incoming`)
- [x] Pydantic modelleri
- [x] **Masking v1** (`worker/masking/`) — regex (TC/phone/plate/IBAN) + isim sözlüğü v0 (~42) + `mask_all` pipeline + testler — @bariss9
- [x] **Masking hata izleme** — `mask_all` başarısızsa `audit_trail`'e `masking_error` step yazılıyor (sessiz fallback kapatıldı) — @bariss9
- [x] **Unmask** (`worker/masking/unmask.py`) — extraction çıktısındaki placeholder'ları (`[PLATE_1]`) mask_mappings'ten geri açar; saf, recursive (nested dict), format-agnostik; round-trip testli — @bariss9
- [x] **Validation** (`worker/validation/validator.py`) — extraction çıktısı için 11 deterministik kural (format + yaralanma çapraz kontrol + tutarlılık), flag üretir (reddetmez); 32 test — @bariss9
- [x] **Ortak yaralanma sözlüğü** (`worker/shared/injury_terms.py`) — classification (pipeline) + validation tek kaynaktan okuyor (12 terim); Türkçe-güvenli `_normalize_tr` (büyük harf I/İ bug'ı düzeltildi, "YARALI" artık yakalanıyor) — @bariss9 (@nursenakyga onaylı)
- [x] **Onay kuyruğu ekranı (S2-7)** — @bariss9. Kuyruk sayfası: sol liste (ClaimsTable, tıklanabilir + seçili vurgu) + sağ detay paneli (`QueueDetail`). Düzenlenebilir extraction alanları (10 alan, null/false ayrımı korunuyor), validation_flags gösterimi (ilgili alanın altında), masked_text salt okunur. Onayla → değişen alanlar `edits` olarak gönderiliyor (diff audit'e); Reddet iki adımlı. `useQueue` hook (3sn polling) + `useApproveClaim`/`useRejectClaim` (ekipte ilk useMutation, invalidateQueries ile tazeleme). Gerçek veriyle test edildi (düzenle→onayla→diff audit zinciri doğrulandı).
- [x] `worker/parser/sentence_splitter` — Türkçe kısaltma/ondalık koruyan bölücü — @muyesser10
- [x] `data/gt_generator.py` — claim.json uyumlu GT üreteci (İngilizce alanlar, TR PII, yaralanma→kritik) — @muyesser10
- [x] `data/text_generator.py` — e-posta üreteci (email kanalı), 5 sözlük, JSONL çıktı (emails.jsonl + enriched GT) — @muyesser10
- [x] `replay/replay.py` — emails.jsonl → /ingest replay (dry-run + gerçek mod, gt_id/received_at eşleme) — @muyesser10
- [x] `worker/extraction/schema.py` — extraction çıktı sözleşmesi (Pydantic): claim.json alanları + kanıt/güven/eksik alan blokları; claim.json senkron testi — @Cagri12345
- [x] **worker/main.py gerçek Redis tüketicisi + pipeline (S1-5)** — `claims:incoming`'den BRPOP ile id çekiyor, `masking` → deterministik yaralanma kuralıyla `classification` → `Claim` oluşturup `routing` adımlarını çalıştırıyor, her adımda `audit_trail`'e gerçek satır yazıyor — @nursenakyga
- [x] `worker/llm/client.py` — OpenAI istemcisi (instructor + Pydantic): iki kademe, seed, zaman aşımı, iki katmanlı retry, denetim izi logu — @Cagri12345. **NOT: extraction üzerinden pipeline'a bağlı** (`worker/extraction/extractor.py` bunu kullanıyor) — classification hâlâ deterministik keyword kuralı, LLM'e bağlı değil.
- [x] **Canlı LLM doğrulaması + şema optimizasyonu** — gerçek gpt-4o çağrısı yapıldı: `create_with_completion` doğrulandı, `source_references` düz metne çevrildi. Mesaj başına 3 istek → 1, 7.343 → 1.554 token, 14,8 → 8,7 sn — @Cagri12345
- [x] **`prompts/extraction_v1.txt` + `worker/extraction/extractor.py` (S1-15)** — Türkçe extraction prompt'u (9 kural + 3 few-shot) ve onu LLM istemcisiyle birleştiren modül: her alıntıyı ham metinde bulup `{quote,start,end}` üretiyor, bulunamayan alıntının alanını düşük güvene düşürüyor (halüsinasyon savunması). DB'ye dokunmuyor — pipeline sınırı @nursenakyga ile mutabık. 12 test, hiçbiri ağa çıkmıyor — @Cagri12345
- [x] **web/ Vite entry point** (S1-13) — @bariss9/@nursenakyga. index.html, vite.config.ts, src/main.tsx
- [x] **Ham liste ekranı (S1-8)** — @bariss9. Pano'da claims tablosu, urgency'e göre sıralama + kritik/yüksek vurgu, `/api/claims` 3sn polling (`useClaims` hook + `ClaimsTable` component)
- [x] **Extraction pipeline entegrasyonu (S1-15)** — @nursenakyga. `worker/pipeline.py`'da `step_extract`: masked_text ile `extract()` çağrılıyor, sonuç `unmask_data()`'dan geçirilip `Claim.data.extraction`'a yazılıyor, `audit_trail`'e provider/duration_ms ile loglanıyor. Extraction hatası dead_letter'a düşmüyor — in_human_review'da kalıp `extraction_error` audit adımı düşüyor (aciliyet sıralamasının kaybolmaması için, Çağrı ile mutabık). Gerçek OpenAI çağrısıyla test edildi.
- [x] **Validation pipeline entegrasyonu** — @nursenakyga. `step_extract` sonrası `step_validate` çalışıyor: Barış'ın 11 kuralı (`worker/validation/validator.py`) extraction çıktısı + claim.urgency/content_type üzerinde koşuyor, sonuç `Claim.data.validation_flags`'a ve `audit_trail`'e yazılıyor. Flag'ler engellemiyor, sadece görünür kılıyor. Gerçek veriyle test edildi (doğru format flag üretmiyor, format hatası doğru yakalanıyor).
- [x] **S2-8 — Pano sayaç kartları + aciliyet donut + il barı** — @nursenakyga. Backend: `/istatistik/ozet` endpoint'i (`urgency_counts`/`status_counts`/`city_counts`, city verisi `Claim.data.extraction.incident_location.city`'den JSON path ile çekiliyor). Frontend: `useStats.ts` hook + `StatCards`/`UrgencyDonut`/`CityBar` bileşenleri (Recharts), Dashboard.tsx'e entegre. Gerçek veriyle test edildi (kritik/normal ayrımı donut'ta, şehir verisi bar'da doğru görünüyor).

## HENÜZ YAPILMADI

- [ ] **Masking v2 (S2-5)** — @bariss9. 5K isim sözlüğü + Türkçe normalizasyon + LLM sanity (LLM kısmı extraction'a bağımlı; artık teknik olarak mümkün).
- [ ] **eval/ (S1-9)** — @MehmetTayyip. feature/ds-analiz-kurulum branch'inde var ama MERGE BLOKERİ (aşağıya bak).
- [ ] **Çalışan fallback katmanı** — OpenAI birincil, Groq/Gemini/Ollama config'i duruyor ama kod yok (ADR-001 açık maddesi, @bariss9 + @nursenakyga).
- [ ] **source_references offset + kaynak cümle vurgulama (S2-12)** — @nursenakyga. Offset backend'de zaten çözülüyor (`{quote,start,end}`); kalan iş sadece ekranda vurgulama.
- [ ] **CLAUDE.md §2/§4 güncellemesi** — hâlâ eski üçlü router'ı anlatıyor; ADR-001'e göre güncellenmeli — @bariss9
- [ ] `schemas/claim.json` nihai "dondu" işareti

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca  —  DURUM: bitti (eval hariç)
- [x] compose 6 servis (hepsi çalışıyor)
- [x] FastAPI iskelet + `/health`
- [x] `schemas/claim.json`
- [x] Alembic migration (VECTOR 384 + external_ref)
- [x] `/ingest` + `/claims` + `/claims/{id}`
- [x] **Masking v1 (S1-4)**
- [x] GT üreteci (S1-1)
- [x] Worker kuyruk tüketici pipeline (S1-5)
- [x] LLM istemcisi + extraction prompt/extractor (S1-15) — ADR-001 ile OpenAI'ye dönüştü; pipeline'a bağlandı (extraction + validation) @nursenakyga
- [x] web/ Vite iskeleti (S1-13)
- [x] Pano ham liste ekranı (S1-8)
- [x] text_generator / e-posta üreteci (S1-2)
- [x] Türkçe cümle bölücü (S1-3)
- [x] replay v1 (S1-10) — emails.jsonl → /ingest
- [ ] eval (S1-9) — DS merge blokeri
- [ ] Sprint 1 demo

### Sprint 2 — Kuyruk + Pano Tam + Masking v2  —  DURUM: aktif
- [x] S2-DE-1 — counterparty_exists artık damage_type'a bağlı — @muyesser10
- [x] **S2-3 — Validation kuralları (11 kural) + ortak yaralanma sözlüğü** — @bariss9
- [x] **S2-4 — Kuyruk backend (onayla/reddet + audit + edit/diff)** — @bariss9
- [ ] S2-5 Masking v2 — @bariss9
- [x] **S2-7 — Onay kuyruğu ekranı (düzenle + onayla/reddet + diff)** — @bariss9
- [x] S2-8 Pano sayaç/donut/il barı — @nursenakyga
- [ ] S2-12 Kaynak cümle vurgulama — @nursenakyga
- **Dağılım:** bariss9 → S2-4/S2-7/S2-5, nursena → S2-8/S2-12 (mutabık)

### Sprint 3 — Auth + RAG + Observability  —  DURUM: başlamadı
### Sprint 4 — Cila + Hata Merkezi + Demo  —  DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| S2-12 (ekran vurgusu) | — | @nursenakyga | Bağımlılık çözüldü (extraction pipeline'da, offset hazır); kalan iş sadece ekranda vurgulama |
| **MERGE BLOKERİ** | **eval kodu ↔ claim.json alan adı uyuşmazlığı** | **@MehmetTayyip** | **DS branch Türkçe alan adı kullanıyor (police_no/plaka), claim.json İngilizce. Eval GT'yi okuyamaz. Standup'ta çözülmeli.** |

---

## BİLİNEN SORUNLAR / RİSKLER

- **Worker/api image bayatlaması:** extraction/validation gibi yeni worker kodu (veya api değişiklikleri) `docker compose up -d` ile OTOMATİK gelmiyor — image yeniden build edilmeli (`docker compose up -d --build worker`). Aksi halde container eski kodu çalıştırır (örn. extraction hiç çağrılmaz). Web'de bind mount var, worker/api'de yok.
- **Extraction OpenAI anahtarına bağlı:** `OPENAI_API_KEY` `.env`'de yoksa extraction hata verir, `audit_trail`'e `extraction_error` düşer, claim `in_human_review`'da kalır (data'da extraction bloğu olmaz). Bu doğru davranış (aciliyet kaybolmuyor) ama lokal test için anahtar gerekir; anahtarsız test için data elle enjekte edilebilir.
- **Extraction taban çizgisi ölçüldü (100 kayıt, gpt-4o-mini, 3 few-shot):** zorunlu alan doğruluğu **%99,4**, kanıtsız alan oranı **%3,9**. CLAUDE.md §7 hedefleri (≥%82, ≤%7) karşılandı. Kanal bazında e-posta %99,2 / transkript %99,6 / form %99,4. Koşu maliyeti ~$0,05.
- **Extraction artık `gpt-4o-mini` kullanıyor — ADR-001 güncellendi.** 8 kayıtta 4o ile eşit çıkmıştı, 100 kayıtta %99,4 yaptı; güçlü kademeye gerek olmadığı ölçümle görüldü. Text-to-SQL ve RAG hâlâ güçlü kademede, onlar ölçülmedi.
- Ölçüm gürültüsü: `temperature=0` ve sabit `seed`'e rağmen aynı koşu 800 alanda ±1 alan oynuyor (±%0,13). %0,5'ten küçük farklar anlamlı sayılmamalı.
- Kalan 5 hatanın 3'ü veri kaynaklı: `collision` kayıtlarının 53'ünde (139'un %38'i) `counterparty_exists=False` — çarpışacak kimse olmadan çarpışma. Ayrıca 3 `collision` kaydında metinde olayın nasıl olduğu hiç yazmıyor. @muyesser10'a iletildi.
- 3 few-shot örneği yerine 1 örnek aynı doğruluğu verdi ama `damage_type`'ı 22 kez kanıtsız doldurdu (3'e karşı) — tahmin ederek tutturuyordu. 3 örnek kaldı; önbellekleme sayesinde süre farkı da yok.
- **Veri sürümü:** `text_generator.py`'deki her değişiklik 1000 kaydın neredeyse hepsini değiştiriyor (PR #25'te 991/1000). Taban çizgisi ölçüldükten sonra veri dondurulmalı, yoksa haftalık metrikler kıyaslanamaz — @muyesser10'a iletildi.
- **DS branch (feature/ds-analiz-kurulum) merge blokeri:** (1) Türkçe alan adları (dil kararı İngilizceydi), (2) eval/ → analiz/ yeniden adlandırılmış (CLAUDE.md dizin sahipliğine aykırı), (3) pandas/scikit-learn requirements'ta yok (CI patlar). Merge öncesi standup.
- **CLAUDE.md §2/§4 güncel değil:** ADR-001 üçlü router yerine OpenAI'ye geçti ama CLAUDE.md hâlâ eskiyi anlatıyor. Yanlış yönlendirme riski. @bariss9 güncelleyecek.
- worker `depends_on` `service_started` (api'deki `service_healthy` değil); DB hazır olmadan bağlanma riski — @nursenakyga.
- `.env.example` `postgresql://` ile başlıyor; kod `+psycopg`'ye çeviriyor. İleride düzeltme ekiple konuşulacak.
- Yerel Postgres çakışması (bariss9): db override ile 5433'te (kişisel).
- isim sözlüğü v0 Türkçe karaktersiz; "Hüseyin" eşleşmez — Sprint 2 (S2-5).
- **`policy_no` formatı:** validation'daki `POL-YYYY-NNNNN` deseni sentetik (gt_generator'dan). @muyesser10 teyit etti: gerçek format değil, sadece test verisi kalıbı. Validation bu yüzden flag'liyor, reddetmiyor — gerçek veri farklı formatta gelirse kırılmaz.
- OpenAI maliyeti ölçüldü: extraction mesaj başına ~3.900 girdi + ~330 çıktı token, ~3,9 sn (gpt-4o-mini, tek istek). 100 kayıtlık koşu ~$0,05; 1000 kayıtlık tam koşu birkaç kuruş. Sistem prompt'u her çağrıda aynı olduğu için OpenAI'nin önbelleği devrede (`cached_tokens` çıktıda görünüyor). `DEMO_OFFLINE` için yerel model yok, kayıtlı fixture gerekiyor (Sprint 4). Çalışan fallback katmanı henüz yazılmadı, sadece anahtarlar duruyor. Bkz. ADR-001.
- `data/dictionaries/opening_templates.txt` 12. satırda "dün" sabit yazılı ve gövdedeki gerçek tarihle çelişiyor — 46 mailin 5'i (GT-000001/3/57/76/99). `make_date_phrase` doğru çalışıyor, sorun yalnız bu şablonda. @muyesser10'a iletildi.
- `injury` / `counterparty_exists`: metin sessizse GT `false`, extraction sözleşmesi `null` diyor. Eval normalizasyonunda `null` = `false` eşlenecek; şema değişmiyor (bilgi kaybı olmasın).

---

## KARAR GEÇMİŞİ (kısa)

- İsimler İngilizce (endpoint/kod/dosya/**alan adları**); yorumlar İngilizce; prompt Türkçe; config ASCII.
- claim.json: damage_type 8 değer; source_references offset'li {quote,start,end}; status sistem alanı; city/district; estimated_amount nullable number; incident_date ISO.
- external_ref: GT eşleştirme için ingest'e opsiyonel alan. received_at override: GT'de sabit zaman.
- Masking: regex önce, isim sözlüğü sonra; plaka 1-3 harf; v0 sözlük ~42 isim. Hata olursa audit_trail'e masking_error yazılıyor.
- Yaralanma sözlüğü tek kaynak (`worker/shared/injury_terms.py`), classification + validation ortak kullanıyor; Türkçe-güvenli karşılaştırma (`_normalize_tr`).
- Durum makinesi onay/ret: in_human_review → approved (onayla) | archived (reddet); geçiş dışı istek 409. Onayla opsiyonel `edits` alır; değişen alanlar audit_trail'e diff olarak yazılır.
- extraction `source_references`: LLM'den düz alıntı metni (`dict[str, str]`). `{quote,start,end}` nihai kayıt şekli olarak `claim.json`'da kalıyor, offset'i pipeline hesaplar. Ölçüm: sarmalayıcı nesne mesaj başına 2 fazla LLM çağrısına yol açıyordu.
- LLM sağlayıcı: OpenAI iki kademe (gpt-4o-mini / gpt-4o) — ADR-001. Eski sağlayıcı anahtarları `.env.example`'da fallback başlığı altında duruyor, kod okumuyor. **Embedding yerel 384 (değişmedi).** SQLAlchemy senkron (psycopg3); Python 3.11.
- web servisi: bind mount + anonymous node_modules volume ile live-reload (S1-8 sırasında eklendi).

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*