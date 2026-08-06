# STATUS.md — Projenin Güncel Durumu

> Bu dosya **canlı** durumu tutar; sık güncellenir. CLAUDE.md sabit kurallardır, bu dosya
> "şu an neredeyiz" sorusunun cevabıdır. Her Claude Code oturumu işe başlamadan bunu okur.
>
> **Güncelleme kuralı:** İş biten kişi, PR'ında bu dosyayı da günceller (kısa tut).

---

## ÖZET (bir bakışta)

- **Faz:** Sprint 1 ve Sprint 2 tamamen bitti. Sprint 3 neredeyse bitti — RAG puanlama (S3-3), Metrikler ekranı (S3-11) ve eval-quality panel (Mehmet'i bekliyor) kaldı.
- **Aktif sprint:** Sprint 3.
- **Repo durumu:** 8 servis (db, redis, api, worker, **rag**, web, prometheus, grafana — ollama artık fiilen ölü). Uçtan uca akış: /ingest → Redis → worker (mask → sanity → classify → route → extract → validate → embed) → /claims + /queue (auth korumalı) → Pano (tam, S3-5) + Kuyruk (klavye UX ile, S3-4) + Soru (`/soru` → api proxy → rag servisi, S3-2).
- **Son büyük olaylar:** JWT auth (S3-8), Prometheus+Grafana (S3-9), masking v2 tamamlandı (isim sözlüğü ~1550 + ambiguous kural + LLM sanity + PII-sızıntı hotfix), Pano tam görünüm (S3-5, nursena), classification veri blokeri çözüldü (Müyesser), embedding modeli seçildi (ADR-002, e5-small), **RAG bitti — `/soru` uçtan uca çalışıyor** (S3-2, Cagri; ayrı `rag` servisi, ADR-003).
- **Sıradaki iş (BE):** CLAUDE.md §2/§4 güncellemesi (borç), soyisim sözlüğü resmi kaynağı (Müyesser'den bekleniyor), **`claims_flat` view migration'ı** (tanım hazır: `migrations/sql/claims_flat.sql`), compose'a eklenen `rag` servisinin aynı gün merge'ü (ortak dosya, CLAUDE.md §5 — ADR-003 onaylandı), `monitoring/prometheus.yml`'ye `rag` scrape hedefi.
- **Sıradaki iş (LLM/DS):** RAG 40 soruluk eval seti + puanlama (S3-3), eval-quality Grafana paneli (Mehmet), extraction baseline'ının yeniden ölçülmesi (korpus yeniden üretildi), classification'ın pipeline'a bağlanması (`worker/classification/` hazır ama `pipeline.py` hâlâ keyword kuralı çalıştırıyor).

---

## HAZIR OLANLAR

### Sistem / Backend / Frontend (bariss9 + nursenakyga)
- [x] Dizin yapısı, `docker-compose.yml` (7 servis), `.env.example`, CI (ruff+gitleaks), `CLAUDE.md`/`STATUS.md`/`CODEOWNERS`
- [x] `schemas/claim.json` — damage_type (8 değer), source_references offset'li, status sistem alanı, city/district, ISO tarih, nullable number
- [x] Alembic migration (7 tablo + external_ref, VECTOR 384), SQLAlchemy senkron modelleri
- [x] `/health`, `/ingest`, `/claims`, `/claims/{id}`, `/queue`, `/queue/{id}/approve` (opsiyonel `edits` + diff audit), `/queue/{id}/reject`, `/istatistik/ozet`
- [x] **JWT Auth (S3-8)** — `POST /auth/login`, HS256, `require_role`/`get_current_user` dependencies. Tüm endpoint'ler korumalı (`/health` ve `/metrics` hariç, bilerek açık). `/ingest` bilerek JWT dışı bırakıldı (service-to-service API key planlanıyor, TODO). approve/reject `operator`/`admin` rolü gerektiriyor. `scripts/create_user.py` (kullanıcı oluşturma CLI'ı). Frontend: `Login.tsx`, `auth.ts` (authenticatedFetch wrapper), tüm hook'lar (`useClaims`/`useQueue`/`useStats`) güncellendi.
- [x] **Prometheus + Grafana (S3-9)** — `/metrics` (api, instrumentator ile) + worker'da ayrı HTTP server (port 9100). Sistem/pipeline paneli + Kuyruk/operasyon paneli canlı. Eval-quality paneli placeholder (Mehmet'i bekliyor).
- [x] **Masking v1+v2 (S2-5, tam)** — regex (TC/phone/plate/IBAN) + isim sözlüğü (~1550, Faker `tr_TR` kaynaklı, `data/dictionaries/turkish_names.txt`) + ambiguous-isim kuralı (günlük kelimeyle çakışan isimler — Deniz/Yağmur/Bahar vb. — sadece soyisim bitişikliğinde VEYA bağlam işaretinde maskeleniyor). Soyisim listesi hâlâ **stub** (Faker'ın küçük kümesi), resmi kaynak (Müyesser) bekleniyor.
- [x] **LLM Masking Sanity** — masking sonrası küçük bir LLM çağrısı kaçan PII kontrolü yapar. Sonuç `audit_trail` + `Claim.data.masking_sanity_flags`'e **tür+konum** olarak yazılır (ham metin ASLA DB'ye yazılmaz — ilk versiyonda bir sızıntı bug'ı vardı, hotfix'lendi). Kaçak bulunursa extraction atlanır (maliyet + PII'yi 3. tarafa göndermeme). LLM hatasında fail-closed, `MASKING_SANITY_ENABLED` ile kapatılabilir.
- [x] Masking hata izleme, Unmask (`worker/masking/unmask.py`), Validation (11 kural, `worker/validation/validator.py`), ortak yaralanma sözlüğü (`worker/shared/injury_terms.py`)
- [x] **Onay kuyruğu ekranı (S2-7)** — liste + detay paneli, düzenlenebilir extraction alanları, validation_flags gösterimi, onayla (edits/diff) / reddet (iki adımlı)
- [x] **Kuyruk klavye UX (S3-4)** — `a`=onayla (düzenlemesiz hızlı onay), `r`=reddet (iki adımlı onay korunuyor), onay/red sonrası otomatik sıradaki kayda geçiş (taze cache'ten, polling yarış durumu ele alındı), `?` yardım overlay'i. Harici kütüphane eklenmedi.
- [x] **Pano tam görünüm (S3-5)** — @nursenakyga. StatCards/UrgencyDonut/CityBar + yeni TrendChart/Pulse bileşenleri, `/istatistik/ozet` trend sorgusu eklendi.
- [x] **Kaynak cümle vurgulama (S2-12)** — @nursenakyga. `SourceHighlight.tsx`, offset tabanlı, kanıtsız alanlarda savunmacı (çökmüyor).
- [x] worker gerçek Redis tüketicisi + pipeline (S1-5), extraction+validation pipeline entegrasyonu — @nursenakyga
- [x] **S3-6 — Soru-cevap arayüzü + kaynak çipleri (mock)** — @nursenakyga.Çağrı'nın dondurduğu sözleşmeye (question/answer/mode/answerable/
  refusal_reason/sources/sql/row_count/duration_ms) birebir uyumlu mock var,gerçek endpoint gelince tek fonksiyon değişecek. Üç senaryo da (retrieval,sql, answerable=false) test edildi.
  
### LLM / Extraction / RAG (Cagri12345)
- [x] `worker/llm/client.py` — OpenAI istemcisi (instructor+Pydantic), iki kademe, seed, retry, audit log
- [x] `prompts/extraction_v1.txt` + `worker/extraction/extractor.py` (S1-15) — halüsinasyon savunması, offset çözümleme
- [x] Extraction taban çizgisi: 100 kayıt, gpt-4o-mini, %99,4 doğruluk, %3,9 kanıtsız — **NOT: korpus yeniden üretildiği için (isim+classification düzeltmesi) bu ölçüm geçersiz, yeniden ölçülmesi gerekiyor**
- [x] **Embedding modeli seçimi (ADR-002)** — `intfloat/multilingual-e5-small` seçildi (MiniLM'e karşı ölçülüp karşılaştırıldı, retrieval sıralamasında daha iyi). `worker/embedding/encoder.py` (embed_query/embed_passages, query:/passage: prefix'leri dahili). **Önemli bulgu:** korpusta sadece 61 benzersiz `damage_description` var — RAG bu korpusta dürüstçe gösterilemez, 40 soruluk RAG seti bunu bilerek tasarlanmalı (Müyesser'e iletildi).
- [x] **RAG Phase 1 — Text-to-SQL** — prompt + SQL guard + generator. `sqlglot` bağımlılığı eklendi.
- [x] Injury matching düzeltmesi — precision %18,5 → %98,8
- [x] Eval baseline yeniden pinlendi + korpus fingerprint'i eklendi
- [x] **step_embed + backfill (S3-2)** — claim metni `claim_embeddings`'e yazılıyor (`masked_text`; `damage_description` korpusta 61 benzersiz değere çöktüğü için seçilmedi, ADR-002). Sanity flag'li kayıtlarda atlanıyor, embed hatası dead_letter'a düşürmüyor. Gerçek modelle uçtan uca doğrulandı: 384 boyut, L2 normu 1.0000, adım 291 ms. `scripts/backfill_embeddings.py` mevcut kayıtlar için (`--dry-run` / `--force`).
- [x] **RAG Phase 2 — retrieval + kaynaklı cevap + yönlendirme (S3-2)** — `worker/rag/retrieval.py` (pgvector, **eşiksiz sıralama** — ADR-002 "rank, not threshold"; snippet = soruya en yakın cümle, tek batch'te embed), `answer.py` + `prompts/rag_answer_v1.txt` (**atıf doğrulaması**: hiçbir kaynağa dayanmayan cevap gösterilmiyor, `invalid_citations` Hata Merkezi'ne sinyal), `router.py` + `prompts/rag_router_v1.txt` (SQL/retrieval seçimi + filtre çıkarımı, `mode` burada hesaplanıyor). **Endpoint yok** — `claims_flat` bekliyor.
- [x] **ADR-003** — `/soru` ayrı `rag` compose servisinde (worker image'ından, api torch'suz kalsın diye). Durum: **Accepted** (2026-08-06, @bariss9). Şartı JWT hop'uydu — proxy çağıranın token'ını geçirsin, tokensiz istek api katmanında 401 alsın, testle doğrulansın; üçü de var (proxy testi, tokensiz istek rag'e hiç çıkmıyor, rag ayrıca kendi doğruluyor).
- [x] **RAG Phase 2 tamamlandı — `/soru` uçtan uca (S3-2)** — `worker/rag/ask.py` (yönlendirme → sql|retrieval → cevap, denetim izi `step='rag_question'`, eval için `audit=False`), `worker/rag/sql_answer.py` (sorgu çalıştırma + **satırlar maskelenip LLM'e gidiyor, cevap geri açılıyor** — `claims_flat` maskesiz extraction okuyor, `pipeline.py:194` unmask ediyor; + **sayı doğrulaması**: sonuçta geçmeyen sayı içeren cevap gösterilmiyor, `unverified_numbers` Hata Merkezi'ne sinyal), `rag/main.py` (ayrı servis, JWT'yi **kendi** doğruluyor, model `lifespan`'da yükleniyor, endpoint `def` — `async def` event loop'u kilitlerdi), `api/routers/question.py` (proxy: async httpx, token geçirme, 504/503, non-2xx passthrough). Frontend mock'u söküldü (`useQuestion.ts`). **Uçtan uca gerçek modelle doğrulandı (2026-08-06):** retrieval 7,1 sn, SQL 6,9 sn, SQL sayıları DB ile birebir.
- [x] **Atıf numaralama hatası düzeltildi** — cevap 5 kaynaktan 1. ve 3.'yü kullanınca ekranda 2 çip kalıyor ama metinde "[3]" yazıyordu, üçüncü çip yoktu. Artık metin çip sırasına göre yeniden numaralanıyor, çözülemeyen atıf metinden düşüyor (`answer.renumber_citations`). Uçtan uca koşuda yakalandı.
- [x] **`claims_flat` view tanımı** — `migrations/sql/claims_flat.sql`. Migration'a saracak taraf backend ikilisi (CLAUDE.md §4); dosya repoda ki tanım ile prompt (`schema_context.SCHEMA_TEXT`) birlikte review edilebilsin. `json` (jsonb değil) kolonu `pg_input_is_valid` ile güvenli cast'leniyor — bozuk tek değer tüm sonucu düşürmüyor. **View olmadan da `/soru` çökmüyor:** SQL yolu Türkçe reddediyor, retrieval yolu tam çalışıyor.
- [x] **Docker build düzeltmesi (PR #52)** — torch CPU indeksinden (502→183 MB), `sentence-transformers` `requirements-worker.txt`'e taşındı (api image'ı artık torch indirmiyor: 625→34 MB), pip cache mount, `.dockerignore` (yoktu — `.env` worker image'ına gömülüyordu).

### Data / Eval (muyesser10, MehmetTayyip)
- [x] `worker/parser/sentence_splitter`, `gt_generator.py`, `text_generator.py`, `replay/replay.py` (+ senaryo modu, S3-10)
- [x] **Classification veri blokeri ÇÖZÜLDÜ** — content_type artık metne yansıyor (info_request soruyor, irrelevant konu dışı, claim ihbar), injury önce belirleniyor urgency ondan türüyor (yaralanmasız kritik kayıt kalmadı), high/normal metinlerde aciliyet izi var.
- [x] **Holdout isimler (eval için)** — `holdout_first_names.txt` (109) + `holdout_last_names.txt` (77), Faker ile sıfır kesişim kodda doğrulandı, `name_source` alanı (`faker`/`holdout`) her kayıtta. **Bu dosyalar masking sözlüğüne asla girmeyecek** (governance kuralı, Cagri+Müyesser+bariss9 mutabık) — eval'in isim recall ölçümü artık dairesel değil.
- [x] `eval/` omurgası (S1-9) — loader/normalize/scoring/metrics/runner, CLI, 68 test

## HENÜZ YAPILMADI

- [ ] **CLAUDE.md §2/§4 güncellemesi** — hâlâ eski üçlü router'ı anlatıyor — @bariss9
- [ ] **Soyisim sözlüğü resmi kaynağı** — masking'deki `SURNAMES` hâlâ stub, Müyesser'den TÜİK/temiz kaynak bekleniyor
- [ ] **Çalışan fallback katmanı** — OpenAI birincil, Groq/Gemini/Ollama config'i duruyor ama kod yok
- [ ] **`monitoring/prometheus.yml`'ye `rag` scrape hedefi** — servis `/metrics` yayınlıyor, kazıyan yok — @bariss9
- [ ] **Eval-quality Grafana paneli** — placeholder duruyor, Mehmet'in metrik export'u bekleniyor
- [ ] **Extraction baseline'ının yeniden ölçülmesi** — korpus yeniden üretildi (isim+classification), eski %99,4 rakamı geçersiz — @Cagri12345
- [ ] **RAG 40 soruluk eval seti** — korpusun sadece 61 benzersiz açıklama içerdiği bilinerek tasarlanmalı — @muyesser10/@MehmetTayyip
- [ ] `schemas/claim.json` nihai "dondu" işareti

---

## SPRINT İLERLEMESİ

### Sprint 1 — İskelet + İlk Uçtan Uca — DURUM: bitti (eval hariç)
Tüm maddeler tamamlandı (masking v1, GT üreteci, worker pipeline, LLM client+extraction, web iskeleti, Pano ham liste, text/sentence üreteçleri, replay v1). Eval omurgası yazıldı, o zamanki 3 metrik veri blokerindeydi (artık çözüldü, bkz. Sprint 2/3).

### Sprint 2 — Kuyruk + Pano Tam + Masking v2 — DURUM: bitti
- [x] S2-DE-1, S2-3 (validation), S2-4 (kuyruk backend), S2-5 (masking v2, normalizasyon+sözlük+sanity, çok parçalı), S2-7 (onay ekranı), S2-8 (Pano sayaç/donut/il barı), S2-12 (kaynak vurgulama)

### Sprint 3 — Auth + RAG + Observability — DURUM: neredeyse bitti
- [x] S3-5 — Pano tam görünüm (trend+nabız) — @nursenakyga
- [x] S3-8 — JWT auth + roller — @bariss9
- [x] S3-9 — Prometheus+Grafana (sistem+kuyruk panelleri; eval paneli placeholder) — @bariss9
- [x] S3-10 — Replay v2 senaryo modu — @muyesser10
- [x] S3-1/S3-7 (kısmen) — embedding modeli seçimi (ADR-002), RAG Phase 1 (Text-to-SQL) — @Cagri12345
- [x] **S3-4 — Kuyruk klavye UX (a/r kısayolları + otomatik-sonraki + yardım overlay)** — @bariss9 (bu PR)
- [x] **S3-2 — RAG Phase 2 (bitti)** — @Cagri12345. Embedding, retrieval, kaynaklı cevap, soru yönlendirme, `/soru` endpoint'i + `rag` servisi + api proxy'si. Uçtan uca gerçek modelle doğrulandı. `claims_flat` migration'ı hâlâ backend ikilisinde ama artık bloker değil: view yokken SQL yolu düzgün reddediyor.
- [ ] S3-3 — RAG puanlama— @MehmetTayyip 
- [x] S3-6 — soru-cevap arayüzü — @nursenakyga
- [ ] S3-11 — Metrikler ekranı (Mehmet'in RAG koşu verisine bağımlı, sona bırakılabilir)

### Sprint 4 — Cila + Hata Merkezi + Demo — DURUM: başlamadı

---

## BİLİNEN BAĞIMLILIKLAR / BEKLEYENLER

| Bekleyen | Beklenen şey | Kimden | Durum |
|----------|--------------|--------|-------|
| Soyisim sözlüğü kaynağı | TÜİK/temiz liste | @muyesser10 | Stub, araştırma sürüyor |
| **`claims_flat` view migration'ı** | Tanım hazır: `migrations/sql/claims_flat.sql` — `op.execute()` içine sarılmayı bekliyor | @bariss9 / @nursenakyga | Artık bloker değil: view yokken `/soru`'nun SQL yolu Türkçe reddediyor, retrieval yolu çalışıyor |
| DS branch (feature/ds-analiz-kurulum) | Branch'in akıbeti | @MehmetTayyip | Hâlâ çözülmedi, standup'ta bakılacak |
| RAG eval seti tasarımı | 61 benzersiz açıklama kısıtına göre tasarlanmalı | @muyesser10 | İletildi |

---

## BİLİNEN SORUNLAR / RİSKLER

- **Operatörün sorusu maskelenmeden LLM'e gidiyor** — `router.py`, `text_to_sql.py` ve cevap katmanı soruyu olduğu gibi yolluyor. "34 ABC 123 plakalı aracın ihbarı ne oldu?" yazılırsa plaka OpenAI'ye gider. Kolay çözümü yok: Text-to-SQL'in `WHERE` için gerçek değere ihtiyacı var. Sonuç satırları ve claim metni maskeli gidiyor, sızıntı yalnızca sorunun kendisiyle sınırlı — @Cagri12345
- **Web formu metinlerinde snippet cümle değil, form dökümü** — form metninde cümle sonu yok, `sentence_splitter` bölemiyor, kaynak çipine tüm form giriyor. Çipte `truncate` var, görsel sorun çıkmıyor ama "soruya en yakın cümle" vaadi o kanalda tutmuyor.
- **CLAUDE.md §4 `npm run types` diyor ama böyle bir script yok** — `openapi-typescript` bağımlılığı da yok, TS tipleri fiilen elle yazılıyor (`ClaimsTable.tsx:9`, `useQuestion.ts`). `/soru` proxy'sinin OpenAPI şeması doğru ama ondan üreten yok; koruma `api/routers/test_question.py`'deki drift testi (api ile worker'daki iki sözleşme tanımının alanlarını karşılaştırıyor).
- **Worker/api image bayatlaması** — kod değişince `docker compose up -d --build worker` (veya api) şart, aksi halde eski kod çalışır. `rag` servisi de `worker/` kodunu yüklüyor, o da yeniden build ister.
- **`sqlglot` yerel kurulum eksikliği** — `requirements.txt`'te var ama bazı yerel venv'lerde kurulu değil, `worker/rag/test_*.py` collection hatası verir. Kod sorunu değil, `pip install -r requirements.txt` çözer.
- **CI test hatalarını yutuyor** — `.github/workflows/ci.yml:31` satırı `pytest -q || echo "No tests yet..."`. `|| echo` yüzünden testler patlasa da adım yeşil geçiyor; **yeşil CI "testler geçti" anlamına gelmiyor**. Sprint 1 bitti, 400+ test var — bu güvenlik ağı artık amacını aştı.
- **Maskeleme yanlış pozitif: akrabalık terimleri** — "Eşim yaralandı" → `[NAME_1] yaralandı`. LLM'e giden metinde kimin yaralandığı kayboluyor. Uçtan uca testte görüldü — @bariss9
- **Maskeleme yanlış negatif: Türkçe karaktersiz isimler** — "Mehmet Yilmaz" (ı yerine i) sözlükte yok, maskelenmiyor; LLM sanity katmanı yakaladı ama o mesaj başına ekstra OpenAI çağrısı. Gerçek dünyada klavye/SMS yüzünden sık — @bariss9
- **`useQuestion.ts` `urgency`'yi zorunlu tipliyor** (`"critical" | "high" | "normal"`), ama `Claim.urgency` DB'de nullable ve `RetrievedClaim.urgency` `str | None`. Null gelirse `SourceChip`'teki `urgencyDot[source.urgency]` `undefined` döner ve renk noktası sessizce kaybolur (çökmez). Gerçek endpoint bağlanmadan düzeltilmeli; `score` için zaten var olan null kontrolünün aynısı — @nursenakyga
- Extraction OpenAI anahtarına bağlı — `.env`'de yoksa `extraction_error` audit'i düşer, claim `in_human_review`'da kalır (doğru davranış, aciliyet kaybolmuyor).
- Veri kontratı ile gerçek dosyalar arasında hâlâ küçük ayrışmalar var (`meta`/`labels` blokları claim.json'da yok) — düşük öncelik.
- Prompt yer tutucuları (`[PLAKA_1]` vb.) ile masking'in ürettiği (`[PLATE_1]`) farklıydı — Cagri'nin ayrı bir düzeltme PR'ında ele alındı (placeholder + adres-kuralı daraltma).
- `policy_no` formatı (`POL-YYYY-NNNNN`) sentetik, gerçek format değil — validation flag'liyor, reddetmiyor.
- OpenAI maliyeti: extraction ~3.900 girdi token, ~$0,05/100 kayıt. Sanity: kısa prompt, ek maliyet düşük. `DEMO_OFFLINE` kodda hâlâ okunmuyor (placeholder).
- `injury`/`counterparty_exists`: `null`≠`false` ayrımı korunuyor, eval normalizasyonunda `null`=`false` eşleniyor.
- worker `depends_on: service_started` (service_healthy değil) — DB hazır olmadan bağlanma riski, düzeltilmedi.
- Yerel Postgres çakışması (bariss9): db override ile 5433'te (kişisel, gitignore'da).
- Ollama servisi fiilen ölü (ADR-001 sonrası), kaldırma kararı hâlâ açık.

---

## KARAR GEÇMİŞİ (kısa)

- İsimler İngilizce (endpoint/kod/dosya/alan adları); yorumlar İngilizce; prompt Türkçe; config ASCII.
- claim.json: damage_type 8 değer; source_references offset'li; status sistem alanı; city/district; estimated_amount nullable; incident_date ISO.
- Masking: regex önce, isim sözlüğü sonra. Sözlük kaynağı: Faker `tr_TR` (statik dosya, `data/dictionaries/turkish_names.txt`, ~1550). Ambiguous isimler soyisim-bitişikliği VEYA bağlam-işareti şartıyla maskelenir. **Holdout isimleri (eval) asla sözlüğe girmez** — governance kuralı.
- LLM masking sanity: sonuç DB'ye **tür+konum** olarak yazılır, asla ham metin (PII sızıntısı hotfix'i sonrası kesinleşti). Kaçak bulunursa extraction atlanır, fail-closed.
- Auth: JWT HS256, `/health`+`/metrics` hariç her şey korumalı, approve/reject rol gerektiriyor (`operator`/`admin`). `/ingest` bilerek JWT dışı (service-to-service key planı, TODO).
- Kuyruk klavye UX: `a`=hızlı onay (düzenlemesiz), `r`=iki adımlı reddet, otomatik-sonraki taze cache'ten hesaplanır (polling yarış durumu ele alındı).
- Durum makinesi onay/ret: in_human_review → approved | archived; geçiş dışı istek 409. Onayla opsiyonel `edits` alır, diff audit'e yazılır.
- Embedding: yerel, 384 boyut, `intfloat/multilingual-e5-small` (ADR-002, MiniLM'e karşı ölçülüp seçildi).
- `/soru` ayrı `rag` servisinde (ADR-003), portu yayınlanmıyor; api proxy'liyor ve çağıranın JWT'sini geçiriyor, rag ayrıca kendi doğruluyor. SQL yolunda sonuç satırları maskelenip LLM'e gidiyor, cevap geri açılıyor; sonuçta geçmeyen sayı içeren cevap gösterilmiyor. Cevap sözleşmesi donmuş, api tarafında ayrıca tanımlı (api `worker/`'ı import edemez) — drift testi ikisini eşliyor.
- LLM sağlayıcı: OpenAI iki kademe (gpt-4o-mini/gpt-4o) — ADR-001. Eski sağlayıcı config'i `.env.example`'da duruyor, kod okumuyor.
- SQLAlchemy senkron (psycopg3); Python 3.11. web servisi bind mount ile live-reload.

---

*Bu dosyayı her iş bitişinde güncelle. Sabit kurallar için → `CLAUDE.md`.*