# CLAUDE.md — Claims-Cockpit (İhbar Kokpiti)

> Bu dosya, bu repoda çalışan her Claude Code oturumunun **ilk okuduğu** dosyadır.
> Amacı: projeyi tanıtmak, standartları dayatmak ve "nereden devam edeceğim" sorusunu
> netleştirmek. Anlatım Türkçe; kod, komut, dosya yolu ve kritik kural işaretleri (MUST/
> NEVER) İngilizce. Kod/klasör/değişken adları **İngilizce**, kod içi yorumlar **Türkçe** serbest.

---

## 0. HER OTURUMDA ÖNCE BUNU YAP

1. **`docs/STATUS.md` dosyasını oku.** Projenin şu an neresinde olduğunu, hangi sprintte,
   neyin bittiğini ve sıradaki işi oradan öğrenirsin. Bu dosya (CLAUDE.md) sabit kurallardır;
   güncel durum STATUS.md'dedir.
2. Çalışacağın klasörde ayrı bir `CLAUDE.md` varsa (`web/CLAUDE.md`, `worker/CLAUDE.md`) onu da oku.
3. İş yapmadan önce ilgili şemayı (`schemas/claim.json`) ve varsa ADR'leri (`docs/decisions/`) kontrol et.
4. Bir değişiklik başkasını etkileyecekse (API şeması, DB şeması, prompt çıktısı, GT yapısı),
   **önce STATUS.md'deki "Bilinen bağımlılıklar" bölümüne bak**, sonra ilerle.

---

## 1. PROJE NE YAPIYOR

Claims-Cockpit, bir kasko sigorta şirketine **üç kanaldan** (e-posta, çağrı merkezi
transkripti, web formu) gelen hasar ihbarlarını otomatik olarak işleyen bir **triyaj
sistemidir**. Bugün bu iş insan operatörlerce elle yapılıyor (ihbar başına 8-12 dk) ve
en kritik sorun şu: **yaralanmalı acil bir ihbar, sıradan bir çizik ihbarının arkasında
kuyrukta bekleyebiliyor** — çünkü kuyruk geliş sırasına göre işleniyor, aciliyete göre değil.

Sistem, gelen her mesaj için şu zinciri (pipeline) çalıştırır:

1. **Masking** — Metindeki kişisel veriler (TC, telefon, plaka, isim) bulunup `[TC_1]`,
   `[PLAKA_1]` gibi takma değerlerle maskelenir. Üç katman: regex + 5K Türkçe isim sözlüğü
   + LLM sanity taraması. Gerçek değerler ayrı tabloda; gerektiğinde geri açılabilir.
