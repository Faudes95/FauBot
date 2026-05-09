/* auto_classify.js
 *
 * Pintado client-side de chips informativos de auto-clasificación clínica:
 *   - CHAARTED volume (Sweeney 2015): high vs low según mets óseas + apendicular + viscerales.
 *   - LATITUDE risk (Fizazi 2017): high_risk si ≥2 de {Gleason ≥8, ≥3 mets óseas, viscerales}.
 *
 * Las funciones equivalentes en backend (clinical_scores.auto_classify_*) son
 * la **fuente de verdad** y se persisten al guardar. Los chips client-side son
 * SOLO un hint para el médico durante la captura; no sustituyen la
 * persistencia ni la decisión final del backend.
 *
 * Contrato: el contenedor con `data-auto-classify` debe tener inputs/selects
 * con los siguientes `name` (o `id`):
 *   - bone_metastases_count (number)
 *   - bone_appendicular (checkbox / select 0|1)
 *   - visceral_mets (checkbox / select 0|1)
 *   - visceral_mets_count (number)
 *   - gleason_score (number)
 *
 * Y los chips de salida con:
 *   - data-auto-chip="chaarted"
 *   - data-auto-chip="latitude"
 */
(function (global) {
  'use strict';

  function readNum(form, names) {
    for (const n of names) {
      const el = form.querySelector(`[name="${n}"], #${n}`);
      if (el) {
        const v = parseFloat(el.value);
        if (!isNaN(v)) return v;
      }
    }
    return null;
  }

  function readBool(form, names) {
    for (const n of names) {
      const el = form.querySelector(`[name="${n}"], #${n}`);
      if (!el) continue;
      if (el.type === 'checkbox') return el.checked;
      const v = String(el.value).trim().toLowerCase();
      if (['1', 'true', 'si', 'sí', 'yes'].includes(v)) return true;
      if (['0', 'false', 'no', ''].includes(v)) return false;
    }
    return false;
  }

  /**
   * CHAARTED volume — high si visceral o ≥4 óseas con apendicular.
   * Mantener sincronizado con clinical_scores.auto_classify_chaarted_volume.
   */
  function classifyChaarted(form) {
    const boneCount = readNum(form, ['bone_metastases_count', 'bone_count']) || 0;
    const visceral = readBool(form, ['visceral_mets', 'visceral_metastases']);
    const visceralCount = readNum(form, ['visceral_mets_count']) || 0;
    const appendicular = readBool(form, ['bone_appendicular', 'bone_outside_axial']);

    if (visceral || visceralCount >= 1) return { volume: 'high', reason: 'Metástasis visceral presente' };
    if (boneCount >= 4 && appendicular) return { volume: 'high', reason: '≥4 óseas con apendicular (Sweeney 2015)' };
    return { volume: 'low', reason: 'Sin criterios de alto volumen' };
  }

  /**
   * LATITUDE risk — high si ≥2 de {Gleason ≥8, ≥3 óseas, visceral}.
   * Mantener sincronizado con clinical_scores.auto_classify_latitude.
   */
  function classifyLatitude(form) {
    const gleason = readNum(form, ['gleason_score']) || 0;
    const boneCount = readNum(form, ['bone_metastases_count', 'bone_count']) || 0;
    const visceral = readBool(form, ['visceral_mets', 'visceral_metastases']);
    const visceralCount = readNum(form, ['visceral_mets_count']) || 0;

    const criteria = [
      { name: 'Gleason ≥8', met: gleason >= 8 },
      { name: '≥3 mets óseas', met: boneCount >= 3 },
      { name: 'Metástasis visceral', met: visceral || visceralCount >= 1 },
    ];
    const metCount = criteria.filter((c) => c.met).length;
    return {
      risk: metCount >= 2 ? 'high_risk' : 'low_risk',
      met_count: metCount,
      criteria,
    };
  }

  function paintChaartedChip(chip, result) {
    if (!chip) return;
    const cls = result.volume === 'high' ? 'stage-chip-mhspc' : 'stage-chip-localized';
    chip.className = `stage-chip ${cls}`;
    chip.textContent = `CHAARTED · ${result.volume === 'high' ? 'Alto vol.' : 'Bajo vol.'}`;
    chip.title = result.reason;
  }

  function paintLatitudeChip(chip, result) {
    if (!chip) return;
    const cls = result.risk === 'high_risk' ? 'stage-chip-crpc' : 'stage-chip-localized';
    chip.className = `stage-chip ${cls}`;
    chip.textContent = `LATITUDE · ${result.risk === 'high_risk' ? 'Alto riesgo' : 'Bajo riesgo'} (${result.met_count}/3)`;
    chip.title = result.criteria.map((c) => `${c.met ? '✓' : '✗'} ${c.name}`).join(' · ');
  }

  function refresh(form) {
    const ch = form.querySelector('[data-auto-chip="chaarted"]');
    const lt = form.querySelector('[data-auto-chip="latitude"]');
    if (ch) paintChaartedChip(ch, classifyChaarted(form));
    if (lt) paintLatitudeChip(lt, classifyLatitude(form));
  }

  function init() {
    document.querySelectorAll('[data-auto-classify]').forEach((form) => {
      if (form.dataset.autoClassifyBound) return;
      form.dataset.autoClassifyBound = '1';
      form.addEventListener('input', () => refresh(form));
      form.addEventListener('change', () => refresh(form));
      refresh(form);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  global.autoClassify = { init, classifyChaarted, classifyLatitude, refresh };
})(window);
