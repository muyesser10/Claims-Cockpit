# demo/fixtures — çevrimdışı demo cevapları (S4-6)

`DEMO_OFFLINE=true` iken `worker/llm/client.py`'nin `get_llm_client()` fabrikası,
OpenAI çağrısının yerine buradaki kayıtlı cevapları koyar. Değişen **yalnızca en
alt katman**: instructor şemayı yine doğrular, `structured()` yine süre ölçer ve
yine `llm_call` denetim satırını yazar. Yani ağsız demo, canlı demoyla aynı kod
yolunu çalıştırır.

## `eval/fixtures/` ile karıştırmayın

Bu dizin ile `eval/fixtures/` **kasıtlı olarak ayrıdır ve asla birbirinin yerine
kullanılmaz**: `eval/fixtures/` ölçüm girdisidir (bir koşunun neye karşı
puanlandığı), `demo/fixtures/` ise gösterim çıktısıdır (modelin ne cevap vermiş
gibi yapacağı). Aynı dosyaları paylaşsalardı bir eval koşusu kendi kendini
puanlardı; `get_llm_client()`'ın `LlmClient.__init__`'e değil ayrı bir fabrikaya
konmasının sebebi de budur — eval doğrudan `LlmClient()` kurar ve fixture'ları
hiçbir koşulda göremez.

Dosya adlarındaki `demo_` öneki bu ayrımı görünür kılar; yükleyici zaten yalnızca
`demo_*.jsonl` kalıbını okur.

## Format

Satır başına bir JSON nesnesi (JSONL):

```json
{"gt_id": "GT-000000", "response_model": "ClaimExtraction", "tier": "cheap", "payload": {...}}
```

| Alan | Zorunlu | Anlamı |
|---|---|---|
| `gt_id` | evet | Eşleşme anahtarı. Replay her mesaja `external_ref = gt_id` yazar (`replay/replay.py`). `"*"` joker kayıttır. |
| `response_model` | evet | Pydantic sınıfının **adı** — `client.structured(response_model=...)`'a geçen sınıf. Bugün: `ClaimExtraction`, `SanityCheckResult`. |
| `tier` | hayır | Bilgi amaçlı (`cheap`/`strong`). Tier'ı çağıran belirler; yükleyici bu alanı kullanmaz, okunabilirlik ve grep için durur. |
| `payload` | evet | `response_model(**payload)` ile parse edilir. Şemaya uymazsa demo sırasında değil, burada patlar. |

## İki kural

1. **Her `response_model` için bir `"*"` kaydı zorunludur.** Yükleyici bunu
   doğrular ve eksikse hangi model için eksik olduğunu söyleyerek hata verir.
   Sebebi: demoda jüri kendi cümlesini yazarsa o mesajın `external_ref`'i
   `None` olur ve joker kayda düşmek **her zaman** başarılı olmalıdır.
2. **`gt_id` bulunamazsa sessizce jokere düşülür**, istisna atılmaz. Bozuk
   dosya, eksik joker veya hiç fixture'ı olmayan bir `response_model` ise
   yüklemede açıkça hata verir (`FixtureLoadError`) — bunlar demo hazırlayanın
   sorunudur, sahnede çıkmamalıdır.

## Üretme

```bash
python demo/fixtures/build_extraction_fixtures.py   # -> demo_extraction.jsonl
python demo/fixtures/build_sanity_fixtures.py       # -> demo_sanity.jsonl
```

İkisi de `data/ground_truth_enriched.jsonl`'ı okur ve ürettikleri her payload'ı
gerçek Pydantic sınıfına karşı doğrular; şemaya uymayan bir satır dosyaya hiç
yazılmaz. Dosyalar commit'lenir — demo makinesinde üretim adımı olmamalıdır.

## Bilinen sınır: kaynak alıntıları yok

Ground truth alanların **değerlerini** tutar, o değerlerin metnin neresinde
geçtiğini değil. Bu yüzden `ClaimExtraction.source_references` boş üretiliyor ve
çevrimdışı demoda Kuyruk ekranındaki **kaynak cümle vurgulaması (S2-12) çalışmaz**
— alanlar dolu görünür, altları çizili gelmez. Çökme yok, `unverified_fields` de
boş kalır (otomatik onay kapısı bu yüzden engellemez). Vurgulamayı da göstermek
gerekirse fixture'lara metinde birebir geçen alıntılar eklenmelidir; bu ayrı bir
iştir.

## Kişisel veri

`data/ground_truth_enriched.jsonl` her kaydın yanında bir `_personal` bloğu
taşır (isim, telefon, TC — sentetik). Üreteçler bu bloğu **okumaz ve fixture'a
yazmaz**; yalnızca `expected` bloğu kullanılır. Elle fixture eklerken aynı kurala
uyun, bu dosyalar repoda commit'li duruyor.
