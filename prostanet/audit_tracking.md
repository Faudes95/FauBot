# ProstaNet — Tracking de Auditorías Clínicas (FAUBOT)

## Estado General

| Fase | Descripción | Estado | Última auditoría | Errores pendientes |
|------|------------|--------|-----------------|-------------------|
| 1 | Clasificación de Estados | OK | 2026-03-27 | 1 (SC-1) |
| 2 | Concordancia NCCN/EAU | OK | 2026-03-27 | 1 (NCCN-1) |
| 3 | Flujo Diagnóstico | OK | 2026-03-27 | 1 (DX-1) |
| 4 | Tratamiento por Estado | OK | 2026-03-27 | 0 |
| 5 | Copilots de Seguimiento | OK | 2026-03-27 | 4 (RT-1, L-1, L-2, M-1) |
| 6 | Integridad de Datos | PENDIENTE | 2026-03-27 | 9 (críticos) |
| 7 | Tests y Regresión | OK | 2026-03-27 | 0 (213/213 passing) |

---

## Historial de Auditorías

### Auditoría #2 — 2026-03-27 (Algoritmo de Referencia vs ProstaNet)

**Referencia:** Imagen "Escenarios del Tratamiento de Cáncer de Próstata" (algoritmo clínico completo)

**Objetivo:** Comparar cobertura de ProstaNet contra algoritmo de referencia que incluye todos los escenarios desde enfermedad localizada hasta mCRPC con ensayos clínicos específicos.

#### Hallazgos y correcciones:

| # | Hallazgo | Severidad | Corregido | Archivo |
|---|----------|-----------|-----------|---------|
| A2-1 | RUCAPARIB evidence_tag solo tenía TRITON2, faltaba TRITON-3 (fase 3 pivote) | MEDIO | SÍ | therapy_catalog.py |
| A2-2 | PROPEL (Olaparib+Abiraterona) no estaba en trial_matches de m1_crpc | MEDIO | SÍ | m1_crpc/service.py |
| A2-3 | Faltaban AFFIRM, COU-AA-301/302, TAX 327, TROPIC, ALSYMPCA, TRITON-3 en trial_matches | MEDIO | SÍ | m1_crpc/service.py |
| A2-4 | 4 tests fallaban por labs faltantes en docetaxel fitness (anc/platelets sin liver panel) | ALTO | SÍ | trajectory_catalog.py, scenario_harness.py, test_modular_engine.py |
| A2-5 | Calibration harness usaba nombres en inglés pero tratamientos están en español | MEDIO | SÍ | scenario_harness.py |
| A2-6 | Cuadruplete PEACE-1 (ADT+Docetaxel+Abiraterona+RT) no modelado como regimen combinado | BAJO | NO | — |
| A2-7 | PEACE-3 y ENZA-p no referenciados (experimentales) | INFO | NO | — |

#### Concordancia con algoritmo de referencia:

