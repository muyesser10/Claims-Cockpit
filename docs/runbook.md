# Runbook

> Filled in during Sprint 4 (task S4-8).

## Setup

### rag_readonly rolü (Text-to-SQL yolu)

`/soru`'nun Text-to-SQL yolu, modelin ürettiği sorguyu `rag_readonly` rolüyle
çalıştırır: yalnızca `claims_flat` ve `audit_trail` üzerinde `SELECT`. Rolü
`migrations/init/01-create-readonly-role.sh` oluşturur ve bu script iki nedenle
elle çalıştırılmak zorunda kalabilir:

1. **Volume'ün doluysa hiç çalışmamıştır.** Postgres image'ı
   `/docker-entrypoint-initdb.d`'yi yalnızca veri dizini **boşken** çalıştırır.
   Reponun bu değişiklikten önceki hâliyle bir `db_data` volume'ü oluşturmuş
   olan herkes bu durumda.
2. **Taze bir volume'de bile grant'ler eksik kalır.** Script migration'lardan
   önce koşar; o anda `claims_flat` ve `audit_trail` henüz yoktur. Rol
   oluşturulur, tablo grant'leri için uyarı basılır.

Her iki durumda da çözüm aynı: `alembic upgrade head` sonrası script'i bir kez
elle çalıştırın. Script idempotent, tekrar çalıştırmak her zaman güvenli.

```bash
# .env'de RAG_READONLY_DB_PASSWORD dolu olmalı
docker compose up -d db
docker compose exec db bash /docker-entrypoint-initdb.d/01-create-readonly-role.sh
```

Doğrulama — rol okuyabilmeli, yazamamalı:

```bash
# claims_flat okunabiliyor mu?
docker compose exec db psql -U rag_readonly -d claims_cockpit \
  -c "SELECT count(*) FROM claims_flat;"

# audit_trail'e yazamıyor olmalı → "ERROR: permission denied for table audit_trail"
docker compose exec db psql -U rag_readonly -d claims_cockpit \
  -c "INSERT INTO audit_trail (step) VALUES ('x');"

# ham claims tablosu görünmemeli → "ERROR: permission denied for table claims"
docker compose exec db psql -U rag_readonly -d claims_cockpit \
  -c "SELECT data FROM claims LIMIT 1;"
```

`RAG_READONLY_DATABASE_URL` tanımsızsa rag servisi ayağa kalkar ama
`DATABASE_URL`'e düşer ve izolasyon **uygulanmaz**; açılış logunda
`rag_readonly_url_not_set` uyarısı görünür. Log'da bu satır varsa `.env`
eksiktir.
### Sıfırdan kurulum

```bash
cp .env.example .env          # OPENAI_API_KEY'i LLM Engineer'dan alın
docker compose up -d --build  # 9 servis; ilk build birkaç dakika sürer
docker compose exec api alembic upgrade head
```

**Üçüncü adım zorunlu.** Compose migration çalıştırmıyor; onsuz tablolar yok ve
api ayağa kalkar ama her istekte SQL hatası verir:

```
[SQL: SELECT count(*) AS count_1 FROM claims WHERE claims.status = ...]
```

`docker compose up` ile `alembic upgrade head` arasındaki bu pencerede api
loglarında bu hataları görmek **beklenen** bir geçiş durumudur, kurulum bozuk
değildir. Migration'dan sonra kaybolur (`GET /queue` → 401, 500 değil).

CLAUDE.md §9 bu komutu host'ta çalıştırmayı söylüyor; **birincil yöntem yukarıdaki
`docker compose exec api` biçimidir** — host'ta Python 3.11 + bağımlılıkların
kurulu olmasını gerektirmez. api image'ı alembic'i, `migrations/` dizinini ve
`alembic.ini`'yi zaten içeriyor.

Kurulumun ayakta olduğunu doğrulama:

```bash
docker compose ps                      # 9 servis; db, redis, rag "healthy"
curl http://localhost:8000/health      # {"status":"ok","service":"api"}
curl -o /dev/null -w '%{http_code}\n' http://localhost:8000/queue   # 401
```

`rag` servisi ilk açılışta embedding modelini indirir (471 MB) ve hazır olması
~26-45 sn sürer. Healthcheck'i `/health`'in `model_ready` alanına bakar, yani
`docker compose ps` "healthy" gösterdiğinde gerçekten soru alabilir demektir.

