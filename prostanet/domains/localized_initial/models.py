from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalizedPatient:
    age: int
    psa: float
    clinical_tstage: str
    isup_grade: int
    gleason_primary: int
    gleason_secondary: int
    num_cores_positive: int
    total_cores: int
    pct_cores_positive: float
    max_core_involvement: float
    psad: float
    life_expectancy_years: float
    cribriform_pattern: bool
    intraductal_carcinoma: bool
    metastasis_site: str
    nodal_status: str

