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
## Model rotation
## Incident playbook
