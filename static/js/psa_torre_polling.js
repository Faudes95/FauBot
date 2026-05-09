/* psa_torre_polling.js
 *
 * Mantiene la torre de control APE sincronizada con el backend.
 *
 * Estrategia:
 *   - Polling cada 30 s sobre /api/patients/<id>/psa_kinetics_snapshot.
 *   - Pausa automática cuando la pestaña no está visible (visibilitychange).
 *   - Backoff exponencial hasta 5 min en errores HTTP / red.
 *   - Refresh inmediato al recibir el evento custom `psa-snapshot-updated`
 *     (lo emite psa_history_crud.js tras cualquier CRUD).
 *
 * Punto de actualización de UI: dispatcha `psa-torre-render` con el snapshot
 * normalizado. El componente del perfil escucha y actualiza Chart.js + chips
 * sin reload.
 */
(function (global) {
  'use strict';

  const DEFAULT_INTERVAL = 30000;
  const MAX_BACKOFF = 5 * 60 * 1000;

  class PsaTorrePolling {
    constructor(patientId, opts) {
      opts = opts || {};
      this.patientId = patientId;
      this.intervalMs = opts.intervalMs || DEFAULT_INTERVAL;
      this.timer = null;
      this.backoff = 0;
      this.lastComputedAt = null;
      this.running = false;
      this._onVisibility = this._onVisibility.bind(this);
      this._onForceRefresh = this._onForceRefresh.bind(this);
    }

    start() {
      if (this.running) return;
      this.running = true;
      document.addEventListener('visibilitychange', this._onVisibility);
      window.addEventListener('psa-snapshot-updated', this._onForceRefresh);
      this._schedule(0);
    }

    stop() {
      this.running = false;
      document.removeEventListener('visibilitychange', this._onVisibility);
      window.removeEventListener('psa-snapshot-updated', this._onForceRefresh);
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
      }
    }

    forceRefresh() {
      if (!this.running) return;
      if (this.timer) clearTimeout(this.timer);
      this._tick();
    }

    _onVisibility() {
      if (document.visibilityState === 'visible') {
        // Al regresar el foco, refresca de inmediato y reanuda intervalo.
        if (this.timer) clearTimeout(this.timer);
        this._tick();
      }
    }

    _onForceRefresh(ev) {
      if (!ev.detail || ev.detail.patientId === this.patientId) {
        this.forceRefresh();
      }
    }

    _schedule(delay) {
      if (!this.running) return;
      this.timer = setTimeout(() => this._tick(), delay);
    }

    async _tick() {
      if (document.visibilityState === 'hidden') {
        // Re-agendar pero sin pegarle al servidor.
        this._schedule(this.intervalMs);
        return;
      }
      try {
        const res = await fetch(`/api/patients/${this.patientId}/psa_kinetics_snapshot`, {
          headers: { Accept: 'application/json' },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const snap = (data && data.snapshot) || null;
        if (snap && snap.computed_at !== this.lastComputedAt) {
          this.lastComputedAt = snap.computed_at;
          window.dispatchEvent(new CustomEvent('psa-torre-render', { detail: { snapshot: snap, patientId: this.patientId } }));
        }
        this.backoff = 0;
        this._schedule(this.intervalMs);
      } catch (err) {
        console.warn('[psa_torre_polling] error:', err);
        this.backoff = Math.min(this.backoff ? this.backoff * 2 : this.intervalMs, MAX_BACKOFF);
        this._schedule(this.backoff);
      }
    }
  }

  function init() {
    const containers = document.querySelectorAll('[data-psa-torre-poll]');
    containers.forEach((el) => {
      if (el.dataset.psaPollBound) return;
      el.dataset.psaPollBound = '1';
      const pid = parseInt(el.dataset.patientId || el.dataset.psaTorrePoll, 10);
      if (!pid) return;
      const poller = new PsaTorrePolling(pid);
      poller.start();
      el._psaPolling = poller;
      // Exponer el primer poller para callbacks globales.
      if (!global.psaPolling) global.psaPolling = poller;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  global.PsaTorrePolling = PsaTorrePolling;
  global.psaTorrePollingInit = init;
})(window);
