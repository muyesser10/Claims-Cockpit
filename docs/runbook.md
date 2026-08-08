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

## Backup and restore
## Model rotation
## Incident playbook
