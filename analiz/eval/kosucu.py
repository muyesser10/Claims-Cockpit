# analiz/eval/kosucu.py
import pandas as pd
from analiz.eval.metrikler import alan_dogruluk, siniflandirma_f1, halusinasyon_orani

def degerlendir(df: pd.DataFrame) -> dict:
    """
    Model çıktılarını (tahmin) ve Ground Truth (gt) verilerini 
    içeren DataFrame'i alıp tüm metrikleri hesaplar ve genel bir rapor sunar.
    """
    # 1. Sınıflandırma Metrikleri
    siniflandirma_skorlari = siniflandirma_f1(df)
    
    # 2. Halüsinasyon Oranı
    halusinasyon = halusinasyon_orani(df)
    
    # 3. Alan Doğruluk Ortalama
    alan_skorlari_list = []
    for _, row in df.iterrows():
        ayiklanan = {
            "police_no": row.get("tahmin_police_no"),
            "plaka": row.get("tahmin_plaka"),
            "olay_tarihi": row.get("tahmin_olay_tarihi"),
            "hasar_aciklamasi": row.get("tahmin_hasar_aciklamasi")
        }
        gt = {
            "police_no": row.get("gt_police_no"),
            "plaka": row.get("gt_plaka"),
            "olay_tarihi": row.get("gt_olay_tarihi"),
            "hasar_aciklamasi": row.get("gt_hasar_aciklamasi")
        }
        alan_skoru = alan_dogruluk(ayiklanan, gt)["ortalama"]
        alan_skorlari_list.append(alan_skoru)
    
    ortalama_alan_dogrulugu = sum(alan_skorlari_list) / max(len(alan_skorlari_list), 1)

    # Sonuçları tek bir raporda birleştir
    rapor = {
        "siniflandirma_skorlari": siniflandirma_skorlari,
        "halusinasyon_orani": halusinasyon,
        "ortalama_alan_dogrulugu": round(ortalama_alan_dogrulugu, 3)
    }
    
    return rapor

if __name__ == "__main__":
    print("Koşucu modülü başarıyla yüklendi ve göreve hazır!")