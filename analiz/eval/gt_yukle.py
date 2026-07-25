# analiz/eval/gt_yukle.py
import pandas as pd
import os

def gt_verisini_getir(dosya_yolu: str = None) -> pd.DataFrame:
    """
    Veri Mühendisliği (DE) tarafından hazırlanan Ground Truth veri setini yükler.
    Eğer dosya verilmezse, sistemi test etmek için 100 satırlık sentetik bir DataFrame döner.
    """
    # Eğer gerçek bir dosya yolu verilirse onu oku
    if dosya_yolu and os.path.exists(dosya_yolu):
        if dosya_yolu.endswith('.csv'):
            return pd.read_csv(dosya_yolu)
        elif dosya_yolu.endswith('.json'):
            return pd.read_json(dosya_yolu)
        else:
            raise ValueError("Desteklenmeyen format. Sadece CSV veya JSON.")
    
    # Dosya yoksa Sprint 1 testi için 100 kayıtlık veri simülasyonu üret
    print("Sistem Mesajı: Gerçek GT veri yolu bulunamadı. 100 kayıtlık test verisi üretiliyor...")
    
    mock_data = []
    for i in range(1, 101):
        mock_data.append({
            "id": i,
            "tahmin_police_no": f"POL-100{i}",
            "gt_police_no": f"POL-100{i}",
            "tahmin_plaka": f"34 ABC {i}", 
            "gt_plaka": f"34 ABC {i}",
            "tahmin_olay_tarihi": "2026-07-25",
            # %10 ihtimalle tarih eksik gelsin (Alan doğruluğu testi)
            "gt_olay_tarihi": "2026-07-25" if i % 10 != 0 else None, 
            "tahmin_hasar_aciklamasi": "Carpisma",
            "gt_hasar_aciklamasi": "Carpisma",
            "gt_icerik_tipi": "hasar_ihbari",
            # %6 ihtimalle yanlış sınıflandırma
            "tahmin_icerik_tipi": "hasar_ihbari" if i % 15 != 0 else "diger", 
            "gt_aciliyet": "normal",
            # %5 ihtimalle yanlış aciliyet sınıflandırması
            "tahmin_aciliyet": "normal" if i % 20 != 0 else "acil", 
            "ham_metin": f"Kaza raporu {i}. Araca arkadan carptilar.",
            "kaynak_referanslari": {
                # %20 ihtimalle metinde olmayan halüsinasyon bilgi
                "hasar": {"alinti": "Araca arkadan carptilar"} if i % 5 != 0 else {"alinti": "Tekerlek koptu"}
            }
        })
    
    return pd.DataFrame(mock_data)