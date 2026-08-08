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
"healthy" olduğunda gerçekten soru alabilir demektir. api, rag healthy olana
kadar başlamaz — kokpitin tamamı bu süre kadar geç açılır, bu bilinçli bir
tercihtir (Soru ekranı açılır açılmaz 503 vermesin diye).

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

## Backup and restore
## Model rotation
## Incident playbook
