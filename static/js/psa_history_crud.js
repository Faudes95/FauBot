/* psa_history_crud.js
 *
 * Hidrata el componente templates/components/psa_history_table.html.
 * Maneja CRUD inline + audit log + export CSV.
 *
 * Cada operación contra el backend dispara automáticamente un evento
 * `psa-snapshot-updated` para que la torre de control (psa_torre_polling.js)
 * refresque sin esperar al siguiente tick de polling.
 *
 * No usa frameworks: sólo fetch + DOM + dialog. Mantener compatibilidad con
 * navegadores modernos (Chrome 95+/Firefox 98+/Safari 15.4+).
 */
(function (global) {
  'use strict';

  const STAGE_DISPLAY = {
    diagnostic_workup: { label: 'Diagnóstico', cls: 'stage-chip-localized' },
    post_negative_biopsy_followup: { label: 'Vig. post-biopsia', cls: 'stage-chip-localized' },
    post_prostatectomy: { label: 'Post-RP', cls: 'stage-chip-localized' },
    recurrence_bcr: { label: 'BCR', cls: 'stage-chip-bcr' },
    post_radiotherapy_or_local_salvage: { label: 'Post-RT', cls: 'stage-chip-bcr' },
    mcspc_oligo_metachronous: { label: 'mHSPC oligo metacr.', cls: 'stage-chip-mhspc' },
    mcspc_low_volume_sync_oligo: { label: 'mHSPC bajo vol.', cls: 'stage-chip-mhspc' },
    mcspc_high_volume_sync: { label: 'mHSPC alto vol. sinc.', cls: 'stage-chip-mhspc' },
    mcspc_high_volume_metachronous: { label: 'mHSPC alto vol. metacr.', cls: 'stage-chip-mhspc' },
    adt_progression_verification: { label: 'ADT progr. verif.', cls: 'stage-chip-crpc' },
    m0_crpc: { label: 'm0 CRPC', cls: 'stage-chip-crpc' },
    m1_crpc: { label: 'm1 CRPC', cls: 'stage-chip-crpc' },
    oligoprogression_post_systemic: { label: 'Oligoprogresión', cls: 'stage-chip-oligoprogression' },
  };

  const SOURCE_LABEL = {
    laboratory: 'Lab',
    self_report: 'Autoreporte',
    historical_import: 'Histórico',
    intake: 'Intake',
    followup: 'Seguimiento',
  };

  function renderStageChip(state) {
    const meta = STAGE_DISPLAY[state] || { label: state || '—', cls: '' };
    return `<span class="stage-chip ${meta.cls}">${escapeHtml(meta.label)}</span>`;
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtDate(d) {
    if (!d) return '—';
    return String(d).slice(0, 10);
  }

  /**
   * Construye una fila <tr> a partir de un punto del backend.
   */
  function buildRow(point) {
    const tr = document.createElement('tr');
    tr.dataset.pointId = point.id;
    tr.className = 'psa-history-row';
    tr.innerHTML = `
      <td class="py-2 px-2">${escapeHtml(fmtDate(point.sample_date))}</td>
      <td class="py-2 px-2 font-mono">${Number(point.value).toFixed(2)}</td>
      <td class="py-2 px-2">${renderStageChip(point.clinical_state_at_measurement)}</td>
      <td class="py-2 px-2">${escapeHtml(point.line_label || '—')}</td>
      <td class="py-2 px-2"><span class="origin-chip">${escapeHtml(SOURCE_LABEL[point.source] || point.source || 'Lab')}</span></td>
      <td class="py-2 px-2 text-slate-400">${escapeHtml(point.reason || '')}</td>
      <td class="py-2 px-2 text-right whitespace-nowrap">
        <button type="button" class="pn-btn pn-btn-icon" data-action="edit-row" title="Editar">✏️</button>
        <button type="button" class="pn-btn pn-btn-icon" data-action="delete-row" title="Eliminar">🗑️</button>
      </td>
    `;
    return tr;
  }

  /**
   * PsaHistoryCrud — clase principal que asocia un container a un patient_id.
   */
  class PsaHistoryCrud {
    constructor(container) {
      this.container = container;
      this.patientId = parseInt(container.dataset.patientId, 10);
      this.editable = container.dataset.editable !== 'false';
      this.tbody = container.querySelector('[data-role="rows"]');
      this.dialog = container.querySelector('[data-role="psa-edit-dialog"]');
      this.form = container.querySelector('[data-role="psa-edit-form"]');
      this.auditDialog = container.querySelector('[data-role="psa-audit-dialog"]');
      this.auditTbody = container.querySelector('[data-role="audit-rows"]');
      this.auditBadge = container.querySelector('[data-role="audit-count"]');
      this.points = [];
      this.bind();
      this.load();
    }

    bind() {
      if (!this.editable) return;
      this.container.addEventListener('click', (ev) => {
        const btn = ev.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        if (action === 'add-row') this.openDialog();
        else if (action === 'edit-row') {
          const tr = btn.closest('tr');
          this.openDialog(tr.dataset.pointId);
        } else if (action === 'delete-row') {
          const tr = btn.closest('tr');
          this.confirmDelete(tr.dataset.pointId);
        } else if (action === 'show-audit') this.openAuditDialog();
        else if (action === 'close-audit') this.auditDialog.close();
        else if (action === 'cancel-edit') this.dialog.close();
        else if (action === 'export-csv') this.exportCsv();
      });
      this.form.addEventListener('submit', (ev) => {
        ev.preventDefault();
        this.submitDialog();
      });
    }

    async load() {
      try {
        const res = await fetch(`/api/patients/${this.patientId}/psa_history`, { headers: { Accept: 'application/json' } });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'No se pudo cargar PSA history');
        this.points = data.points || [];
        this.render();
        this.refreshAuditCount();
      } catch (err) {
        console.error('[psa_history_crud] load:', err);
      }
    }

    render() {
      this.tbody.innerHTML = '';
      if (!this.points.length) {
        const empty = document.createElement('tr');
        empty.dataset.empty = '';
        empty.innerHTML = `<td colspan="${this.editable ? 7 : 6}" class="text-center text-slate-500 italic py-8">Sin puntos PSA capturados todavía.${this.editable ? ' Pulsa <strong>+ Agregar PSA</strong>.' : ''}</td>`;
        this.tbody.appendChild(empty);
        return;
      }
      for (const point of this.points) {
        this.tbody.appendChild(buildRow(point));
      }
    }

    openDialog(pointId) {
      this.form.reset();
      const titleEl = this.dialog.querySelector('[data-role="dialog-title"]');
      if (pointId) {
        const point = this.points.find((p) => String(p.id) === String(pointId));
        if (!point) return;
        titleEl.textContent = `Editar punto PSA #${point.id}`;
        this.form.point_id.value = point.id;
        this.form.value.value = point.value;
        this.form.sample_date.value = fmtDate(point.sample_date);
        this.form.clinical_state.value = point.clinical_state_at_measurement || '';
        this.form.line_label.value = point.line_label || '';
        this.form.source.value = point.source || 'laboratory';
      } else {
        titleEl.textContent = 'Agregar punto PSA';
        this.form.point_id.value = '';
      }
      if (typeof this.dialog.showModal === 'function') {
        this.dialog.showModal();
      } else {
        this.dialog.setAttribute('open', '');
      }
    }

    async submitDialog() {
      const fd = new FormData(this.form);
      const payload = Object.fromEntries(fd.entries());
      const pointId = payload.point_id;
      delete payload.point_id;
      payload.value = parseFloat(payload.value);

      try {
        let res, data;
        if (pointId) {
          res = await fetch(`/api/patients/${this.patientId}/psa_history/${pointId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        } else {
          res = await fetch(`/api/patients/${this.patientId}/psa_history`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        }
        data = await res.json();
        if (!data.success) throw new Error(data.error || 'Error al guardar');
        this.dialog.close();
        await this.load();
        this.notifySnapshot();
        this.toast('Punto PSA agregado a la torre del APE.');
      } catch (err) {
        console.error('[psa_history_crud] submit:', err);
        alert(err.message);
      }
    }

    async confirmDelete(pointId) {
      const reason = prompt('Razón del borrado (obligatoria por trazabilidad clínica):');
      if (!reason) return;
      try {
        const res = await fetch(`/api/patients/${this.patientId}/psa_history/${pointId}?reason=${encodeURIComponent(reason)}`, {
          method: 'DELETE',
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Error al eliminar');
        await this.load();
        this.notifySnapshot();
        this.toast('Punto PSA marcado como eliminado.');
      } catch (err) {
        console.error('[psa_history_crud] delete:', err);
        alert(err.message);
      }
    }

    async openAuditDialog() {
      try {
        const res = await fetch(`/api/patients/${this.patientId}/psa_audit_log?limit=200`);
        const data = await res.json();
        const entries = data.entries || [];
        this.auditTbody.innerHTML = '';
        if (!entries.length) {
          this.auditTbody.innerHTML = '<tr><td colspan="6" class="text-center text-slate-500 italic py-4">— sin entradas —</td></tr>';
        } else {
          for (const e of entries) {
            const tr = document.createElement('tr');
            tr.className = 'border-b border-slate-800';
            tr.innerHTML = `
              <td class="py-1 px-2 font-mono text-slate-300">${escapeHtml(e.timestamp || '')}</td>
              <td class="py-1 px-2"><span class="audit-op audit-op-${escapeHtml((e.operation || '').toLowerCase())}">${escapeHtml(e.operation)}</span></td>
              <td class="py-1 px-2">#${escapeHtml(e.point_id || '')}</td>
              <td class="py-1 px-2">${escapeHtml(e.actor || '')}</td>
              <td class="py-1 px-2 text-slate-400">${escapeHtml(e.reason || '')}</td>
              <td class="py-1 px-2 font-mono text-xs text-slate-300">${escapeHtml(e.value_before || '∅')} → ${escapeHtml(e.value_after || '∅')}</td>
            `;
            this.auditTbody.appendChild(tr);
          }
        }
        if (typeof this.auditDialog.showModal === 'function') {
          this.auditDialog.showModal();
        }
      } catch (err) {
        console.error('[psa_history_crud] audit:', err);
      }
    }

    async refreshAuditCount() {
      if (!this.auditBadge) return;
      try {
        const res = await fetch(`/api/patients/${this.patientId}/psa_audit_log?limit=500`);
        const data = await res.json();
        this.auditBadge.textContent = String(data.count || 0);
      } catch { /* silent */ }
    }

    exportCsv() {
      const header = ['fecha', 'psa_ng_ml', 'estadio', 'linea_terapeutica', 'origen', 'razon'];
      const rows = this.points.map((p) => [
        fmtDate(p.sample_date),
        p.value,
        p.clinical_state_at_measurement || '',
        p.line_label || '',
        p.source || '',
        (p.reason || '').replace(/[\r\n,]/g, ' '),
      ]);
      const csv = [header, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `psa_history_pt${this.patientId}_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }

    notifySnapshot() {
      // Aviso a la torre que el snapshot cambió. La fuente única de verdad
      // sigue siendo el backend; este evento sólo dispara un re-fetch.
      window.dispatchEvent(new CustomEvent('psa-snapshot-updated', { detail: { patientId: this.patientId } }));
    }

    toast(msg) {
      const out = document.createElement('output');
      out.role = 'status';
      out.className = 'psa-toast';
      out.textContent = msg;
      document.body.appendChild(out);
      requestAnimationFrame(() => out.classList.add('psa-toast-visible'));
      setTimeout(() => {
        out.classList.remove('psa-toast-visible');
        setTimeout(() => out.remove(), 400);
      }, 2500);
    }
  }

  function init() {
    document.querySelectorAll('.psa-history-section').forEach((el) => {
      if (el.dataset.psaHistoryBound) return;
      el.dataset.psaHistoryBound = '1';
      // Cada container guarda su propia instancia para callbacks externos.
      el._psaHistoryCrud = new PsaHistoryCrud(el);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  global.PsaHistoryCrud = PsaHistoryCrud;
  global.psaHistoryInit = init;
})(window);
