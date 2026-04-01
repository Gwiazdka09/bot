import math
from datetime import datetime


# ================================================================
#  MODUL 2 - HELPERY
# ================================================================

def _s(v, domyslna: str = "-") -> str:
    if v is None:
        return domyslna
    try:
        if isinstance(v, float) and math.isnan(v):
            return domyslna
    except TypeError:
        pass
    s = str(v).strip()
    return domyslna if s.lower() in ("nan", "none", "null", "") else s

def _parse_date(data_str) -> datetime | None:
    if not data_str or str(data_str) in ("-", "nan", "none"):
        return None
    s = str(data_str).strip()
    # UWAGA: nie uzywaj len(fmt) jako dlugosci stringa daty –
    # format string ma inną długość niż reprezentowany przez niego ciąg.
    # Np. "%Y-%m-%d" ma 8 znaków, ale data "2024-03-15" ma 10.
    _FORMATY = [
        ("%Y-%m-%dT%H:%M:%SZ", 20),   # "2024-03-15T20:30:00Z"
        ("%Y-%m-%dT%H:%M:%S",  19),   # "2024-03-15T20:30:00"
        ("%Y-%m-%d",           10),   # "2024-03-15"
    ]
    for fmt, dl in _FORMATY:
        try:
            return datetime.strptime(s[:dl], fmt)
        except ValueError:
            continue
    return None
