# analiz/testler/test_metrikler.py
import pandas as pd

from analiz.eval.metrikler import alan_dogruluk, halusinasyon_orani


def test_alan_dogruluk_tam_eslesme():
    ayiklanan = {
        "police_no": "POL-2024-88341",
        "plaka": "34 ABC 123",
        "olay_tarihi": "2026-07-14",
        "hasar_aciklamasi": "Park halinde carpiilma",
    }
    gt = {
        "police_no": "pol-2024-88341 ",
        "plaka": "34 ABC 123",
        "olay_tarihi": "2026-07-14",
        "hasar_aciklamasi": "Park halinde carpiilma",
    }
    sonuc = alan_dogruluk(ayiklanan, gt)
    assert sonuc["ortalama"] == 1.0
    assert sonuc["police_no"] == 1


def test_alan_dogruluk_eksik_alan():
    ayiklanan = {
        "police_no": "POL-2024-88341",
        "plaka": "34 ABC 123",
        "olay_tarihi": None,
        "hasar_aciklamasi": "Park halinde carpiilma",
    }
    gt = {
        "police_no": "POL-2024-88341",
        "plaka": "34 ABC 123",
        "olay_tarihi": "2026-07-14",
        "hasar_aciklamasi": "Park halinde carpiilma",
    }
    sonuc = alan_dogruluk(ayiklanan, gt)
    assert sonuc["olay_tarihi"] == 0
    assert sonuc["ortalama"] == 0.75


def test_halusinasyon_orani():
    df = pd.DataFrame(
        [
            {
                "ham_metin": "Dün akşam 34 ABC 123 plakalı aracımla kaza yaptım.",
                "kaynak_referanslari": {
                    "plaka": {"alinti": "34 ABC 123"},
                    "hasar": {"alinti": "ön tampon tamamen koptu"},
                },
            }
        ]
    )
    oranim = halusinasyon_orani(df)
    assert oranim == 0.5