2. **Classification** — İhbar mı / bilgi talebi mi / alakasız mı? Aciliyet: kritik / yüksek /
   normal? Yaralanma işareti geçen her mesaj **deterministik kuralla** kritik olur (LLM'e bırakılmaz).
3. **Extraction** — Serbest metinden yapılandırılmış veri çıkarılır (poliçe no, plaka, olay
   tarihi, hasar açıklaması, karşı taraf, tahmini tutar). Göreli tarihler ("dün") mutlağa çevrilir.
4. **Validation** — Her alan format kurallarından geçer. LLM'in verdiği her bilgi için
   metinden **kaynak alıntısı** istenir; alıntı ham metinde geçmiyorsa alan "düşük güvenli" işaretlenir (halüsinasyon savunması).
5. **Routing** — Her şey temizse **otomatik onay**; eksik/şüpheli varsa **insan onay kuyruğuna**
   düşer — aciliyete göre sıralı.

Üstünde 5 ekranlık bir kokpit var: canlı **Pano**, klavyeyle hızlı temizlenen **Kuyruk**,
doğal dille sorgulama (**Soru** — RAG), kalite **Metrikler** paneli, **Hata** merkezi.

### Ana artılar
- Aciliyet sıralaması (yaralanmalı ihbar 30 sn'de kırmızı yanar)
- İnsanı değiştirmez, önünü açar (basit vakalar otomatik, şüpheli olanlar insana)
- Tam denetim izi (her adım: girdi/model/çıktı/süre kaydedilir — regüle sektör zorunluluğu)
- Halüsinasyona yapısal savunma (kaynak alıntı zorunlu + doğrulanır)
- KVKK uyumu tasarımda (kişisel veri LLM'e gitmez, maskeli metin gider; yerel model yedeği var)
- **Sıfır altyapı maliyeti** (tümü açık kaynak + ücretsiz LLM katmanı)

---

## 2. MİMARİ VE TEKNOLOJİ

### Servisler (docker compose)
| Servis | Teknoloji | Rol |
|--------|-----------|-----|
| `db` | PostgreSQL 16 + pgvector | Ana veritabanı + vektör arama |
| `redis` | Redis 7 | İş kuyruğu (LPUSH/BRPOP) |
| `api` | FastAPI + Uvicorn | REST API (12 endpoint) |
| `worker` | Python + pipeline | Masking→Classification→Extraction→Validation→Routing |
| `web` | React + Vite + TS | 5 ekranlı kokpit |
| `ollama` | Ollama (yerel) | LLM fallback (Groq/Gemini düşerse) |

### Teknoloji kararları (bunlar sabit — değiştirme, önce ADR aç)
- **Dil:** Python 3.11 (backend/worker), TypeScript 5+ (web)
- **ORM:** SQLAlchemy 2.0 **senkron** (async DEĞİL — repo `psycopg[binary]` v3 sync seçti; event-loop tuzağı yok)
- **Migration:** Alembic
- **LLM:** **Sıfır maliyet üçlü router** → Groq (Llama 3.3 70B) → Gemini 2.0 Flash → Ollama (yerel). 429/hata alınca sıradakine düşer.
- **Embedding:** `sentence-transformers` **yerel** (`paraphrase-multilingual-MiniLM-L12-v2`, **384 boyut**)
- **Vektör kolonu:** `VECTOR(384)` — **MUST** 1536 değil. Yanlış boyut = INSERT hatası.
- **Auth:** JWT HS256, 24 saat, 2 rol (operator/admin)
- **Observability:** Prometheus + Grafana + structlog (JSON log, her satırda mesaj_id)
- **Frontend:** Vite + React + TailwindCSS + shadcn/ui + TanStack Query + Recharts + react-hook-form

### Pipeline durum makinesi (özet)
`received → masked → classified → extracted → validated → (auto_approved | in_human_review)`
→ onay/ret → `approved | archived`. Hata olursa → `dead_letter` (DLQ, Hata Merkezi'nde görünür).
Her durum geçişi **koşullu UPDATE** ile enforce edilir; her adım denetim izine yazılır.

---

## 3. REPO YAPISI VE SAHİPLİK

```
api/            # FastAPI — endpoints, models, services  [Backend ikilisi]
worker/         # Pipeline — masking, classification, extraction, validation, embedding  [Backend ikilisi + LLM]
web/src/        # React — pages, components, api hooks  [Backend ikilisi = frontend de onlarda]
migrations/     # Alembic  [SADECE backend ikilisi üretir]
prompts/        # LLM prompt'ları (Türkçe)  [LLM Engineer]
data/           # Sentetik veri üreteçleri  [Data Engineer]
replay/         # Kayıt akıtma / demo senaryosu  [Data Engineer]
eval/           # Metrik hesaplama, eval koşucu  [Data Scientist]
schemas/        # claim.json — TEK DOĞRULUK KAYNAĞI  [Ortak, [SCHEMA] PR gerekir]
monitoring/     # Prometheus + Grafana konfig  [Backend ikilisi]
docs/           # runbook, compliance(KVKK), ADR, standup, STATUS.md
```

### Ekip (5 kişi)
- **Data Engineer — @muyesser10** — `data/`, `replay/`, parser'lar
- **LLM Engineer — @Cagri12345** — `prompts/`, `worker/` içindeki LLM router + embedding + masking/llm_sanity
- **Data Scientist — @MehmetTayyip** — `eval/`, metrikler, RAG puanlama
- **Backend + Frontend ikilisi — @bariss9 & @nursenakyga (2 kişi)** — `api/`, `worker/pipeline`, `web/`,
  `migrations/`, `monitoring/`. İkisi domain'e göre bölüşür: biri "sistem + operatör ekranları"
  (Pano, Kuyruk), diğeri "AI entegrasyon + observability + analitik ekranlar" (Soru, Metrikler, Hata).
  Detaylı görev dağılımı ekip dokümanlarındadır.

---

## 4. KOD STANDARTLARI (Claude Code bunlara MUST uyar)

### Genel
- **NEVER** commit a secret (API key, token, parola). `.env` gitignore'da; sadece `.env.example` commit'lenir. CI'da gitleaks tarar.
- **Kod/dosya/değişken/fonksiyon adları İngilizce.** Kod içi yorumlar Türkçe serbest.
- **Prompt'lar Türkçe** (sigorta verisi Türkçe). `prompts/` altında versiyonlu (`extraction_v1.txt`, `_v2` ...).
- Lint: `ruff check .` + `ruff format --check .` **MUST** temiz geçsin (line-length 100, py311, kurallar: E,F,I,UP,B).
- 20+ satır kod veya yeni dosya → mutlaka bir yere test ekle (`pytest`).

### Python / Backend
- SQLAlchemy **senkron** kullan (`Session`, `select()`), async session AÇMA.
- Her yeni endpoint için Pydantic request/response modeli + OpenAPI docstring.
- DB şeması değişikliği → **SADECE** backend ikilisi `alembic revision` çalıştırır. Başkası çalıştırmaz (multiple-heads felaketi).
- `VECTOR(384)` — embedding kolonu. Migration'da MUST 384.
- Hata yönetimi: pipeline adımı patlarsa mesajı `dead_letter`'a al, exception'ı structlog ile `mesaj_id` alanıyla logla, sessizce yutma.
- LLM çağrısı **her zaman** router üzerinden (`worker/llm_router`). Doğrudan Groq/Gemini/Ollama çağırma — fallback kaybolur.

### Frontend / web
- Elle TypeScript tipi YAZMA. `npm run types` ile OpenAPI'dan üret (`openapi-typescript`).
- Her ekranda boş / yükleme / hata durumları **MUST** olsun (demo'da eksik state amatör görünür).
- API çağrıları `/api/...` proxy üzerinden (CORS'a girme). `localhost:8000`'e doğrudan fetch yapma.
- Polling: TanStack Query, `refetchIntervalInBackground: false` (arka sekmede stampede olmasın).
- RAG cevabı 8-20 sn sürer (yerel model) — Soru ekranında yükleme mesajı buna göre.

### Git / iş akışı
- Branch: `owner/short-description` (örn. `bariss9/queue-approve`, `dev2/prometheus`). Ömrü **en fazla 1 gün**.
- Commit öneki: `api:`, `worker:`, `web:`, `prompt:`, `data:`, `eval:`, `infra:`, `docs:`.
- Özel etiketler PR başlığında: `[BREAKING]` (API şeması değişti), `[SCHEMA]` (claim.json değişti — 5 kişi de reviewer).
- Merge öncesi `git pull --rebase origin main`. Akşam açık branch bırakma.
- `pip freeze > requirements.txt` **NEVER** — tüm dosyayı yazar, çakışır. Elle tek satır ekle.

---

## 5. SIK ÇAKIŞAN DOSYALAR — DİKKAT

| Dosya | Kural |
|-------|-------|
| `docker-compose.yml` | Ekleyen aynı gün merge eder. Kişisel port/replica → `docker-compose.override.yml` (gitignore'da) |
| `.env.example` | Bölüm bölüm yapı (DB/Redis/LLM/JWT...). Herkes kendi bölümüne ekler |
| `migrations/` | Sadece backend ikilisi üretir. `alembic heads` birden fazla dönerse `alembic merge heads` |
| `requirements.txt` | Elle satır ekle, `pip freeze` yasak |
| `web/package-lock.json` | Çakışırsa merge etme: `git checkout --theirs` + `npm install` |
| `schemas/claim.json` | `[SCHEMA]` PR + standup'ta sözlü bildirim ZORUNLU. Değişikliği 5 rol de etkiler |

---

## 6. SÖZLEŞME DEĞİŞİKLİĞİ ETKİ ZİNCİRİ

Bir şey değişince kimin bozulacağını bil, önce haber ver:

| Değişen | Kim etkilenir | Nasıl bildirilir |
|---------|---------------|------------------|
| API endpoint şeması | Frontend tarafı | `[BREAKING]` PR + standup |
| DB şeması / claim.json | Herkes | `[SCHEMA]` PR + standup + migration backend'den |
| Prompt çıktı yapısı | Pipeline (worker), Eval (DS) | LLM Engineer standup'ta söyler |
| Ground truth alan yapısı | LLM, DS | Data Engineer standup'ta söyler |

`claim.json` değişince zincir: schema → Alembic migration → Pydantic → TS types (otomatik) →
prompt şeması → GT üreteci → eval normalizasyon. Yani tek şema değişikliği 5 kişinin işini etkiler.

---

## 7. KALİTE METRİKLERİ (Sıfır maliyet hedefleri)

Yerel/ücretsiz modeller bulut premium'a göre ~8-15 puan aşağıda. Sprint 4 (final) hedefleri:

| Metrik | Hedef | Not |
|--------|-------|-----|
| Zorunlu alan doğruluğu | ≥ %82 | |
| Sınıflandırma macro-F1 | ≥ %85 | Yaralanma override deterministik → yüksek tutar |
| Halüsinasyon oranı | ≤ %7 | Kaynak alıntı kontrolü ile |
| Otomatik onay precision | ≥ %95 | Muhafazakar eşik |
| Kritik aciliyet recall | ≥ %97 | Yaralanma kaçırmak kabul edilemez |
| Maskeleme recall | ≥ %97 | Regex+sözlük deterministik |
| p95 uçtan uca gecikme | ≤ 60 sn | Rate limit fallback dahil |
| RAG doğruluğu | ≥ %65 | Yerel embedding |

Metrik ölçümü Data Scientist'in işi; her cuma eval koşusu + rapor. Detay `eval/`.

---

## 8. SPRINT HEDEFLERİ (gün numarası değil, hedef + bağımlılık)

Takvim 2 kişilik backend+frontend paralelliğiyle kayabilir; bu yüzden **gün numarasına
güvenme, STATUS.md'ye bak.** Sprint hedefleri:

- **Sprint 1 — İskelet + ilk uçtan uca:** compose api/worker/web açık, `/ingest` → Redis →
  worker pipeline (v0) → Postgres → Pano'da görünür. Şema Gün 2'de donar. LLM router çalışır.
- **Sprint 2 — Kuyruk + Pano tam + Masking v2:** insan onay kuyruğu uçtan uca (BE+FE),
  masking %92, doğrulama kuralları tam, `/istatistik/ozet` çalışır.
- **Sprint 3 — Auth + RAG + Observability:** JWT + rol koruması, yerel embedding + `/soru` RAG,
  Prometheus + Grafana, Metrikler ekranı.
- **Sprint 4 — Cila + Hata Merkezi + Demo:** temiz makinede `docker compose up` ≤15dk,
  DLQ/Hata ekranı, `DEMO_OFFLINE` yedeği, runbook, yük testi, final demo.

---

## 9. KURULUM VE KOMUTLAR

```bash
# İlk kurulum
cp .env.example .env          # Groq + Gemini anahtarlarını LLM Engineer'dan al
docker compose up -d db redis # önce altyapı
alembic upgrade head          # şema (migration hazır olduğunda)
docker compose up -d          # tüm servisler

# Geliştirme
ruff check . && ruff format --check .   # commit öncesi MUST temiz
pytest -q                                # testler
docker compose logs -f worker            # pipeline log takibi

# Frontend
cd web && npm install && npm run dev     # 5173
npm run types                            # OpenAPI'dan TS tipleri
```

Yerel LLM (Ollama) kurulumu ve model çekme, ağ dışı demo (`DEMO_OFFLINE=true`) prosedürü
`docs/runbook.md`'dedir.

---

## 10. CLAUDE CODE İÇİN DAVRANIŞ KURALLARI

- Bir görev başlamadan **STATUS.md**'yi oku; hangi sprint/durum olduğunu varsayma.
- Kod yazarken bu dosyadaki standartlara (Bölüm 4) uy; ihlal edeceksen önce sor.
- DB şeması değiştirecek bir iş istenirse: migration'ı **backend ikilisinin üreteceğini** hatırlat, kendi başına `alembic revision` önerisini uyarıyla ver.
- `claim.json`, `docker-compose.yml`, `.env.example` gibi ortak dosyalara dokunacaksan Bölüm 5/6'daki etkiyi belirt.
- İş bitince: ne yaptığını özetle ve **STATUS.md'ye ne yazılması gerektiğini** öner (dosyayı sen güncelleme, öneriyi ver — insan onaylasın).
- Emin olmadığın mimari kararda ADR öner (`docs/decisions/ADR-000-template.md` formatında).
- Türkçe konuş, kodu İngilizce yaz, prompt'ları Türkçe yaz.

---

*Bu dosya sabit kurallardır. Güncel proje durumu için → `docs/STATUS.md`.*
*Son güncelleme: kurulum aşaması (Sprint 1 öncesi).*
