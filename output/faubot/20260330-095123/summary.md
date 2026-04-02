# FAUBOT Audit Summary

- Modo: `visual`
- Repo: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6`
- Base URL: `http://127.0.0.1:8080`
- Output: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260330-095123`

## Hallazgos críticos
- Sin hallazgos críticos.

## Hallazgos moderados
- Sin hallazgos moderados.

## Cobertura ejecutada
- `visual_audit`: OK | `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/run_vertical_verification.py --base-url http://127.0.0.1:8080 --visual-mode playwright_real --live-limit-per-vertical 1 --output /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260330-095123/artifacts/vertical_verification_visual.json`

## Evidencia clínica y técnica
- `Visual vertical verification` -> stdout: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260330-095123/artifacts/visual_audit.stdout.log`, stderr: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260330-095123/artifacts/visual_audit.stderr.log`
  Reporte: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260330-095123/artifacts/vertical_verification_visual.json`

## Plan de corrección propuesto
- Mantener `smoke` en cada cambio modular y reservar `deep` o `visual` para verificaciones longitudinales o releases clínicos.

## Pendientes no resueltos
- Ninguno.