**api, rag'i beklemez.** Bağımlılık `service_started` (`service_healthy` değil):
Pano, Kuyruk ve Metrikler ekranlarının rag'e hiç ihtiyacı yok ve modelin
yüklenmesini beklemek kokpitin tamamını ~40 sn geciktirirdi. Bunun bedeli şu:
bu pencerede Soru ekranı kullanılırsa **503 + Türkçe hata mesajı** döner
(`api/routers/question.py` erişilemeyen rag'i böyle karşılıyor). Kabul edilmiş
bir ödünleşimdir, arıza değildir.

> **Demoda:** Soru ekranını göstermeden önce `docker compose ps` ile `rag`
> servisinin `healthy` olduğunu kontrol edin.

Model `hf_cache` adlı named volume'de tutulur ve `worker` ile `rag` arasında
paylaşılır; `docker compose down` (volume silmeden) sonrasında yeniden inmez.
`docker compose down -v` volume'ü de siler, o zaman tekrar iner.

### Port çakışması

Host portları `.env`'den ayarlanır — makinenizde 5432'de yerel bir Postgres
varsa `POSTGRES_HOST_PORT=5433` yazmanız yeterli (`REDIS_HOST_PORT`,
`WORKER_METRICS_HOST_PORT` de aynı şekilde). **`docker-compose.override.yml`
artık gerekli değil**; hâlâ çalışır ve kişisel ayarlar için kullanılabilir
(gitignore'da), ama sırf port değiştirmek için yazmaya gerek yok.

Override yazacaksanız bir tuzak: **Compose `ports` listelerini birleştirir,
ezmez.** Override'da `ports: ["55432:5432"]` yazmak eski `5432:5432` girdisini
kaldırmaz; ikisini birden yayınlamaya çalışır ve çakışma sürer. Değiştirmek için
`!override` etiketi gerekir:

```yaml
services:
  db:
    ports: !override ["55432:5432"]
```

### Konteyner adları

Servislerin sabit `container_name`'i yoktur (bir zamanlar vardı ve başka bir
klondan kalan konteyner `docker compose up`'ı tamamen düşürüyordu). Konteynerlere
servis adıyla erişin:

```bash
docker compose logs -f worker
docker compose exec api alembic upgrade head
docker compose exec db psql -U claims -d claims_cockpit
```

## Demo hazırlığı (S4-6)

Çevrimdışı demo (`DEMO_OFFLINE=true`), LLM cevaplarını `demo/fixtures/`
altındaki kayıtlı setten okur. Maskeleme, embedding, SQL guard, gerçek sorgu
çalıştırma, sayı ve atıf doğrulaması **gerçek** çalışmaya devam eder — sahte
olan yalnızca en alttaki OpenAI çağrısıdır.

### Ne zaman çalıştırılır

Demodan önce, **temiz bir veritabanı üzerinde** bir kez. Veritabanı zaten
doluysa önce sıfırlayın (`docker compose down -v` + `up -d` + `alembic upgrade
head`), yoksa sayımlar birikir ve `/soru`'nun SQL cevapları tutmaz.

### Adımlar

```bash
# .env'de DEMO_OFFLINE=true olmalı; worker bu değişkeni okuyarak başlar
docker compose up -d --build
docker compose exec api alembic upgrade head

# Script HOST'ta çalışır (container içinde değil): .dockerignore data/*.jsonl'ı
# image'lara koymuyor, script de tam o dosyaları okuyor. Host'un Python ortamı
# (requirements.txt) ve yayınlanmış portlar gerekiyor.
DEMO_OFFLINE=true \
DATABASE_URL=postgresql://claims:<parola>@localhost:5432/claims_cockpit \
python -m demo.seed_demo_db
```

`.env`'deki `DATABASE_URL` `db:5432`'yi gösterir ve yalnızca compose ağının
içinden çözülür; host'tan çalıştırırken yayınlanmış portu veren bir değerle
geçmek gerekir (yukarıdaki gibi).

Script `data/texts.jsonl`'ın ilk 60 kaydını `/ingest`'e gönderir, worker
kuyruğu boşalana kadar bekler ve sonucu doğrular:

```
=== sonuç ===
  raw_messages.status=classified: 60
  claims:           60
  claim_embeddings: 60
Demo veritabanı hazır.
```

Ölçüldü: 60 kayıt uçtan uca ~50 sn (ilk embedding çağrısında e5 modelinin
yüklenmesi bunun yaklaşık yarısı; ilerleme `bekleniyor... 0/60` diye görünür,
takılmış değildir).

Yararlı parametreler: `--limit` (kaç kayıt), `--wait-timeout` (varsayılan 120
sn; aşılırsa uyarı verir ama hata vermez), `--api-url` (varsayılan
`http://localhost:8000`).

### Neden tam 60 kayıt

`demo/fixtures/demo_rag.jsonl`'daki `/soru` cevaplarının içindeki sayılar (5
kritik, 9 dolu hasarı, İzmir 14 / Ankara 11 / Antalya 11 / İstanbul 10 / Bursa
8) **bu 60 kayda karşı ölçüldü**. Çalışma anında bu sayılar doğrulanıyor
(`worker/rag/sql_answer.py`), dolayısıyla farklı bir alt küme **yanlış cevap
üretmez** — cevabı tamamen gizler ve operatör bir ret mesajı görür. Güvenli
ama demonun SQL yarısını boşaltır. `--limit`'i değiştirirseniz RAG
fixture'larını da yeniden üretin:

```bash
python demo/fixtures/build_rag_fixtures.py   # içindeki sayıları elle güncelledikten sonra
```

### DEMO_OFFLINE kapalıyken

Script çalışmayı reddeder ve nedenini söyler: 60 kayıt × 3 LLM çağrısı = 180
canlı OpenAI isteği, yani parayla ödenen bir kaza. Kontrol script'in kendi
sürecinin ortamına bakar; asıl belirleyici olan worker'ın ayarıdır:

```bash
docker compose exec worker env | grep DEMO_OFFLINE
```

## Backup and restore

### Neden `pg_dump`, neden özel format

`claim_embeddings.embedding` kolonu `vector(384)` — pgvector'e özgü bir tip.
Standart `pg_dump` bunu sorunsuz taşır (extension hedef DB'de kuruluysa,
bu repo'nun `pgvector/pgvector:pg16` image'ı zaten içeriyor), ekstra bir
bayrak gerekmiyor. Custom format (`-F c`) seçildi çünkü `pg_restore` ile
seçici geri yükleme (tek tablo, sadece şema) yapılabiliyor — düz SQL
dump'ın aksine.

### Backup

```bash
docker compose exec db pg_dump -U claims -d claims_cockpit -F c -f /tmp/backup.dump
docker compose cp db:/tmp/backup.dump ./backup_$(date +%Y%m%d_%H%M%S).dump
docker compose exec db rm /tmp/backup.dump   # container içinde bırakma
```

### Restore

```bash
docker compose cp ./backup_YYYYMMDD_HHMMSS.dump db:/tmp/restore.dump
docker compose exec db pg_restore -U claims -d claims_cockpit --clean --if-exists /tmp/restore.dump
docker compose exec db rm /tmp/restore.dump
```

`--clean --if-exists`: hedef DB'de var olan nesneleri önce düşürür. Bunsuz,
dolu bir DB'ye restore "already exists" hatalarıyla yarım kalır.

### `rag_readonly` rolü restore sonrası

Rol `migrations/init/`'teki bir init script'iyle geliyor, **restore bunu
kapsamaz** — `pg_dump`, rolleri değil verileri yedekler. Restore sonrası
Setup bölümündeki `01-create-readonly-role.sh` adımını tekrar çalıştırın,
idempotent olduğu için zarar vermez:

```bash
docker compose exec db bash /docker-entrypoint-initdb.d/01-create-readonly-role.sh
```

### Ne yedeklenmiyor

`hf_cache` named volume'ü (embedding modeli, ~471 MB) bu prosedürün dışında
— o bir model dosyası, kurtarılacak veri değil, restore sonrası ilk
başlangıçta zaten yeniden iner (bkz. Setup → "Sıfırdan kurulum").

**Ölçüldü (2026-08-09, 8 claim'lik yerel geliştirme DB'si):** backup 0,66 sn,
restore 0,61 sn, dump dosyası 18,3 KB. Doğrulama: restore öncesi/sonrası
`claims` kayıt sayısı birebir eşleşti (8=8). **Not:** bu rakamlar küçük bir
geliştirme veritabanına ait — demo/production ölçeğinde (yüzlerce/binlerce
kayıt, embedding vektörleri dahil) süre ve boyut orantılı büyür, ama prosedür
aynı kalır.

## Model rotation

### LLM model/sağlayıcı değişimi (ADR-001)

Modeller `.env`'de, kod değişikliği gerektirmez:

```bash
LLM_MODEL_CHEAP=gpt-4o-mini    # classification, triage, RAG routing
LLM_MODEL_STRONG=gpt-4o        # extraction, Text-to-SQL, RAG answers
```

Değiştirdikten sonra:

```bash
docker compose up -d --build worker rag   # ikisi de LLM client'ı içeriyor (ADR-003)
```

**Zorunlu sonraki adım:** `eval/report.py`'nin ürettiği Metrikler tablosu
(§7) **eski modelin** ölçümüdür — model değişince bu tablo yanlışı doğru
gösterir. Yeniden ölçüp raporu yeniden üretin:

```bash
python -m eval --run --seed 42
python -m eval.report
```

ve yeni `eval/reports/quality_report.json`'ı commit'leyip `api`'yi yeniden
build edin (Metrikler ekranının okuduğu dosya budur, `api/Dockerfile`
sadece bu dosyayı kopyalıyor — bkz. `api/routers/quality.py`).

### Embedding modeli değişimi (ADR-002)

Bu, LLM model değişiminden **çok daha ağır**: mevcut `claim_embeddings`
satırlarının tamamı eski modelin vektör uzayında, yeni modelle
karşılaştırılamaz — yarım geçiş, retrieval'i sessizce bozar.

1. `worker/embedding/encoder.py`'de model adını değiştirin
2. Yeni model farklı boyut üretiyorsa (`intfloat/multilingual-e5-small`
   384 boyutlu; başka bir model farklı olabilir) `EMBED_DIM` **ve**
   migration'daki `VECTOR(384)` güncellenmeli — kolon boyutu sabit
   kodlanmış, tip uyuşmazlığında INSERT hatası alırsınız
3. Tüm embedding'leri yeniden üretin:
```bash
   docker compose exec worker python -m scripts.backfill_embeddings --force
```
4. RAG accuracy'yi yeniden ölçün (Metrikler ekranındaki `sql`/`retrieval`/
   `refusal` kırılımı bunun için var — retrieval kategorisi doğrudan
   embedding kalitesinin göstergesi)