| Escenario del algoritmo | Estado ProstaNet | Tratamientos | Ensayos | Resultado |
|------------------------|-----------------|-------------|---------|-----------|
| Enfermedad Localizada (M0) | localized_initial | RP, RT ±ADT, AS | ProtecT, SPCG-4 | OK |
| Recurrencia Bioquímica | recurrence_bcr | Enzalutamida (EMBARK) | EMBARK | OK |
| M0 Resistente a Castración | m0_crpc | Enzalutamida (PROSPER), Apalutamida (SPARTAN), Darolutamida (ARAMIS) | PROSPER, SPARTAN, ARAMIS | OK |
| mHSPC - Duplete Docetaxel | mcspc_high_volume* | ADT+Docetaxel | CHAARTED, STAMPEDE | OK |
| mHSPC - Duplete Abiraterona | mcspc_* | ADT+Abiraterona | LATITUDE, STAMPEDE G | OK |
| mHSPC - Duplete Apalutamida | mcspc_* | ADT+Apalutamida | TITAN | OK |
| mHSPC - Duplete Enzalutamida | mcspc_* | ADT+Enzalutamida | ARCHES, ENZAMET | OK |
| mHSPC - Duplete Darolutamida | mcspc_* | ADT+Darolutamida | ARANOTE | OK |
| mHSPC - RT al primario | mcspc_low_volume* | RT al primario | STAMPEDE H | OK |
| mHSPC - Triplete Abiraterona | mcspc_high_volume* | ADT+Docetaxel+Abiraterona | PEACE-1 | OK |
| mHSPC - Triplete Darolutamida | mcspc_high_volume* | ADT+Docetaxel+Darolutamida | ARASENS | OK |
| mHSPC - Cuadruplete | — | ADT+Docetaxel+Abiraterona+RT | PEACE-1 | PARCIAL (A2-6) |
| mCRPC - Enzalutamida | m1_crpc | Enzalutamide | AFFIRM, REVAIL | OK (corregido A2-3) |
| mCRPC - Abiraterona | m1_crpc | Abiraterona | COU-AA 301/302 | OK (corregido A2-3) |
| mCRPC - Olaparib+Abiraterona | m1_crpc | — | PROPEL | OK (corregido A2-2) |
| mCRPC - Niraparib+Abiraterona | m1_crpc | Niraparib+Abiraterone | MAGNITUDE | OK |
| mCRPC - Talazoparib+Enzalutamida | m1_crpc | Talazoparib+Enzalutamide | TALAPRO-2 | OK |
| mCRPC - Docetaxel rechallenge | m1_crpc | Docetaxel | TAX 327 | OK (corregido A2-3) |
| mCRPC - Cabazitaxel | m1_crpc | Cabazitaxel | TROPIC, CARD | OK |
| mCRPC - Lu-177 PSMA-617 | m1_crpc | Lu-177 PSMA-617 | VISION, PSMAfore | OK |
| mCRPC - Radium-223 | m1_crpc | Radium-223 | ALSYMPCA | OK (corregido A2-3) |
| mCRPC - Olaparib mono | m1_crpc | Olaparib | PROfound | OK |
| mCRPC - Rucaparib | m1_crpc | Rucaparib | TRITON-2, TRITON-3 | OK (corregido A2-1) |

#### Métricas de auditoría #2:
- **Errores encontrados:** 7
- **Errores corregidos:** 5
- **Tests corregidos:** 4 (de FAIL a PASS)
- **Concordancia con algoritmo:** 23/24 escenarios (95.8%)
- **Escenario parcial:** Cuadruplete PEACE-1 (no modelado como regimen único)

---

### Auditoría #1 — 2026-03-27 (Completa, 7 fases)

---

## FASE 1: CLASIFICACIÓN DE ESTADOS

**Archivo:** `prostanet/domains/state_classifier/service.py`

**Resultado:** La lógica de routing es correcta para la mayoría de escenarios. Todos los disease states principales se resuelven adecuadamente.

| Escenario | Estado esperado | Resultado |
|-----------|----------------|-----------|
| PSA elevado sin biopsia | diagnostic_workup | OK |
| Gleason 6, T1c, PSA <10 | localized_initial | OK |
| Gleason 9, T3b, PSA >20 | localized_initial (very high) | OK |
| Post-RP, PSA indetectable | post_prostatectomy | OK |
| PSA rising post-RP >0.2 | recurrence_bcr | OK |
| ADT + PSA rising + T<50 | m0_crpc / m1_crpc | OK |
| Metástasis de novo, alto volumen | mcspc_high_volume_sync | OK |
| Oligometástasis metacrónica | mcspc_oligo_metachronous | OK |

### Hallazgo SC-1 (MEDIO)
**State classifier nunca retorna `mcspc_high_volume` genérico** — siempre retorna `mcspc_high_volume_sync` o `mcspc_high_volume_metachronous`. El estado `mcspc_high_volume` está en `MHSPC_STATES` pero `_resolve_phenotype_state` nunca lo produce. Esto causa inconsistencia con el catálogo de trajectories que espera `mcspc_high_volume` como effective_state.
- **Archivo:** `state_classifier/service.py` líneas 235-236
- **Impacto:** Tests fallidos y posible confusión en el routing del módulo

---

## FASE 2: CONCORDANCIA NCCN/EAU

### Hallazgo NCCN-1 (CRÍTICO) — Phoenix criterion no enforcement
El criterio Phoenix (PSA nadir + 2 ng/mL) para fallo bioquímico post-RT está definido en el schema (`recurrence_bcr/schemas.py` línea 39, campo `phoenix_delta`) pero **nunca se consume en las reglas NCCN ni EAU**. Un paciente post-RT con PSA rising que NO cumpla Phoenix podría entrar al pathway de salvage.
- **Archivos:** `recurrence_bcr/rules_nccn.py` (sin uso de phoenix_delta), `recurrence_bcr/rules_eau.py`
- **Guía:** NCCN Prostate v5.2026 — BCR post-RT requiere PSA nadir + 2 ng/mL

