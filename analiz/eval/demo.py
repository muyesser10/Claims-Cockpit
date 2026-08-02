# analiz/eval/demo.py
import sys
from pathlib import Path

# Proje kök dizinini Python yoluna ekliyoruz (Import hatasını engellemek için)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from analiz.eval.kosucu import degerlendir


def calistir():
    # Sistemimizi test etmek için 2 satırlık sentetik veri seti oluşturuyoruz
    veri = [
        {
            # 1. Kayıt: Kusursuz bir tahmin simülasyonu
            "tahmin_police_no": "POL-123",
            "gt_police_no": "POL-123",
            "tahmin_plaka": "38 MTT 99",
            "gt_plaka": "38 MTT 99",
            "tahmin_olay_tarihi": "2026-07-25",
            "gt_olay_tarihi": "2026-07-25",
            "tahmin_hasar_aciklamasi": "Bariyerlere carpma",
            "gt_hasar_aciklamasi": "Bariyerlere carpma",
            "gt_icerik_tipi": "hasar_ihbari",
            "tahmin_icerik_tipi": "hasar_ihbari",
            "gt_aciliyet": "normal",
            "tahmin_aciliyet": "normal",
            "ham_metin": (
                "Dün yağmurlu havada giderken 1999 model Toyota Corolla 1.6 aracımla "
                "kayıp bariyerlere çarptım. 4A-FE motor bloğuna kadar hasar ulaştı."
            ),
            "kaynak_referanslari": {
                "plaka": {"alinti": "38 MTT 99"},
                "hasar": {"alinti": "bariyerlere çarptım"},
            },
        },
        {
            # 2. Kayıt: Hatalı tahminler ve halüsinasyon içeren bir simülasyon
            "tahmin_police_no": "POL-456",
            "gt_police_no": "POL-456",
            "tahmin_plaka": "34 Z 0000",
            "gt_plaka": "34 Z 0000",
            "tahmin_olay_tarihi": "2026-07-25",
            "gt_olay_tarihi": None,  # Hata (Ground Truth'da yok ama LLM bulmuş)
            "tahmin_hasar_aciklamasi": "Park halinde çarpma",
            "gt_hasar_aciklamasi": "Park halinde çarpma",
            "gt_icerik_tipi": "hasar_ihbari",
            "tahmin_icerik_tipi": "diger",  # Hata (Yanlış sınıflandırma)
            "gt_aciliyet": "acil",
            "tahmin_aciliyet": "normal",  # Hata (Yanlış aciliyet)
            "ham_metin": "Aracıma park halindeyken çarpmışlar.",
            "kaynak_referanslari": {
                "hasar": {"alinti": "camlar tuz buza dönmüş"}  # Halüsinasyon (Ham metinde geçmiyor)
            },
        },
    ]

    df = pd.DataFrame(veri)

    # Koşucuyu çalıştır ve raporu al
    rapor = degerlendir(df)

    print("\n" + "=" * 40)
    print(" 🚀 MODEL DEĞERLENDİRME RAPORU")
    print("=" * 40)
    for anahtar, deger in rapor.items():
        print(f" 📊 {anahtar.upper()}: {deger}")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    calistir()
