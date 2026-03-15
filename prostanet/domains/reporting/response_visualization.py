# -*- coding: utf-8 -*-
"""
Módulo de visualización de respuesta terapéutica.

Genera datos estructurados para gráficos clínicos:
  - Waterfall plot: mejor respuesta PSA por línea de tratamiento
  - Spider plot: cambio longitudinal de lesiones individuales
  - Swimmer plot: duración de tratamientos con anotaciones de respuesta
  - PSA trajectory: trayectoria PSA con overlays de tratamiento

Los datos se retornan como dicts listos para Chart.js en el frontend.

Referencia:
  Gillessen S et al. Eur Urol 2022 — Data visualization in PCa trials
  PCWG3 — Scher HI et al. J Clin Oncol 2016
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WaterfallBar:
    """Barra individual del waterfall plot."""
    label: str  # Nombre del esquema
    line_of_therapy: int
    psa_change_pct: float  # % cambio desde baseline
    nadir_psa: float
    baseline_psa: float
    outcome: str  # Ongoing, Progression, Toxicidad
    color: str  # Hex color según categoría de respuesta


@dataclass
class SpiderPoint:
    """Punto de una línea del spider plot (una lesión en un timepoint)."""
    timepoint_label: str  # e.g., "Baseline", "Sem 12", "Sem 24"
    measurement_date: str
    change_from_baseline_pct: float


@dataclass
class SpiderLine:
    """Una línea del spider plot (una lesión a lo largo del tiempo)."""
    lesion_id: str
    location: str
    category: str  # target, non-target
    points: list[SpiderPoint]
    best_response_pct: float
    color: str


@dataclass
class SwimmerLane:
    """Una barra del swimmer plot (un tratamiento)."""
    label: str
    line_of_therapy: int
    start_month: float  # Meses desde diagnóstico
    duration_months: float
    outcome: str
    color: str
    markers: list[dict[str, Any]] = field(default_factory=list)  # PSA50, PD, etc.


@dataclass
class PSATrajectoryPoint:
    """Punto de la trayectoria PSA."""
    date: str
    psa: float
    treatment_label: str | None = None


@dataclass
class ResponseVisualizationBundle:
    """Bundle completo de datos de visualización."""
    waterfall: list[dict[str, Any]]
    spider: dict[str, Any]
    swimmer: list[dict[str, Any]]
    psa_trajectory: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResponseVisualizationService:
    """Genera datos de visualización de respuesta terapéutica."""

    @classmethod
    def build_visualization_bundle(
        cls,
        treatments: list[dict[str, Any]],
        lesions: list[dict[str, Any]] | None = None,
        psa_series: list[dict[str, Any]] | None = None,
        baseline_psa: float | None = None,
        diagnosis_date: str | None = None,
    ) -> ResponseVisualizationBundle:
        """Genera el bundle completo de datos de visualización."""
        return ResponseVisualizationBundle(
            waterfall=cls.build_waterfall(treatments, baseline_psa),
            spider=cls.build_spider(lesions or []),
            swimmer=cls.build_swimmer(treatments, diagnosis_date),
            psa_trajectory=cls.build_psa_trajectory(psa_series or [], treatments),
        )

    @staticmethod
    def build_waterfall(
        treatments: list[dict[str, Any]],
        baseline_psa: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Waterfall plot: mejor respuesta PSA (% cambio) por línea de tratamiento.

        Colores:
          - Verde (#10b981): respuesta profunda (≤-50%)
          - Azul (#3b82f6): respuesta parcial (-50% a -30%)
          - Amarillo (#f59e0b): estabilidad (-30% a 0%)
          - Rojo (#ef4444): progresión (>0%)
        """
        if not baseline_psa or baseline_psa <= 0:
            baseline_psa = _first_valid_float(
                [t.get("baseline_psa") for t in treatments], fallback=10.0
            )

        bars: list[dict[str, Any]] = []
        for tx in treatments:
            nadir = _safe_float(tx.get("nadir_psa"), None)
            if nadir is None:
                continue

            change_pct = ((nadir - baseline_psa) / baseline_psa) * 100 if baseline_psa > 0 else 0

            if change_pct <= -50:
                color = "#10b981"
            elif change_pct <= -30:
                color = "#3b82f6"
            elif change_pct <= 0:
                color = "#f59e0b"
            else:
                color = "#ef4444"

            bars.append(asdict(WaterfallBar(
                label=tx.get("drug_scheme") or f"Línea {tx.get('line_of_therapy', '?')}",
                line_of_therapy=int(tx.get("line_of_therapy") or len(bars) + 1),
                psa_change_pct=round(change_pct, 1),
                nadir_psa=round(nadir, 2),
                baseline_psa=round(baseline_psa, 2),
                outcome=tx.get("outcome") or "Desconocido",
                color=color,
            )))

        # Ordenar por línea de terapia
        bars.sort(key=lambda b: b["line_of_therapy"])
        return bars

    @staticmethod
    def build_spider(lesions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Spider plot: cambio porcentual longitudinal de lesiones individuales.

        Cada lesión es una línea con múltiples timepoints.
        Eje Y: % cambio desde baseline (primera medición).
        Eje X: timepoints cronológicos.

        Input esperado: lista de dicts con:
          - lesion_id, anatomical_location, lesion_category
          - measurements: [{measurement_date, longest_diameter_mm, suvmax, volume_ml}]
        """
        if not lesions:
            return {"lines": [], "timepoints": [], "has_data": False}

        # Paleta de colores para lesiones
        palette = [
            "#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6",
            "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#a855f7",
        ]

        all_timepoints: set[str] = set()
        lines: list[dict[str, Any]] = []

        for idx, lesion in enumerate(lesions):
            measurements = lesion.get("measurements") or []
            if len(measurements) < 2:
                continue

            # Ordenar por fecha
            measurements = sorted(measurements, key=lambda m: m.get("measurement_date") or "")

            baseline_val = _safe_float(measurements[0].get("longest_diameter_mm"), None)
            if not baseline_val or baseline_val <= 0:
                continue

            points: list[dict[str, Any]] = []
            best_response = 0.0

            for i, m in enumerate(measurements):
                val = _safe_float(m.get("longest_diameter_mm"), None)
                if val is None:
                    continue
                date = m.get("measurement_date") or f"T{i}"
                change_pct = ((val - baseline_val) / baseline_val) * 100

                if i == 0:
                    tp_label = "Baseline"
                else:
                    tp_label = date

                all_timepoints.add(date)
                points.append(asdict(SpiderPoint(
                    timepoint_label=tp_label,
                    measurement_date=date,
                    change_from_baseline_pct=round(change_pct, 1),
                )))

                if change_pct < best_response:
                    best_response = change_pct

            color = palette[idx % len(palette)]
            location = lesion.get("anatomical_location") or f"Lesión {idx + 1}"
            category = lesion.get("lesion_category") or "target"

            lines.append(asdict(SpiderLine(
                lesion_id=lesion.get("lesion_id") or str(idx + 1),
                location=location,
                category=category,
                points=points,
                best_response_pct=round(best_response, 1),
                color=color,
            )))

        timepoints_sorted = sorted(all_timepoints)

        return {
            "lines": lines,
            "timepoints": timepoints_sorted,
            "has_data": len(lines) > 0,
            "recist_thresholds": {
                "pr_line": -30,  # RECIST PR threshold
                "pd_line": 20,   # RECIST PD threshold
            },
        }

    @staticmethod
    def build_swimmer(
        treatments: list[dict[str, Any]],
        diagnosis_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Swimmer plot: duración de cada línea terapéutica con marcadores de evento.

        Eje X: meses desde inicio de primera línea (o diagnóstico).
        Cada barra horizontal = un tratamiento con duración y outcome.
        Marcadores: PSA50, PSA90, PD, cambio de línea.
        """
        if not treatments:
            return []

        # Paleta por clase de fármaco
        drug_colors = {
            "ADT": "#3b82f6",
            "ARPI": "#8b5cf6",
            "DOCETAXEL": "#ef4444",
            "CABAZITAXEL": "#f97316",
            "RADIUM": "#14b8a6",
            "LUTETIUM": "#ec4899",
            "PARP": "#6366f1",
            "PEMBROLIZUMAB": "#a855f7",
        }
        default_color = "#64748b"

        # Encontrar fecha de referencia (primera start_date o diagnóstico)
        ref_date = diagnosis_date
        for tx in treatments:
            sd = tx.get("start_date")
            if sd:
                if not ref_date or sd < ref_date:
                    ref_date = sd
        if not ref_date:
            ref_date = "2024-01-01"

        lanes: list[dict[str, Any]] = []
        for tx in treatments:
            start = tx.get("start_date")
            end = tx.get("end_date")
            if not start:
                continue

            start_month = _months_between(ref_date, start)
            duration = _months_between(start, end) if end else _months_between(start, "2026-03-15")

            scheme = tx.get("drug_scheme") or "Desconocido"
            color = default_color
            for key, c in drug_colors.items():
                if key in scheme.upper():
                    color = c
                    break

            # Marcadores de evento
            markers: list[dict[str, Any]] = []
            outcome = tx.get("outcome") or ""

            nadir_psa = _safe_float(tx.get("nadir_psa"), None)
            baseline_psa = _safe_float(tx.get("baseline_psa"), None)
            if nadir_psa is not None and baseline_psa and baseline_psa > 0:
                change = ((nadir_psa - baseline_psa) / baseline_psa) * 100
                nadir_time = _safe_float(tx.get("time_to_nadir_months"), None)
                if change <= -90:
                    markers.append({
                        "type": "PSA90", "symbol": "▼▼",
                        "month": start_month + (nadir_time or duration * 0.3),
                        "color": "#10b981",
                    })
                elif change <= -50:
                    markers.append({
                        "type": "PSA50", "symbol": "▼",
                        "month": start_month + (nadir_time or duration * 0.3),
                        "color": "#3b82f6",
                    })

            if "progres" in outcome.lower():
                markers.append({
                    "type": "PD", "symbol": "✕",
                    "month": start_month + duration,
                    "color": "#ef4444",
                })

            lanes.append(asdict(SwimmerLane(
                label=scheme,
                line_of_therapy=int(tx.get("line_of_therapy") or len(lanes) + 1),
                start_month=round(start_month, 1),
                duration_months=round(max(duration, 0.5), 1),
                outcome=outcome,
                color=color,
                markers=markers,
            )))

        lanes.sort(key=lambda l: l["line_of_therapy"])
        return lanes

    @staticmethod
    def build_psa_trajectory(
        psa_series: list[dict[str, Any]],
        treatments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Trayectoria PSA con overlays de tratamiento.

        Genera data para gráfico de línea con bandas de tratamiento.
        """
        if not psa_series:
            return {"points": [], "treatment_bands": [], "has_data": False}

        points: list[dict[str, Any]] = []
        for entry in sorted(psa_series, key=lambda e: e.get("sample_date") or e.get("date") or ""):
            date = entry.get("sample_date") or entry.get("date") or ""
            psa = _safe_float(entry.get("value") or entry.get("psa"), None)
            if psa is not None and date:
                points.append({"date": date, "psa": round(psa, 2)})

        # Bandas de tratamiento para overlay
        treatment_bands: list[dict[str, Any]] = []
        if treatments:
            band_colors = [
                "rgba(59,130,246,0.15)", "rgba(139,92,246,0.15)",
                "rgba(239,68,68,0.15)", "rgba(20,184,166,0.15)",
                "rgba(249,115,22,0.15)", "rgba(236,72,153,0.15)",
            ]
            for i, tx in enumerate(treatments):
                start = tx.get("start_date")
                if not start:
                    continue
                treatment_bands.append({
                    "label": tx.get("drug_scheme") or f"Línea {i+1}",
                    "start_date": start,
                    "end_date": tx.get("end_date") or "2026-03-15",
                    "color": band_colors[i % len(band_colors)],
                })

        return {
            "points": points,
            "treatment_bands": treatment_bands,
            "has_data": len(points) > 0,
        }


# ── Utilidades privadas ────────────────────────────────────────────────────

def _safe_float(val: Any, default: float | None = 0.0) -> float | None:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _first_valid_float(values: list[Any], fallback: float = 10.0) -> float:
    for v in values:
        r = _safe_float(v, None)
        if r is not None and r > 0:
            return r
    return fallback


def _months_between(date1: str, date2: str) -> float:
    """Calcula meses aproximados entre dos fechas ISO."""
    try:
        from datetime import datetime
        d1 = datetime.strptime(str(date1)[:10], "%Y-%m-%d")
        d2 = datetime.strptime(str(date2)[:10], "%Y-%m-%d")
        delta = d2 - d1
        return delta.days / 30.44
    except (ValueError, TypeError):
        return 0.0