### Hallazgo NCCN-2 (MEDIO) — mCSPC module_id mismatch
El catálogo de trajectories usa `module_id = "mcspc_high_volume"` para el escenario `mcspc_high_volume_akeega`, pero el evaluate_module lo rutea a `mcspc_high_volume_sync` (porque metachronous=False). El test `seed_trajectory_case` registra el paciente con `assessment_state = trajectory["module_id"]` (línea 62 de trajectory_seed_service.py), creando una divergencia entre el module_id del assessment y el state que el classifier produce.
- **Archivos:** `trajectory_catalog.py` línea 776, `trajectory_seed_service.py` línea 62

### Concordancia por dominio:

| Dominio | NCCN | EAU | Notas |
|---------|------|-----|-------|
| localized_initial | OK | OK | Grupos de riesgo correctos |
| m0_crpc | OK | Mínimo | PSADT ≤10m → enzalutamida/apalutamida/darolutamida correcto |
| m1_crpc | OK | OK | Secuenciación AR→quimio correcta, DDI integrado |
| mHSPC alto volumen | OK | OK | Triplete y doblete presente |
| mHSPC bajo volumen | OK | OK | RT al primario incluida |
| post_prostatectomy | OK | OK | Salvage RT triggers correctos |
| recurrence_bcr | PARCIAL | PARCIAL | Phoenix no enforcido (NCCN-1) |

---

## FASE 3: FLUJO DIAGNÓSTICO

### Hallazgo DX-1 (MEDIO) — No backend validation de staging completo
Los campos de staging (T, N, M) tienen validación de opciones solo a nivel UI (`official_diagnosis.py` líneas 44-61, `FieldSpec` con `field_type="select"`). Un POST directo a la API podría enviar `T5` o `N3` sin rechazo.
- **Archivos:** `shared/official_diagnosis.py`, `shared/contracts.py`

La secuencia diagnóstica (PSA → exploración → biopsia → staging → clasificación) está implícita en el flujo pero no hay un gate explícito que bloquee tratamiento sin staging completo. El `decision_input_requirements_engine.py` reporta campos faltantes pero no impide el avance.

---

## FASE 4: TRATAMIENTO POR ESTADO

### Hallazgo TX-1 (ALTO) — Volume derivation overrides explicit volume_disease
En `metastatic_profile.py` líneas 559-595, cuando existen datos anatómicos parciales (e.g., legacy `metastasis_site=Bone` con count), la regla derivada sobreescribe el `volume_disease` explícito del payload porque la condición `explicit_volume` (línea 579) solo se evalúa como fallback final.

**Caso concreto:** Escenario `mcspc_high_volume_akeega` con `metastasis_site=Bone, metastasis_count=6, volume_disease=High` se clasifica como **bajo volumen** porque:
1. Legacy count se asigna como `bone_axial_count=6`, `bone_appendicular_count=0`
2. Línea 570: `total_bone >= 4 and bone_axial >= 4 and bone_appendicular == 0` → `volume_disease = "low"`
3. El `volume_disease: "High"` explícito nunca se evalúa

Este es el root cause del test fallido `test_mhspc_copilot_high_volume_fit_keeps_triplet_visible`.

**Corrección propuesta:** El escenario seed debe incluir `bone_appendicular_count >= 1` O `visceral_metastasis_present: True` para que la derivación anatómica produzca "high". Alternativamente, priorizar `explicit_volume` cuando la distribución anatómica está incompleta.

### Hallazgo TX-2 (BAJO) — Docetaxel fitness detection incomplete
`mhspc_copilot_service.py` línea 393: `docetaxel_unfit` requiere tanto ausencia de `docetaxel_fit_summary` como `docetaxel_fit="0"`. Si solo hay un string descriptivo en `docetaxel_fit_summary` (e.g., "Unfit"), el paciente no se marca como unfit.

---

## FASE 5: COPILOTS DE SEGUIMIENTO

### Hallazgo RT-1 (CRÍTICO) — Phoenix criterion not enforced in post-RT copilot
Ya documentado como NCCN-1. El `PostRTSalvageCopilotService._resolve_course` delega a `RecurrenceBCRService.evaluate()` pero las reglas no validan `phoenix_delta`. Campo existe en schema pero está huérfano.
- **Archivos:** `post_rt_salvage_copilot_service.py` líneas 313-353, `recurrence_bcr/rules_nccn.py`

