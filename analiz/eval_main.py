# analiz/eval_main.py
import sys
from pathlib import Path

# Proje kök dizinini Python yoluna ekliyoruz
PROJ_KOK = Path(__file__).resolve().parent.parent
if str(PROJ_KOK) not in sys.path:
    sys.path.insert(0, str(PROJ_KOK))

from analiz.eval.gt_yukle import gt_verisini_getir
from analiz.eval.kosucu import degerlendir

def ana_dongu():
    print("\n" + "="*55)
    print(" 🚀 SPRINT 1: MODEL DEĞERLENDİRME SÜRECİ BAŞLIYOR")
    print("="*55)
    
    # 1. Veriyi Yükle
    df_veriset = gt_verisini_getir()
    print(f"[+] Toplam {len(df_veriset)} kayıt başarıyla yüklendi.\n")
    
    # 2. Modeli Değerlendir
    print("[+] Metrik hesaplamaları yapılıyor (Sınıflandırma, Halüsinasyon, Alan Doğruluğu)...\n")
    rapor = degerlendir(df_veriset)
    
    # 3. Sonuçları Ekrana Bas
    print("="*55)
    print(" 🏆 NİHAİ MODEL BAŞARI RAPORU (100 Kayıt)")
    print("="*55)
    for metrik, skor in rapor.items():
        print(f" 📊 {metrik.upper()}: {skor}")
    print("="*55)
    print("\n✅ Data Science (DS) değerlendirme altyapısı eksiksiz tamamlandı!\n")

if __name__ == "__main__":
    ana_dongu()