### Fallback sağlayıcı (Groq/Gemini/Ollama) — henüz yok

`.env.example`'da anahtarlar duruyor ama `worker/llm/client.py` onları
okumuyor (ADR-001'in "Still open" maddesi). Birisi bunu aktifleştirmeden
önce STATUS.md'deki bu maddeyi kapatmalı; bu bölüm o güne kadar sadece
konfigürasyon iskeletinin var olduğunu, çalışan bir yolun olmadığını
belgeler.

## Incident playbook

Her madde: belirti → muhtemel sebep → komut. Sırayla değil, belirtiye göre
atlayın.

### Worker kuyruğu işlemiyor / mesajlar `dead_letter`'a düşüyor

```bash
docker compose logs --tail=100 worker
```

- **`extraction_error` audit adımı** — `.env`'de `OPENAI_API_KEY` eksik/geçersiz.
  Claim `in_human_review`'da kalır, kaybolmaz (tasarım gereği, aciliyet
  sıralaması bozulmaz).
- **DB bağlantı hatası, worker açılışta patlıyor** — worker `depends_on:
  service_started` kullanıyor (`service_healthy` değil, bilinen risk —
  STATUS.md). `db` henüz hazır olmadan worker başlamış olabilir:
```bash
  docker compose restart worker
```

