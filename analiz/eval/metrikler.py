# analiz/eval/metrikler.py
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score

# Sprint 1 - Metrik #1: Zorunlu Alan Doğruluğu
ZORUNLU_ALANLAR = ["police_no", "plaka", "olay_tarihi", "hasar_aciklamasi", "ilce"]


def alan_dogruluk(ayiklanan: dict, gt: dict) -> dict:
    """LLM tarafından ayıklanan alanların Ground Truth (GT) ile

    birebir eşleşip eşleşmediğini kontrol eder.
    """
    sonuc = {}
    for alan in ZORUNLU_ALANLAR:
        a = _normalize(ayiklanan.get(alan))
        g = _normalize(gt.get(alan))
        sonuc[alan] = int(a == g)

    sonuc["ortalama"] = sum(sonuc.values()) / len(ZORUNLU_ALANLAR)
    return sonuc


def _normalize(val):
    """Metin karşılaştırmalarında küçük harf/boşluk ve Null/NaN hatalarını eler."""
    if pd.isna(val) or val is None:
        return None

    if isinstance(val, str):
        temiz = val.strip().lower()
        if temiz in ["", "null", "none", "nan"]:
            return None
        return temiz

    return val


# Sprint 2 - Metrik #2: Sınıflandırma Detaylı Raporu (F1 + Confusion Matrix)
def siniflandirma_raporu(df: pd.DataFrame) -> dict:
    """İçerik tipi ve aciliyet sınıflandırmaları için macro-F1 skorunu

    ve Confusion Matrix (Karmaşıklık Matrisi) verilerini hesaplar.
    """
    # 1. F1 Skorları
    icerik_f1 = f1_score(df["gt_icerik_tipi"], df["tahmin_icerik_tipi"], average="macro")
    aciliyet_f1 = f1_score(df["gt_aciliyet"], df["tahmin_aciliyet"], average="macro")

    # 2. Etiketleri Çıkar (Matrisin satır/sütun başlıkları için)
    icerik_etiketler = sorted(
        list(set(df["gt_icerik_tipi"].dropna()).union(set(df["tahmin_icerik_tipi"].dropna())))
    )
    aciliyet_etiketler = sorted(
        list(set(df["gt_aciliyet"].dropna()).union(set(df["tahmin_aciliyet"].dropna())))
    )

    # 3. Confusion Matrix Hesaplama
    icerik_cm = confusion_matrix(
        df["gt_icerik_tipi"], df["tahmin_icerik_tipi"], labels=icerik_etiketler
    )
    aciliyet_cm = confusion_matrix(
        df["gt_aciliyet"], df["tahmin_aciliyet"], labels=aciliyet_etiketler
    )

    return {
        "f1_skorlari": {
            "icerik_tipi_macro_f1": round(icerik_f1, 3),
            "aciliyet_macro_f1": round(aciliyet_f1, 3),
            "birlesik": round((icerik_f1 + aciliyet_f1) / 2, 3),
        },
        "confusion_matrices": {
            "icerik_tipi": {
                "etiketler": icerik_etiketler,
                # Dict/JSON formatına uyumlu olması için listeye çevrildi
                "matris": icerik_cm.tolist(),
            },
            "aciliyet": {
                "etiketler": aciliyet_etiketler,
                "matris": aciliyet_cm.tolist(),
            },
        },
    }


# Sprint 1 - Metrik #3: Halüsinasyon Oranı
def halusinasyon_orani(df: pd.DataFrame) -> float:
    """LLM'in verdiği alıntının (referansın) ham metinde bulunma durumunu ölçer."""
    toplam_referans = 0
    halusinasyon_referans = 0

    for _, row in df.iterrows():
        ham = str(row["ham_metin"]).lower()
        kaynaklar = row.get("kaynak_referanslari", {})

        if pd.isna(kaynaklar) or not isinstance(kaynaklar, dict):
            kaynaklar = {}

        for _alan, ref in kaynaklar.items():
            alinti = str(ref.get("alinti", "")).lower().strip()
            if len(alinti) < 5:
                continue

            toplam_referans += 1
            if alinti not in ham:
                halusinasyon_referans += 1

    return round(halusinasyon_referans / max(toplam_referans, 1), 3)
