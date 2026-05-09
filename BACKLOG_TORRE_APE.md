# Backlog post-sprint — Torre de Control APE

Generado tras el sprint de "Cierre de brechas clínicas + Captura APE por estadio + Torre dinámica" (2026-05-09). Este documento agrupa lo que **no entró** al sprint y debe priorizarse en próximas iteraciones.

---

## 🔴 Bloqueadores FDA pre-market (Class II SaMD)

Identificados por `/fda-medtech-compliance-auditor`. **Críticos** antes de pasar producción a entorno regulado.

### TASK-FDA-001 — Autenticación + RBAC
- **Citación**: 21 CFR Part 11 §11.10(d), §11.300
- **Estado actual**: cualquier cliente envía `X-Actor` libre (`api.py:3152-3153`).
- **Acción**: integrar Flask-Login o JWT; rechazar requests sin sesión válida; persistir `user_id` numérico en lugar de string libre; aplicar RBAC para roles clínicos (médico, enfermería, lectura).
- **Estimación**: 5–8 días.

### TASK-FDA-002 — Firma electrónica vinculante
- **Citación**: §11.50, §11.70, §11.200
- **Acción**: registrar `signature_meaning` ("Acepto responsabilidad clínica del cambio") + dual-credential o WebAuthn token. Persistir en `psa_audit_log` o tabla relacionada.
- **Estimación**: 5 días.

### TASK-FDA-003 — Hash-chain de inmutabilidad criptográfica
- **Citación**: §11.10(c), §11.10(e) (refuerzo del trigger ya aplicado)
- **Acción**: añadir col `prev_hash` y `row_hash` (SHA-256 de la fila + hash anterior) en `psa_audit_log`. Verificación periódica de cadena. Considerar export append-only a almacén externo (S3 versioned con object lock).
- **Estimación**: 3 días.

### TASK-FDA-004 — TLS forzado + rate-limit
- **Citación**: §11.30
- **Acción**: gunicorn + reverse proxy (nginx/caddy) con TLS 1.2+, HSTS, rate-limit por IP, `bind 127.0.0.1` en backend.
- **Estimación**: 1–2 días (config) + 1 día test.

### TASK-FDA-005 — Versionado de modelo en snapshot
- **Citación**: §11.10(k)(2)
- **Acción**: añadir cols `model_hash`, `code_version` en `psa_kinetics_snapshot`. Capturar `git rev-parse HEAD` y SHA-256 de `model_output/*.pt` al arrancar app.
- **Estimación**: 1 día.

### TASK-FDA-006 — Design History File
- **Citación**: 21 CFR 820.30(j), IEC 62304 §5
- **Acción**: crear `docs/dhf/`:
  - SRS con Intended Use, User Needs, requirement IDs.
  - Software Design Description.
  - Trace matrix requirement → code → test.
  - Software Validation Plan.
- **Estimación**: 2 semanas, requiere participación clínica.

### TASK-FDA-007 — Risk file (ISO 14971)
- **Citación**: ISO 14971, 21 CFR 820.30(g)
- **Acción**: FMEA por detector clínico (PCWG3 falso negativo, Phoenix falso positivo, etc.). Probabilidad × Severidad × Detectabilidad. Mitigaciones: dual-confirmación, alertas no autónomas.
- **Estimación**: 3 días.

### TASK-FDA-008 — CAPA formal del bug `psadt`/`psadt_months`
- **Citación**: 21 CFR 820.100
- **Acción**: documentar root-cause = falta de contract test entre `clinical_scores` y `psa_line_monitor`. Effectiveness check = añadir test que rompa si el contrato cambia. (Pruebas en `tests/test_psa_torre_control.py` ya cubren parcialmente.)
- **Estimación**: 0.5 día.

---

## 🟡 Bugs pre-existentes detectados durante este sprint

### TASK-REG-001 — `Error saving PRO assessment: 37 values for 38 columns`
- **Origen**: `tracking_db.py:11158` (no tocado en este sprint).
- **Tests fallando** (verificado con `git stash`):
  1. `test_modular_engine::test_clinical_assessment_draft_and_patient_registration_flow`
  2. `test_modular_engine::test_rich_longitudinal_tables_persist_from_integrated_registration`
  3. `test_modular_engine::test_m1_crpc_structured_taxane_bundle_overrides_legacy_docetaxel_boolean`
  4. `test_modular_engine::test_clinical_calibration_harness_reaches_full_concordance`
  5. `test_additional_vertical_copilots::test_mhspc_copilot_high_volume_fit_keeps_triplet_visible`
  6. `test_additional_vertical_copilots::test_post_rt_copilot_keeps_local_salvage_visible_and_endpoint_resolves`
  7. `test_vertical_verification::test_run_vertical_verification_returns_seeded_and_live_coverage`
  8. `test_vertical_verification::test_vertical_audit_endpoint_returns_report`
