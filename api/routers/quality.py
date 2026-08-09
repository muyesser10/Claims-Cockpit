# api/routers/quality.py
"""Kalite metrikleri — Metrikler ekranının okuduğu §7 tablosu.

Sayılar burada hesaplanmaz. eval/report.py haftalık koşulardan
eval/reports/quality_report.json'ı üretir, bu endpoint onu servis eder. Ayrım
kasıtlı: metrik ölçümü modele para harcayan ve dakikalar süren bir iş, bir HTTP
isteğinin içinde yapılacak şey değil — ve ekranda görünen sayının incelenmiş bir
dosyadan geldiği, o an hesaplanmadığı garanti olmalı.

Dosya süreç ömrü boyunca bir kez okunur ve önbelleğe alınır: içerik ancak yeni
bir eval koşusu commit'lendiğinde değişir, o da yeni bir image demektir.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_current_user
from api.models.db import User
from api.models.schemas import QualityReportOut

router = APIRouter(prefix="/istatistik", tags=["istatistik"])

# api/ ile eval/reports/ kardeş klasörler: repoda da, image'da da (api/Dockerfile
# ikisini de /app altına kopyalar).
REPORT_PATH = Path(__file__).resolve().parents[2] / "eval" / "reports" / "quality_report.json"


@lru_cache(maxsize=1)
def _load_report() -> QualityReportOut:
    """Raporu diskten oku ve doğrula.

    Pydantic'ten geçirilerek okunur: bozuk ya da eski şemalı bir dosya, ekranda
    yarım tabloya dönüşmek yerine burada patlar.
    """
    return QualityReportOut.model_validate_json(REPORT_PATH.read_text(encoding="utf-8"))


@router.get("/kalite", response_model=QualityReportOut)
def get_kalite(_user: User = Depends(get_current_user)) -> QualityReportOut:
    """CLAUDE.md §7 kalite tablosu: metrik başına ölçüm, hedef ve künye.

    Her satır kendi örneklemini, kaynak koşusunu ve ölçüm tarihini taşır —
    sekiz metrik farklı koşulardan geldiği için tek bir tarih yanıltıcı olurdu.
    """
    try:
        return _load_report()
    except FileNotFoundError as exc:
        # Rapor dosyası yoksa bu bir sunucu hatasıdır, boş tablo değil: ekran
        # "henüz ölçülmedi" ile "ölçümü bulamadım"ı ayırt edebilmeli.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kalite raporu bulunamadı. `python -m eval.report` ile üretilmeli.",
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kalite raporu okunamadı: dosya bozuk ya da şeması eski.",
        ) from exc