### `/soru` 503 dönüyor

`rag` servisi embedding modelini yüklüyor olabilir (ilk açılış ~26-45 sn,
bkz. Setup).

```bash
docker compose ps   # rag "healthy" mi?
```

`Restarting` durumundaysa:
```bash
docker compose logs rag
```
`rag_readonly_url_not_set` uyarısı görünüyorsa `.env`'de
`RAG_READONLY_DATABASE_URL` eksik — Setup bölümündeki rol adımını
tamamlamadan `rag` ayakta kalır ama izolasyon uygulanmaz.

### "relation does not exist" / migration hatası

```bash
docker compose exec api alembic upgrade head
```
çalıştırılmamış demektir. Bu, `docker compose up` sonrası kısa bir süre
için **beklenen** bir geçiş durumudur (bkz. Setup) — ama dakikalar sonra
hâlâ görünüyorsa migration gerçekten hiç koşmamıştır.

### `worker/rag/` veya `worker/embedding/` değişti ama `rag` servisi eski davranıyor

İkisi aynı image'dan build oluyor (ADR-003) — biri rebuild edilip diğeri
unutulursa biri bayat kalır, hata vermez, sessizce yanlış davranır:

```bash
docker compose up -d --build worker rag
```

### Metrikler ekranı 503 dönüyor

```bash
curl http://localhost:8000/istatistik/kalite -H "Authorization: Bearer <token>"
```
`"Kalite raporu bulunamadı"` → `eval/reports/quality_report.json` image'a
hiç girmemiş, `python -m eval.report` çalıştırılıp commit'lenmemiş demektir.
`"dosya bozuk ya da şeması eski"` → rapor `QualityReportOut` şemasıyla
uyuşmuyor, muhtemelen eski bir `eval/report.py` sürümünden kalma dosya;
yeniden üretin.

### Port çakışması (5432, 6379, vb.)

```bash
POSTGRES_HOST_PORT=5433   # .env'e ekleyin
```
Bkz. Setup → "Port çakışması". `docker-compose.override.yml` gerekmez.

### Genel kural: "bozuldu ama neden bilmiyorum"

```bash
docker compose ps                              # hangi servis Up değil
docker compose logs --tail=50 <servis_adı>      # son hata
docker compose exec db psql -U claims -d claims_cockpit -c "\dt"   # tablolar gerçekten var mı
```

Bu üç komut, bu playbook'taki maddelerin %90'ının teşhisini kapsar.