- **Acción**: alinear el INSERT en `_save_pro_assessment` con el schema de `patient_pros` (37 ↔ 38 columnas). Probablemente falta una columna en INSERT o sobra una en SET.
- **Estimación**: 0.5 día.

---

## 🟠 Refinamientos UX que quedaron fuera del sprint

### TASK-UX-001 — Bandas de estadio overlay sobre `psaControlChart`
- **Estado actual**: el chart Chart.js sigue mostrando bandas por línea terapéutica. El toggle dual-view ya está implementado y dispara fetch a `/api/patients/<id>/psa_torre?view=stage|line|both`, pero el handler que reescribe el dataset Chart.js está pendiente.
- **Path**: `templates/patient_profile.html:5314-6047` (scripts inline del chart).
- **Acción**: agregar listener `psa-torre-view-changed`; si `view==='stage'`, reescribir `chart.data.datasets` con `stage_segments` y `transitions` como annotations verticales.
- **Estimación**: 2 días.

### TASK-UX-002 — Refactor `patient_profile.html` (7492 líneas)
- **Acción**: extraer a `templates/components/torre_ape.html` + `static/js/profile_charts.js`. Bootstrap JSON `<script id="profile-bootstrap">` para desacoplar JS externos del template Jinja.
- **Riesgo**: alto. Requiere tests visuales (Playwright) antes/después.
- **Estimación**: 4 días.

### TASK-UX-003 — Captura inline de `metastasis_count`/`lesion_count` en wizard
- **Estado actual**: campos añadidos a `FOLLOWUP_NUMERIC_FIELDS` (backend) y schema; UI de visita longitudinal aún no los expone.
- **Path**: `clinical_wizard.html:318+` (registrationPhase).
- **Acción**: agregar campos al schema fragments y formulario.
- **Estimación**: 1 día.

### TASK-UX-004 — Auto-CHAARTED/LATITUDE chips en intake/calculator
- **Estado**: `auto_classify.js` listo; pendiente añadir el contenedor `<div data-auto-classify>` con campos y chips `data-auto-chip="chaarted"`/`data-auto-chip="latitude"` en `calculator_v2.html` y `patient_intake.html`.
- **Estimación**: 0.5 día.

### TASK-UX-005 — Persistir histology_variant desde UI
- **Estado actual**: col `clinical_baseline.histology_variant` agregada; sin selector visible en wizard.
- **Acción**: agregar `<select name="histology_variant">` con tooltip de impacto clínico (intraductal/neuroendocrine cambian conducta).
- **Estimación**: 0.5 día.

---

## 🔵 Gaps clínicos identificados que no se cerraron

### TASK-CLIN-001 — Unificar dual-source de oligoprogresión
- **Estado**: existen dos fuentes: `oligomet_engine._detect_oligoprogression` (lesiones) y `reconciled_state._derive_progression_pattern` (PSA + lesion counts). Documentar prioridad.
- **Acción**: definir `oligomet_engine` como primary source; `reconciled_state` como fallback informado por counts. Test de consistencia.
- **Estimación**: 1 día.

### TASK-CLIN-002 — Variantes histológicas que cambian conducta
- **Estado actual**: enum `HISTOLOGY_VARIANTS` declarado pero sin reglas que cambien el algoritmo. Si paciente es neuroendocrino, debería ofrecerse régimen platino-basado.
- **Acción**: ramificar en `service.py` y `crpc_copilot_service.py` para histology=neuroendocrine/small_cell.
- **Estimación**: 2 días + revisión clínica.

### TASK-CLIN-003 — Validación PCWG3 en cohorte real
- **Estado actual**: tests sintéticos. Para SaMD se requiere validación contra cohorte clínica real (sensibilidad/especificidad).
- **Acción**: definir dataset de validación bloqueado, computar métricas.
- **Estimación**: 1 sprint completo + colaboración clínica.

---

## ✅ Lo que entró y está operativo

- 6 detectores clínicos (PCWG3, Phoenix, ASTRO, bounce, CHAARTED, LATITUDE).
- 7 endpoints REST (POST/PUT/DELETE/GET psa_history + snapshot + audit_log + torre dual-view).
- Schema migrado (idempotente, sin pérdida).
- Servicio `psa_history_service` con CRUD + audit + recompute síncrono.
- Triggers SQLite append-only en `psa_audit_log` (Quick-win FDA §11.10(e)).
- 26 tests pasando (incluido test de inmutabilidad).
- Componente reutilizable en `patient_profile.html`.
- Toggle dual-view, polling 30s, JS CRUD, estilos completos.
- Estado `oligoprogression_post_systemic` integrado en `STATE_SCOPE_MAP` y `_survival_fragment`.
- Bug fix `psadt_months` en `psa_line_monitor`.
- Soft-delete respetado por todos los readers (`_extract_psa_points`, `_derive_psa_series`, `list_psa_points`).

---

**Próxima auditoría recomendada**: Tras cerrar TASK-REG-001 + TASK-FDA-001 (auth) + TASK-UX-003 (wizard captures), volver a correr `/faubot` 7 fases.
