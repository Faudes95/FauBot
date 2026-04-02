# FAUBOT Audit Summary

- Modo: `deep`
- Repo: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6`
- Base URL: `http://127.0.0.1:8080`
- Output: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222409`

## Hallazgos críticos
- Sin hallazgos críticos.

## Hallazgos moderados
- Sin hallazgos moderados.

## Cobertura ejecutada
- `vertical_verification`: OK | `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_vertical_verification.py::test_run_vertical_verification_returns_seeded_and_live_coverage -q`

## Evidencia clínica y técnica
- `Vertical verification seeded/live coverage` -> stdout: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222409/artifacts/vertical_verification.stdout.log`, stderr: `/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/faubot/20260327-222409/artifacts/vertical_verification.stderr.log`

## Plan de corrección propuesto
- Mantener `smoke` en cada cambio modular y reservar `deep` o `visual` para verificaciones longitudinales o releases clínicos.

## Pendientes no resueltos
- Ninguno.