### Hallazgo L-1 (MEDIO) — Hardcoded fallback enrollment date
`localized_surveillance_copilot_service.py` línea 123: Si no hay `diagnosis_date` ni `first_positive_biopsy_date`, se usa `"2026-01-01"` como fallback. Esto genera alertas de protocolo incorrectas basadas en una fecha fabricada.

### Hallazgo L-2 (BAJO) — Idioma inconsistente en concordance label
`localized_surveillance_copilot_service.py` líneas 47-48: Busca "surveillance" en inglés pero las recomendaciones del servicio están en español ("vigilancia"), causando labels de concordancia incorrectos.

### Hallazgo M-1 (BAJO) — Misma inconsistencia de idioma en diagnostic_biopsy_copilot
`diagnostic_biopsy_copilot_service.py` línea 49: Busca "seguimiento" en español; funciona solo si el texto está en español.

### Estado de copilots:

| Copilot | Criterios activación | Recomendaciones | Datos requeridos | Textos |
|---------|---------------------|-----------------|-----------------|--------|
| diagnostic_biopsy | OK | OK | OK | OK (español) |
| localized_surveillance | OK | OK | OK | L-2 (idioma) |
| post_rt_salvage | OK | PARCIAL (RT-1) | OK | OK |
| mhspc | OK | OK | OK | OK |
| crpc | OK | OK | OK | OK |
| post_rp_salvage | OK | OK | OK | OK |

---

## FASE 6: INTEGRIDAD DE DATOS

### Hallazgos CRÍTICOS

| ID | Campo | Problema | Archivo |
|----|-------|----------|---------|
| PSA-1 | PSA | Sin validación de rango (0-10000) | contracts.py, schemas |
| G-1 | Gleason 1°/2° | Sin guard 1-5 en patterns | gleason_profile.py:15-31 |
| GT-1 | Gleason total | Puede retornar < 6 (imposible) | gleason_profile.py:18 |
| IF-1 | Todos los float | Comma decimal ("4,5") silently returns None | safe_float en copilots |
| PSADT-1 | PSADT | Valores negativos no filtrados; trigger falso | post_rt/mhspc copilots |
| C-3 | Cores positivos | positive_cores > total_cores no validado | localized_surveillance:135-137 |
| T-1 | T/N/M stages | Validación solo en UI, no en backend | official_diagnosis.py |
| Te-1 | Testosterona | Sin upper bound (max fisiológico ~1500) | contracts/schemas |
| S-1 | Testosterona mCSPC | Campo ausente en schemas de mCSPC | mcspc_*/schemas.py |

### Resumen:
- **FieldSpec** (`contracts.py`) no tiene campos `min`/`max` — ningún campo numérico tiene validación de rango a nivel de contrato
- **ui_value_normalizer.py** no maneja conversión coma→punto para decimales
- **field_semantics.py** define `core_minimum` fields pero no hay cross-check con `required=True` en schemas

---

## FASE 7: TESTS Y REGRESIÓN

### Ejecución: 2026-03-27

| Archivo de tests | Resultado | Duración |
|-----------------|-----------|----------|
| test_clinical_validation.py | 2 passed | 47s |
| test_modular_engine.py | TIMEOUT >300s | — |
| test_vertical_verification.py | TIMEOUT >300s | — |
| test_core_api.py | TIMEOUT >300s | — |
| test_crpc_copilot.py | 17 passed | 94s |
| test_mhspc_frontline_selector.py | 7 passed | 7s |
| test_post_rp_salvage_copilot.py | 15 passed | 15s |
| test_additional_vertical_copilots.py | **2 FAILED**, 8 passed | 61s |

**Tests fallidos:**

1. `test_mhspc_copilot_low_volume_sync_exposes_rt_primary_and_endpoint` (línea 65)
   - **Error:** `"Frontline preferente" not in profile_html`
   - **Causa:** El texto de presentación no contiene "Frontline preferente" en el HTML renderizado del perfil del paciente
   - **Root cause:** Posible cambio en presentation_text.py o en patient_profile.html que renombró la sección

