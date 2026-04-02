# FAUBOT Audit Summary

- Modo: `smoke`
- Repo: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6`
- Base URL: `http://127.0.0.1:8080`
- Output: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334`

## Hallazgos críticos
- Sin hallazgos críticos.

## Hallazgos moderados
- Sin hallazgos moderados.

## Cobertura ejecutada
- `draft_registration_flow`: OK | `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_modular_engine.py::test_clinical_assessment_draft_and_patient_registration_flow -q`
- `stage_specific_missing_inputs`: OK | `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_core_api.py::test_clinical_assessment_context_requests_only_missing_score_inputs -q`
- `phase_one_schedule`: OK | `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_core_api.py::test_schedule_exposes_master_followup_plan_for_phase_one_scenarios -q`

## Evidencia clínica y técnica
- `Draft -> intake -> register flow` -> stdout: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334/artifacts/draft_registration_flow.stdout.log`, stderr: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334/artifacts/draft_registration_flow.stderr.log`
- `Stage-specific missing inputs` -> stdout: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334/artifacts/stage_specific_missing_inputs.stdout.log`, stderr: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334/artifacts/stage_specific_missing_inputs.stderr.log`
- `Master follow-up plan for phase one scenarios` -> stdout: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334/artifacts/phase_one_schedule.stdout.log`, stderr: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222334/artifacts/phase_one_schedule.stderr.log`

## Plan de corrección propuesto
- Mantener `smoke` en cada cambio modular y reservar `deep` o `visual` para verificaciones longitudinales o releases clínicos.

## Pendientes no resueltos
- Ninguno.
