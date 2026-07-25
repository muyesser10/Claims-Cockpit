# analiz/eval/metrikler.py
import pandas as pd
from sklearn.metrics import f1_score

# Sprint 1 - Metrik #1: Zorunlu Alan Doğruluğu
ZORUNLU_ALANLAR = ["police_no", "plaka", "olay_tarihi", "hasar_aciklamasi"]

def alan_dogruluk(ayiklanan: dict, gt: dict) -> dict:
    """
    LLM tarafından ayıklanan alanların Ground Truth (GT) ile
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
    """Metin karşılaştırmalarında küçük harf/boşluk hatalarını eler."""
    if val is None:
        return None
    if isinstance(val, str):
        return val.strip().lower()
    return val

# Sprint 1 - Metrik #2: Sınıflandırma Macro-F1
def siniflandirma_f1(df: pd.DataFrame) -> dict:
    """
    İçerik tipi ve aciliyet sınıflandırmaları için macro-F1 skorunu hesaplar.
    """
    icerik_f1 = f1_score(df["gt_icerik_tipi"], df["tahmin_icerik_tipi"], average="macro")
    aciliyet_f1 = f1_score(df["gt_aciliyet"], df["tahmin_aciliyet"], average="macro")
    return {
        "icerik_tipi_macro_f1": round(icerik_f1, 3),
        "aciliyet_macro_f1": round(aciliyet_f1, 3),
        "birlesik": round((icerik_f1 + aciliyet_f1) / 2, 3),
    }

# Sprint 1 - Metrik #3: Halüsinasyon Oranı
def halusinasyon_orani(df: pd.DataFrame) -> float:
    """
    LLM'in verdiği alıntının (referansın) ham metinde bulunma durumunu ölçer.
    """
    toplam_referans = 0
    halusinasyon_referans = 0
    
    for _, row in df.iterrows():
        ham = str(row["ham_metin"]).lower()
        kaynaklar = row.get("kaynak_referanslari", {})
        
        for alan, ref in kaynaklar.items():
            alinti = str(ref.get("alinti", "")).lower().strip()
            if len(alinti) < 5:
                continue  # Çok kısa alıntıları atla
            
            toplam_referans += 1
            if alinti not in ham:
                halusinasyon_referans += 1
                
    return round(halusinasyon_referans / max(toplam_referans, 1), 3)