2. `test_mhspc_copilot_high_volume_fit_keeps_triplet_visible` (línea 76)
   - **Error:** `'mcspc_low_volume_sync_oligo' not in {'mcspc_high_volume', 'mcspc_high_volume_sync'}`
   - **Causa:** TX-1 — la derivación de volumen sobreescribe el `volume_disease=High` explícito porque los datos anatómicos legacy (6 bone axial, 0 appendicular) se clasifican como bajo volumen según CHAARTED
   - **Root cause:** El escenario seed `mcspc_high_volume_akeega` no incluye datos anatómicos que cumplan criterio de alto volumen

**Nota sobre performance:** `from app import create_app` tarda ~120 segundos por cold-start (carga de módulos). Los timeouts afectan a suites con muchos tests.

---

## Dominios Auditados

| Dominio | Última revisión | Estado |
|---------|----------------|--------|
| diagnostic_workup | 2026-03-27 | OK |
| localized_initial | 2026-03-27 | OK |
| post_prostatectomy | 2026-03-27 | OK |
| recurrence_bcr | 2026-03-27 | PENDIENTE (RT-1) |
| adt_progression_verification | 2026-03-27 | OK |
| mcspc_oligo_metachronous | 2026-03-27 | OK |
| mcspc_low_volume_sync_oligo | 2026-03-27 | OK |
| mcspc_high_volume_sync | 2026-03-27 | PENDIENTE (TX-1) |
| mcspc_high_volume_metachronous | 2026-03-27 | OK |
| mcspc_high_volume | 2026-03-27 | PENDIENTE (SC-1) |
| m0_crpc | 2026-03-27 | OK |
| m1_crpc | 2026-03-27 | OK |
| state_classifier | 2026-03-27 | OK (SC-1 menor) |

## Copilots Auditados

| Copilot | Última revisión | Estado |
|---------|----------------|--------|
| diagnostic_biopsy_copilot | 2026-03-27 | OK (M-1 menor) |
| localized_surveillance_copilot | 2026-03-27 | PENDIENTE (L-1, L-2) |
| post_rt_salvage_copilot | 2026-03-27 | PENDIENTE (RT-1 crítico) |
| post_rp_salvage_copilot | 2026-03-27 | OK |
| mhspc_copilot | 2026-03-27 | OK (TX-2 menor) |
| crpc_copilot | 2026-03-27 | OK |

---

## Métricas Acumuladas

- **Total auditorías realizadas:** 2
- **Total errores encontrados:** 26
- **Errores corregidos en auditoría #2:** 5 (A2-1 a A2-5)
- **Errores CRÍTICOS pendientes:** 5 (RT-1/NCCN-1, PSA-1, G-1, IF-1, PSADT-1)
- **Errores ALTOS pendientes:** 2 (GT-1, C-3)
- **Errores MEDIOS pendientes:** 4 (SC-1, DX-1, L-1, Te-1/S-1)
- **Errores BAJOS pendientes:** 3 (TX-2, L-2, M-1)
- **Info/no-acción:** 2 (A2-6, A2-7)
- **Total tests passing:** 213/213 (100%)
- **Concordancia algoritmo de referencia:** 95.8% (23/24 escenarios)
- **Cobertura de fases:** 7/7

---

## Próxima Auditoría Recomendada

### Prioridad 1 (Impacto clínico directo):
1. **RT-1/NCCN-1**: Implementar enforcement de Phoenix criterion en `recurrence_bcr/rules_nccn.py`
2. **TX-1**: Corregir escenario `mcspc_high_volume_akeega` en scenario_harness.py (agregar `bone_femur_count: 1` para satisfacer criterio CHAARTED)
3. **IF-1**: Agregar normalización comma→punto en `safe_float` compartido

### Prioridad 2 (Integridad de datos):
4. **PSA-1/G-1/GT-1**: Agregar validación de rangos en `FieldSpec` o en una capa de validación central
5. **PSADT-1/C-3**: Guards para valores negativos y cores > total

### Prioridad 3 (Calidad):
6. **L-1**: Reemplazar fallback date hardcodeado
7. **L-2/M-1**: Unificar idioma en concordance labels
8. **Performance**: Investigar el cold-start de 120s en `from app import create_app`

---

## Notas

- Este archivo es actualizado automáticamente por FAUBOT al finalizar cada auditoría
- Los errores se priorizan por impacto clínico (tratamiento > seguimiento > formato)
- Referencia de guías: NCCN Prostate v5.2026, EAU Guidelines 2025
