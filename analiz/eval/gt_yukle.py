# analiz/eval/gt_yukle.py
import os

import pandas as pd


def gt_verisini_getir(dosya_yolu: str = None) -> pd.DataFrame:
    """Veri Mühendisliği (DE) tarafından hazırlanan Ground Truth veri setini yükler.

    Eğer dosya verilmezse, sistemi test etmek için 100 satırlık sentetik bir
    DataFrame döner.
    """
    # Eğer gerçek bir dosya yolu verilirse onu oku
    if dosya_yolu and os.path.exists(dosya_yolu):
        if dosya_yolu.endswith(".csv"):
            return pd.read_csv(dosya_yolu)
        elif dosya_yolu.endswith(".json"):
            return pd.read_json(dosya_yolu)
        elif dosya_yolu.endswith(".jsonl"):
            return pd.read_json(dosya_yolu, lines=True)
        else:
            raise ValueError(
                "Desteklenmeyen format. Sadece CSV, JSON veya JSONL desteklenir."
            )

    # Dosya yoksa Sprint 1 testi için 100 kayıtlık veri simülasyonu üret
    print(
        "Sistem Mesajı: Gerçek GT veri yolu bulunamadı. "
        "100 kayıtlık test verisi üretiliyor..."
    )

    mock_data = []
    for i in range(1, 101):
        if i % 5 != 0:
            alinti_veri = {"alinti": "Araca arkadan carptilar"}
        else:
            alinti_veri = {"alinti": "Tekerlek koptu"}

        mock_data.append(
            {
                "id": i,
                "tahmin_police_no": f"POL-100{i}",
                "gt_police_no": f"POL-100{i}",
                "tahmin_plaka": f"34 ABC {i}",
                "gt_plaka": f"34 ABC {i}",
                "tahmin_olay_tarihi": "2026-07-25",
                "gt_olay_tarihi": "2026-07-25" if i % 10 != 0 else None,
                "tahmin_hasar_aciklamasi": "Carpisma",
                "gt_hasar_aciklamasi": "Carpisma",
                "gt_icerik_tipi": "hasar_ihbari",
                "tahmin_icerik_tipi": "hasar_ihbari" if i % 15 != 0 else "diger",
                "gt_aciliyet": "normal",
                "tahmin_aciliyet": "normal" if i % 20 != 0 else "acil",
                "ham_metin": f"Kaza raporu {i}. Araca arkadan carptilar.",
                "kaynak_referanslari": {"hasar": alinti_veri},
            }
        )

    return pd.DataFrame(mock_data)