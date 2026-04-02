# FAUBOT Audit Summary

- Modo: `visual`
- Repo: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6`
- Base URL: `http://127.0.0.1:9999`
- Output: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-223625`

## Hallazgos críticos
- Sin hallazgos críticos.

## Hallazgos moderados
- **Visual vertical verification**: La validación no se pudo ejecutar completamente.
  Evidencia: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-223625/artifacts/visual_audit.stdout.log` y `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-223625/artifacts/visual_audit.stderr.log`

## Cobertura ejecutada
- `visual_audit`: FAIL | `no ejecutado`

## Evidencia clínica y técnica
- `Visual vertical verification` -> stdout: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-223625/artifacts/visual_audit.stdout.log`, stderr: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-223625/artifacts/visual_audit.stderr.log`
  Reporte: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-223625/artifacts/vertical_verification_visual.json`

## Plan de corrección propuesto
- Visual vertical verification: Levantar la app con `python3 app.py` en el repo antes de ejecutar el modo visual.

## Pendientes no resueltos
- Levantar la app en `http://127.0.0.1:8080` para completar la auditoría visual.
