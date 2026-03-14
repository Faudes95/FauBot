# -*- coding: utf-8 -*-
"""
Servidor standalone para el modelo ML de Cáncer de Próstata.
Corre en puerto 8001, separado de main.py (puerto 8000).
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# Importar modelo
from prostate_cancer_model import (
    generate_synthetic_data,
    preprocess_data,
    ProstateCancerNet,
    train_model,
    evaluate_model,
    predict_patient,
    save_all,
    load_all,
    OUTPUT_DIR,
    SEED,
)
from sklearn.model_selection import train_test_split

app = FastAPI(title="Modelo ML - Cáncer de Próstata (Testing)")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Estado global en memoria
_state: Dict[str, Any] = {
    "model": None,
    "artifacts": None,
    "history": None,
    "report": None,
    "trained": False,
    "training_in_progress": False,
    "df": None,
    "uploaded_files": [],
    "patient_db": None,
}

# ============================================================================
# TEMPLATE HTML
# ============================================================================
PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Modelo ML — Cáncer de Próstata</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg: #0f1117;
            --surface: #1a1d27;
            --surface-2: #242836;
            --border: #2d3348;
            --text: #e4e6ef;
            --text-dim: #8b8fa3;
            --accent: #6c5ce7;
            --accent-2: #a29bfe;
            --green: #00b894;
            --red: #e74c3c;
            --orange: #f39c12;
            --blue: #0984e3;
            --radius: 12px;
        }
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1d27 0%, #2d1f5e 100%);
            border-bottom: 1px solid var(--border);
            padding: 20px 32px;
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .header h1 {
            font-size: 20px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-2), var(--green));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header .badge {
            background: var(--accent);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

        .tabs {
            display: flex;
            gap: 4px;
            background: var(--surface);
            padding: 4px;
            border-radius: var(--radius);
            margin-bottom: 24px;
        }
        .tab {
            flex: 1;
            padding: 12px;
            text-align: center;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 500;
            font-size: 14px;
            color: var(--text-dim);
            transition: all 0.2s;
            border: none;
            background: none;
        }
        .tab:hover { color: var(--text); background: var(--surface-2); }
        .tab.active {
            background: var(--accent);
            color: white;
        }
        .panel { display: none; }
        .panel.active { display: block; }

        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            margin-bottom: 16px;
        }
        .card h2 {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }

        label {
            display: block;
            font-size: 12px;
            font-weight: 500;
            color: var(--text-dim);
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        input, select {
            width: 100%;
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: var(--surface-2);
            color: var(--text);
            font-size: 14px;
            font-family: inherit;
            transition: border-color 0.2s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: var(--accent);
        }
        .field { margin-bottom: 16px; }

        .btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 24px;
            border-radius: 8px;
            border: none;
            font-family: inherit;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary {
            background: linear-gradient(135deg, var(--accent), #5a4bd1);
            color: white;
        }
        .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 15px rgba(108,92,231,0.4); }
        .btn-success {
            background: linear-gradient(135deg, var(--green), #00a382);
            color: white;
        }
        .btn-success:hover { transform: translateY(-1px); box-shadow: 0 4px 15px rgba(0,184,148,0.4); }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none !important;
        }

        .metric-card {
            background: var(--surface-2);
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }
        .metric-card .value {
            font-size: 28px;
            font-weight: 700;
            margin: 4px 0;
        }
        .metric-card .label {
            font-size: 11px;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .metric-card.green .value { color: var(--green); }
        .metric-card.blue .value { color: var(--blue); }
        .metric-card.orange .value { color: var(--orange); }
        .metric-card.red .value { color: var(--red); }
        .metric-card.accent .value { color: var(--accent-2); }

        .result-box {
            background: linear-gradient(135deg, #1e2235, #252a3e);
            border: 1px solid var(--accent);
            border-radius: var(--radius);
            padding: 24px;
            margin-top: 20px;
            display: none;
        }
        .result-box.visible { display: block; animation: slideIn 0.3s ease; }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .risk-badge {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 14px;
        }
        .risk-bajo { background: rgba(0,184,148,0.2); color: var(--green); border: 1px solid var(--green); }
        .risk-intermedio { background: rgba(243,156,18,0.2); color: var(--orange); border: 1px solid var(--orange); }
        .risk-alto { background: rgba(231,76,60,0.2); color: var(--red); border: 1px solid var(--red); }

        .progress-bar {
            width: 100%;
            height: 6px;
            background: var(--surface-2);
            border-radius: 3px;
            margin: 8px 0;
            overflow: hidden;
        }
        .progress-bar .fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s ease;
        }

        .prob-row {
            display: flex;
            align-items: center;
            gap: 12px;
            margin: 8px 0;
        }
        .prob-label { width: 150px; font-size: 13px; color: var(--text-dim); }
        .prob-bar { flex: 1; }
        .prob-value { width: 50px; text-align: right; font-weight: 600; font-size: 13px; }

        .log {
            background: #0d0f14;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 12px;
            color: var(--green);
            white-space: pre-wrap;
            line-height: 1.6;
        }

        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-dot.green { background: var(--green); box-shadow: 0 0 8px var(--green); }
        .status-dot.red { background: var(--red); }
        .status-dot.orange { background: var(--orange); animation: pulse 1.5s infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        .spinner {
            display: inline-block;
            width: 16px; height: 16px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .data-table th {
            text-align: left;
            padding: 10px 12px;
            background: var(--surface-2);
            color: var(--text-dim);
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .data-table td {
            padding: 10px 12px;
            border-top: 1px solid var(--border);
        }
        .data-table tr:hover td { background: rgba(108,92,231,0.05); }

        /* Upload styles */
        .upload-zone {
            border: 2px dashed var(--border);
            border-radius: var(--radius);
            padding: 48px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            background: var(--surface-2);
            position: relative;
        }
        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--accent);
            background: rgba(108,92,231,0.08);
        }
        .upload-zone .upload-icon {
            font-size: 48px;
            margin-bottom: 16px;
            display: block;
        }
        .upload-zone .upload-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .upload-zone .upload-sub {
            font-size: 13px;
            color: var(--text-dim);
        }
        .upload-zone input[type=file] {
            position: absolute;
            inset: 0;
            opacity: 0;
            cursor: pointer;
        }
        .file-list-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: var(--surface-2);
            border-radius: 8px;
            margin-bottom: 8px;
            animation: slideIn 0.3s ease;
        }
        .file-list-item .file-icon { font-size: 24px; }
        .file-list-item .file-info { flex: 1; }
        .file-list-item .file-name { font-weight: 600; font-size: 14px; }
        .file-list-item .file-meta { font-size: 12px; color: var(--text-dim); }
        .file-list-item .file-status {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }
        .file-status.success { background: rgba(0,184,148,0.2); color: var(--green); }
        .file-status.error { background: rgba(231,76,60,0.2); color: var(--red); }
        .file-status.processing { background: rgba(243,156,18,0.2); color: var(--orange); }
        .col-mapping {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 8px;
            align-items: center;
            padding: 8px 12px;
            background: var(--surface-2);
            border-radius: 6px;
            margin-bottom: 4px;
            font-size: 13px;
        }
        .col-mapping .arrow { color: var(--accent); font-weight: 700; }
        .col-mapping .col-found { color: var(--green); }
        .col-mapping .col-missing { color: var(--text-dim); font-style: italic; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🧬 Modelo ML — Cáncer de Próstata</h1>
        <span class="badge">STANDALONE · Puerto 8001</span>
        <span class="badge" style="background: var(--green)" id="model-status-badge">
            {{ "MODELO CARGADO ✓" if trained else "SIN ENTRENAR" }}
        </span>
    </div>

    <div class="container">
        <div class="tabs">
            <button class="tab active" onclick="showTab('train')">🏋️ Entrenar</button>
            <button class="tab" onclick="showTab('predict')">🔮 Predicción</button>
            <button class="tab" onclick="showTab('metrics')">📊 Métricas</button>
            <button class="tab" onclick="showTab('data')">📋 Datos</button>
            <button class="tab" onclick="showTab('upload')">📤 Subir Archivos</button>
        </div>

        <!-- TAB: ENTRENAR -->
        <div class="panel active" id="panel-train">
            <div class="card">
                <h2>⚙️ Configuración de Entrenamiento</h2>
                <div class="grid-3">
                    <div class="field">
                        <label>Muestras sintéticas</label>
                        <input type="number" id="num_samples" value="3000" min="500" max="50000" step="500">
                    </div>
                    <div class="field">
                        <label>Epochs máximos</label>
                        <input type="number" id="epochs" value="100" min="10" max="500">
                    </div>
                    <div class="field">
                        <label>Batch size</label>
                        <select id="batch_size">
                            <option value="16">16</option>
                            <option value="32" selected>32</option>
                            <option value="64">64</option>
                            <option value="128">128</option>
                        </select>
                    </div>
                </div>
                <br>
                <button class="btn btn-primary" id="btn-train" onclick="trainModel()">
                    🚀 Entrenar Modelo
                </button>
                <button class="btn btn-success" id="btn-quick" onclick="quickTrain()" style="margin-left: 8px;">
                    ⚡ Entrenamiento Rápido (500 muestras, 30 epochs)
                </button>
            </div>

            <div class="card" id="training-log-card" style="display:none">
                <h2>
                    <span class="status-dot orange" id="train-dot"></span>
                    Estado del Entrenamiento
                </h2>
                <div class="log" id="training-log">Esperando...</div>
            </div>

            <div id="train-results" style="display:none">
                <div class="grid-4" id="train-metrics-grid"></div>
            </div>
        </div>

        <!-- TAB: PREDICCIÓN -->
        <div class="panel" id="panel-predict">
            <div class="card">
                <h2>🧑‍⚕️ Datos del Paciente</h2>
                <div class="grid-3">
                    <div class="field">
                        <label>Edad</label>
                        <input type="number" id="p_age" value="68" min="18" max="100">
                    </div>
                    <div class="field">
                        <label>PSA (ng/mL)</label>
                        <input type="number" id="p_psa" value="15.3" min="0" max="500" step="0.1">
                    </div>
                    <div class="field">
                        <label>ECOG</label>
                        <select id="p_ecog">
                            <option value="0">0 — Asintomático</option>
                            <option value="1" selected>1 — Sintomático ambulatorio</option>
                            <option value="2">2 — En cama &lt;50% del día</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>Estadio Clínico (T)</label>
                        <select id="p_stage">
                            <option value="1">T1 — Tumor no palpable</option>
                            <option value="2">T2 — Confinado a próstata</option>
                            <option value="3" selected>T3 — Extensión extraprostática</option>
                            <option value="4">T4 — Invade estructuras adyacentes</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>Gleason Score</label>
                        <select id="p_gleason">
                            <option value="6">6 (3+3) — Bajo grado</option>
                            <option value="7">7 (3+4 / 4+3) — Intermedio</option>
                            <option value="8" selected>8 (4+4) — Alto grado</option>
                            <option value="9">9 (4+5 / 5+4) — Muy alto grado</option>
                            <option value="10">10 (5+5) — Máximo grado</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>Charlson Comorbidity Index</label>
                        <input type="number" id="p_cci" value="2" min="0" max="10">
                    </div>
                    <div class="field">
                        <label>Volumen Prostático (cc)</label>
                        <input type="number" id="p_vol" value="45" min="10" max="200" step="1">
                    </div>
                </div>
                <br>
                <button class="btn btn-primary" id="btn-predict" onclick="predictPatient()">
                    🔮 Predecir
                </button>
            </div>

            <div class="result-box" id="prediction-result">
                <h2 style="margin-bottom: 20px;">📋 Resultado de la Predicción</h2>
                <div id="prediction-content"></div>
            </div>
        </div>

        <!-- TAB: MÉTRICAS -->
        <div class="panel" id="panel-metrics">
            <div id="metrics-content">
                <div class="card" style="text-align:center; padding: 60px;">
                    <p style="color: var(--text-dim); font-size: 16px;">
                        Entrena el modelo primero para ver las métricas de evaluación.
                    </p>
                </div>
            </div>
        </div>

        <!-- TAB: DATOS -->
        <div class="panel" id="panel-data">
            <div class="card">
                <h2>📋 Muestra de Datos Sintéticos</h2>
                <p style="color: var(--text-dim); font-size: 13px; margin-bottom: 16px;">
                    Últimos datos generados con lógica clínica D'Amico. Entrena el modelo para generar datos.
                </p>
                <div id="data-table-container">
                    <p style="color: var(--text-dim); text-align: center; padding: 40px;">
                        Sin datos aún. Entrena el modelo para generar la tabla.
                    </p>
                </div>
            </div>
        </div>

        <!-- TAB: SUBIR ARCHIVOS -->
        <div class="panel" id="panel-upload">
            <div class="card">
                <h2>📤 Carga de Base de Datos de Pacientes</h2>
                <p style="color: var(--text-dim); font-size: 13px; margin-bottom: 20px;">
                    Sube archivos Excel (.xlsx, .xls) con datos de pacientes.
                    Las columnas se mapean automáticamente a los campos del modelo.
                </p>

                <div class="upload-zone" id="upload-zone">
                    <input type="file" id="file-input" accept=".xlsx,.xls" multiple>
                    <span class="upload-icon">📁</span>
                    <div class="upload-title">Arrastra archivos Excel aquí</div>
                    <div class="upload-sub">o haz clic para seleccionar · .xlsx, .xls · Máximo 50MB</div>
                </div>
            </div>

            <!-- Columnas esperadas -->
            <div class="card">
                <h2>📐 Columnas Esperadas</h2>
                <p style="color: var(--text-dim); font-size: 13px; margin-bottom: 12px;">
                    El archivo Excel debe contener estas columnas (no importa el orden ni mayúsculas):
                </p>
                <div class="grid-4" style="gap: 8px;">
                    <div class="metric-card" style="padding:10px">
                        <div class="label">Obligatorias</div>
                        <div style="font-size:13px;color:var(--green);margin-top:6px;text-align:left;line-height:1.8">
                            • age / edad<br>• psa<br>• gleason<br>• stage / estadio
                        </div>
                    </div>
                    <div class="metric-card" style="padding:10px">
                        <div class="label">Clínicas</div>
                        <div style="font-size:13px;color:var(--blue);margin-top:6px;text-align:left;line-height:1.8">
                            • ecog<br>• cci / charlson<br>• psad<br>• volumen_prostatico
                        </div>
                    </div>
                    <div class="metric-card" style="padding:10px">
                        <div class="label">Tratamiento</div>
                        <div style="font-size:13px;color:var(--accent-2);margin-top:6px;text-align:left;line-height:1.8">
                            • treatment / tratamiento<br>• risk / riesgo
                        </div>
                    </div>
                    <div class="metric-card" style="padding:10px">
                        <div class="label">Outcomes</div>
                        <div style="font-size:13px;color:var(--orange);margin-top:6px;text-align:left;line-height:1.8">
                            • cure_rate / tasa_curacion<br>• survival_5y<br>• survival_10y
                        </div>
                    </div>
                </div>
            </div>

            <!-- Preview de mapeo -->
            <div class="card" id="mapping-card" style="display:none">
                <h2>🔗 Mapeo de Columnas Detectado</h2>
                <div id="mapping-content"></div>
            </div>

            <!-- Historial de cargas -->
            <div class="card">
                <h2>📋 Historial de Cargas</h2>
                <div id="upload-history">
                    <p style="color: var(--text-dim); text-align: center; padding: 30px;">
                        Sin archivos cargados aún.
                    </p>
                </div>
                <div id="db-stats" style="display:none; margin-top: 16px;">
                    <div class="grid-3" id="db-stats-grid"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function showTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('panel-' + name).classList.add('active');
        }

        function quickTrain() {
            document.getElementById('num_samples').value = 500;
            document.getElementById('epochs').value = 30;
            document.getElementById('batch_size').value = 32;
            trainModel();
        }

        async function trainModel() {
            const btn = document.getElementById('btn-train');
            const btnQ = document.getElementById('btn-quick');
            btn.disabled = true;
            btnQ.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Entrenando...';

            const logCard = document.getElementById('training-log-card');
            const logEl = document.getElementById('training-log');
            logCard.style.display = 'block';
            logEl.textContent = '⏳ Iniciando entrenamiento...\\n';
            document.getElementById('train-dot').className = 'status-dot orange';

            const params = {
                num_samples: parseInt(document.getElementById('num_samples').value),
                epochs: parseInt(document.getElementById('epochs').value),
                batch_size: parseInt(document.getElementById('batch_size').value),
            };

            try {
                const res = await fetch('/api/train', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(params),
                });
                const data = await res.json();

                if (data.ok) {
                    document.getElementById('train-dot').className = 'status-dot green';
                    logEl.textContent += '✅ Entrenamiento completado\\n';
                    logEl.textContent += `📊 Muestras: ${data.samples}\\n`;
                    logEl.textContent += `📊 Epochs ejecutados: ${data.epochs_run}\\n`;
                    logEl.textContent += `📊 Risk Accuracy: ${(data.report.risk_accuracy * 100).toFixed(1)}%\\n`;
                    logEl.textContent += `📊 Treatment Accuracy: ${(data.report.treatment_accuracy * 100).toFixed(1)}%\\n`;
                    logEl.textContent += `📊 Cure Rate MAE: ${data.report.cure_rate_mae.toFixed(4)}\\n`;
                    logEl.textContent += `📊 Survival 5y MAE: ${data.report.survival_5y_mae.toFixed(4)}\\n`;
                    logEl.textContent += `📊 Survival 10y MAE: ${data.report.survival_10y_mae.toFixed(4)}\\n`;
                    if (data.report.survival_constraint_violations !== undefined) {
                        logEl.textContent += `⚕️  Violaciones constraint surv10≤surv5: ${data.report.survival_constraint_violations}\\n`;
                    }
                    logEl.textContent += '💾 Modelo guardado en disco\\n';

                    document.getElementById('model-status-badge').textContent = 'MODELO CARGADO ✓';
                    document.getElementById('model-status-badge').style.background = '#00b894';

                    showTrainMetrics(data.report);
                    loadMetrics();
                    loadData();
                } else {
                    document.getElementById('train-dot').className = 'status-dot red';
                    logEl.textContent += '❌ Error: ' + (data.error || 'desconocido') + '\\n';
                }
            } catch (e) {
                document.getElementById('train-dot').className = 'status-dot red';
                logEl.textContent += '❌ Error de conexión: ' + e.message + '\\n';
            }

            btn.disabled = false;
            btnQ.disabled = false;
            btn.innerHTML = '🚀 Entrenar Modelo';
        }

        function showTrainMetrics(report) {
            const grid = document.getElementById('train-metrics-grid');
            const container = document.getElementById('train-results');
            container.style.display = 'block';
            grid.innerHTML = `
                <div class="metric-card green">
                    <div class="label">Risk Accuracy</div>
                    <div class="value">${(report.risk_accuracy * 100).toFixed(1)}%</div>
                </div>
                <div class="metric-card blue">
                    <div class="label">Treatment Acc</div>
                    <div class="value">${(report.treatment_accuracy * 100).toFixed(1)}%</div>
                </div>
                <div class="metric-card accent">
                    <div class="label">AUC-ROC Risk</div>
                    <div class="value">${report.risk_auc_roc ? report.risk_auc_roc.toFixed(3) : 'N/A'}</div>
                </div>
                <div class="metric-card orange">
                    <div class="label">Cure MAE</div>
                    <div class="value">${report.cure_rate_mae.toFixed(3)}</div>
                </div>
            `;
        }

        async function predictPatient() {
            const btn = document.getElementById('btn-predict');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Prediciendo...';

            const psa = parseFloat(document.getElementById('p_psa').value);
            const vol = parseFloat(document.getElementById('p_vol').value);
            const payload = {
                age: parseInt(document.getElementById('p_age').value),
                psa: psa,
                ecog: parseInt(document.getElementById('p_ecog').value),
                stage: parseInt(document.getElementById('p_stage').value),
                gleason: parseInt(document.getElementById('p_gleason').value),
                cci: parseInt(document.getElementById('p_cci').value),
                psad: psa / (vol || 40),
                volumen_prostatico: vol,
            };

            try {
                const res = await fetch('/api/predict', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
                const data = await res.json();

                if (data.error) {
                    alert(data.error);
                } else {
                    renderPrediction(data);
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }

            btn.disabled = false;
            btn.innerHTML = '🔮 Predecir';
        }

        function renderPrediction(data) {
            const box = document.getElementById('prediction-result');
            const content = document.getElementById('prediction-content');
            box.classList.add('visible');

            const riskLevel = data.riesgo.nivel;
            const riskClass = riskLevel === 'ALTO' ? 'risk-alto' :
                              riskLevel === 'INTERMEDIO' ? 'risk-intermedio' : 'risk-bajo';

            let html = `
                <div class="grid-2" style="margin-bottom: 20px;">
                    <div>
                        <label>NIVEL DE RIESGO</label>
                        <div style="margin-top: 8px;">
                            <span class="risk-badge ${riskClass}">${riskLevel}</span>
                        </div>
                        <div style="margin-top: 16px;">
            `;
            for (const [nivel, prob] of Object.entries(data.riesgo.probabilidades)) {
                const pct = parseFloat(prob);
                const color = nivel === 'ALTO' ? 'var(--red)' :
                              nivel === 'INTERMEDIO' ? 'var(--orange)' : 'var(--green)';
                html += `
                    <div class="prob-row">
                        <span class="prob-label">${nivel}</span>
                        <div class="prob-bar">
                            <div class="progress-bar"><div class="fill" style="width:${pct}%;background:${color}"></div></div>
                        </div>
                        <span class="prob-value">${prob}</span>
                    </div>`;
            }
            html += `</div></div><div>
                        <label>TRATAMIENTO RECOMENDADO</label>
                        <div style="margin-top: 8px; font-size: 18px; font-weight: 700; color: var(--accent-2);">
                            ${data.tratamiento_recomendado.principal.replace(/_/g,' ').toUpperCase()}
                        </div>
                        <div style="margin-top: 16px;">`;
            for (const [trat, prob] of Object.entries(data.tratamiento_recomendado.probabilidades)) {
                const pct = parseFloat(prob);
                html += `
                    <div class="prob-row">
                        <span class="prob-label">${trat.replace(/_/g,' ')}</span>
                        <div class="prob-bar">
                            <div class="progress-bar"><div class="fill" style="width:${pct}%;background:var(--accent)"></div></div>
                        </div>
                        <span class="prob-value">${prob}</span>
                    </div>`;
            }
            html += `</div></div></div>`;

            html += `
                <div class="grid-3" style="margin-top: 20px;">
                    <div class="metric-card green">
                        <div class="label">Tasa de Curación</div>
                        <div class="value">${data.tasa_curacion}</div>
                    </div>
                    <div class="metric-card blue">
                        <div class="label">Supervivencia 5 Años</div>
                        <div class="value">${data.supervivencia_5_anios}</div>
                    </div>
                    <div class="metric-card accent">
                        <div class="label">Supervivencia 10 Años</div>
                        <div class="value">${data.supervivencia_10_anios}</div>
                    </div>
                </div>`;

            content.innerHTML = html;
        }

        async function loadMetrics() {
            try {
                const res = await fetch('/api/report');
                const data = await res.json();
                if (!data || data.error) return;

                const el = document.getElementById('metrics-content');
                el.innerHTML = `
                    <div class="grid-4" style="margin-bottom: 16px;">
                        <div class="metric-card green">
                            <div class="label">Risk Accuracy</div>
                            <div class="value">${(data.risk_accuracy * 100).toFixed(1)}%</div>
                        </div>
                        <div class="metric-card blue">
                            <div class="label">Treatment Accuracy</div>
                            <div class="value">${(data.treatment_accuracy * 100).toFixed(1)}%</div>
                        </div>
                        <div class="metric-card accent">
                            <div class="label">AUC-ROC (Risk)</div>
                            <div class="value">${data.risk_auc_roc ? data.risk_auc_roc.toFixed(3) : 'N/A'}</div>
                        </div>
                        <div class="metric-card orange">
                            <div class="label">Constraint Violations</div>
                            <div class="value">${data.survival_constraint_violations || 0}</div>
                        </div>
                    </div>
                    <div class="card">
                        <h2>📈 Error Absoluto Medio (MAE) — Regresiones</h2>
                        <div class="grid-3">
                            <div class="metric-card">
                                <div class="label">Tasa de Curación</div>
                                <div class="value" style="color:var(--green)">${data.cure_rate_mae.toFixed(4)}</div>
                            </div>
                            <div class="metric-card">
                                <div class="label">Supervivencia 5 Años</div>
                                <div class="value" style="color:var(--blue)">${data.survival_5y_mae.toFixed(4)}</div>
                            </div>
                            <div class="metric-card">
                                <div class="label">Supervivencia 10 Años</div>
                                <div class="value" style="color:var(--accent-2)">${data.survival_10y_mae.toFixed(4)}</div>
                            </div>
                        </div>
                    </div>
                `;
            } catch (e) {}
        }

        async function loadData() {
            try {
                const res = await fetch('/api/data/sample');
                const data = await res.json();
                if (!data.rows || !data.rows.length) return;

                const cols = data.columns;
                let html = '<div style="overflow-x:auto"><table class="data-table"><thead><tr>';
                cols.forEach(c => { html += `<th>${c}</th>`; });
                html += '</tr></thead><tbody>';
                data.rows.forEach(row => {
                    html += '<tr>';
                    cols.forEach(c => {
                        let v = row[c];
                        if (typeof v === 'number') v = v.toFixed ? v.toFixed(3) : v;
                        html += `<td>${v}</td>`;
                    });
                    html += '</tr>';
                });
                html += '</tbody></table></div>';
                document.getElementById('data-table-container').innerHTML = html;
            } catch (e) {}
        }

        // ============ UPLOAD FUNCTIONS ============
        const uploadZone = document.getElementById('upload-zone');
        const fileInput = document.getElementById('file-input');

        ['dragenter','dragover'].forEach(e => {
            uploadZone.addEventListener(e, ev => { ev.preventDefault(); uploadZone.classList.add('dragover'); });
        });
        ['dragleave','drop'].forEach(e => {
            uploadZone.addEventListener(e, ev => { ev.preventDefault(); uploadZone.classList.remove('dragover'); });
        });
        uploadZone.addEventListener('drop', ev => {
            const files = ev.dataTransfer.files;
            if (files.length) handleFiles(files);
        });
        fileInput.addEventListener('change', ev => {
            if (ev.target.files.length) handleFiles(ev.target.files);
        });

        async function handleFiles(files) {
            for (const file of files) {
                if (!file.name.match(/\.xlsx?$/i)) {
                    alert(`${file.name} no es un archivo Excel válido`);
                    continue;
                }
                await uploadFile(file);
            }
        }

        async function uploadFile(file) {
            // Add processing item to history
            const histEl = document.getElementById('upload-history');
            const itemId = 'upload-' + Date.now();
            const sizeMB = (file.size / 1024 / 1024).toFixed(2);
            histEl.innerHTML = `
                <div class="file-list-item" id="${itemId}">
                    <span class="file-icon">📊</span>
                    <div class="file-info">
                        <div class="file-name">${file.name}</div>
                        <div class="file-meta">${sizeMB} MB · Procesando...</div>
                    </div>
                    <span class="file-status processing"><span class="spinner"></span> Subiendo</span>
                </div>
            ` + (histEl.innerHTML.includes('Sin archivos') ? '' : histEl.innerHTML);

            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await res.json();
                const item = document.getElementById(itemId);

                if (data.ok) {
                    item.querySelector('.file-status').className = 'file-status success';
                    item.querySelector('.file-status').textContent = `✓ ${data.rows_loaded} registros`;
                    item.querySelector('.file-meta').textContent =
                        `${sizeMB} MB · ${data.rows_total} filas · ${data.cols_mapped} columnas mapeadas · ${new Date().toLocaleTimeString()}`;

                    // Show mapping
                    if (data.mapping && data.mapping.length) {
                        showMapping(data.mapping);
                    }
                    // Update DB stats
                    updateDbStats(data.db_stats);
                } else {
                    item.querySelector('.file-status').className = 'file-status error';
                    item.querySelector('.file-status').textContent = '✗ Error';
                    item.querySelector('.file-meta').textContent = `${sizeMB} MB · Error: ${data.error}`;
                }
            } catch (e) {
                const item = document.getElementById(itemId);
                if (item) {
                    item.querySelector('.file-status').className = 'file-status error';
                    item.querySelector('.file-status').textContent = '✗ Error';
                    item.querySelector('.file-meta').textContent = `Error de conexión: ${e.message}`;
                }
            }
        }

        function showMapping(mapping) {
            const card = document.getElementById('mapping-card');
            const content = document.getElementById('mapping-content');
            card.style.display = 'block';
            let html = '';
            mapping.forEach(m => {
                const cls = m.found ? 'col-found' : 'col-missing';
                const icon = m.found ? '✓' : '—';
                html += `<div class="col-mapping">
                    <span>${m.expected}</span>
                    <span class="arrow">→</span>
                    <span class="${cls}">${icon} ${m.mapped_to || 'no encontrada'}</span>
                </div>`;
            });
            content.innerHTML = html;
        }

        function updateDbStats(stats) {
            if (!stats) return;
            const el = document.getElementById('db-stats');
            const grid = document.getElementById('db-stats-grid');
            el.style.display = 'block';
            grid.innerHTML = `
                <div class="metric-card green">
                    <div class="label">Total Pacientes</div>
                    <div class="value">${stats.total_rows}</div>
                </div>
                <div class="metric-card blue">
                    <div class="label">Archivos Cargados</div>
                    <div class="value">${stats.files_loaded}</div>
                </div>
                <div class="metric-card accent">
                    <div class="label">Columnas Activas</div>
                    <div class="value">${stats.columns}</div>
                </div>
            `;
        }

        // Cargar estado al inicio
        fetch('/api/status').then(r => r.json()).then(data => {
            if (data.trained) {
                document.getElementById('model-status-badge').textContent = 'MODELO CARGADO ✓';
                document.getElementById('model-status-badge').style.background = '#00b894';
                loadMetrics();
                loadData();
            }
            if (data.db_stats) updateDbStats(data.db_stats);
        }).catch(() => {});
    </script>
</body>
</html>
"""


# ============================================================================
# API ENDPOINTS
# ============================================================================
@app.get("/", response_class=HTMLResponse)
async def home():
    return PAGE_TEMPLATE.replace("{{ \"MODELO CARGADO ✓\" if trained else \"SIN ENTRENAR\" }}",
                                 "MODELO CARGADO ✓" if _state["trained"] else "SIN ENTRENAR")


@app.get("/api/status")
async def api_status():
    db_stats = None
    if _state["patient_db"] is not None:
        db_stats = {
            "total_rows": len(_state["patient_db"]),
            "files_loaded": len(_state["uploaded_files"]),
            "columns": len(_state["patient_db"].columns),
        }
    return {"trained": _state["trained"], "db_stats": db_stats}


@app.post("/api/train")
async def api_train(request: Request):
    if _state["training_in_progress"]:
        return JSONResponse({"ok": False, "error": "Entrenamiento en progreso"})

    _state["training_in_progress"] = True
    try:
        body = await request.json()
        num_samples = int(body.get("num_samples", 3000))
        epochs = int(body.get("epochs", 100))
        batch_size = int(body.get("batch_size", 32))

        # Generate data
        df = generate_synthetic_data(num_samples)
        _state["df"] = df

        # Preprocess
        X, y_risk, y_treatment, y_cure, y_surv5, y_surv10, artifacts = preprocess_data(df)

        # Split
        (X_train, X_test,
         y_risk_train, y_risk_test,
         y_treatment_train, y_treatment_test,
         y_cure_train, y_cure_test,
         y_surv5_train, y_surv5_test,
         y_surv10_train, y_surv10_test) = train_test_split(
            X, y_risk, y_treatment, y_cure, y_surv5, y_surv10,
            test_size=0.2, random_state=SEED, stratify=y_risk
        )

        targets_train = {
            'risk_output': y_risk_train,
            'treatment_output': y_treatment_train,
            'cure_rate_output': y_cure_train,
            'survival_5y_output': y_surv5_train,
            'survival_10y_output': y_surv10_train,
        }
        targets_test = {
            'risk_output': y_risk_test,
            'treatment_output': y_treatment_test,
            'cure_rate_output': y_cure_test,
            'survival_5y_output': y_surv5_test,
            'survival_10y_output': y_surv10_test,
        }

        n_risk = len(artifacts['risk_encoder'].classes_)
        n_treatment = len(artifacts['treatment_encoder'].classes_)
        model = ProstateCancerNet(X_train.shape[1], n_risk, n_treatment)
        history = train_model(model, X_train, X_test, targets_train, targets_test,
                              epochs=epochs, batch_size=batch_size)
        report = evaluate_model(model, X_test, targets_test, artifacts)

        save_all(model, artifacts, report)

        _state["model"] = model
        _state["artifacts"] = artifacts
        _state["history"] = history
        _state["report"] = report
        _state["trained"] = True

        return JSONResponse({
            "ok": True,
            "samples": num_samples,
            "epochs_run": len(history.get('loss', [])),
            "report": report,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        _state["training_in_progress"] = False


@app.post("/api/predict")
async def api_predict(request: Request):
    if not _state["trained"] or _state["model"] is None:
        return JSONResponse({"error": "Modelo no entrenado. Entrena primero."}, status_code=400)

    body = await request.json()
    try:
        result = predict_patient(_state["model"], _state["artifacts"], body)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/report")
async def api_report():
    if _state["report"] is None:
        return JSONResponse({"error": "Sin reporte"}, status_code=404)
    return JSONResponse(_state["report"])


@app.get("/api/data/sample")
async def api_data_sample():
    if _state["df"] is None:
        return JSONResponse({"rows": [], "columns": []})
    sample = _state["df"].head(50)
    return JSONResponse({
        "columns": list(sample.columns),
        "rows": sample.to_dict(orient="records"),
    })


# ============================================================================
# UPLOAD ENDPOINT
# ============================================================================
COLUMN_ALIASES = {
    'age': ['age', 'edad', 'age_years', 'anos', 'años'],
    'psa': ['psa', 'psa_total', 'psa_ng_ml', 'antigeno_prostatico'],
    'ecog': ['ecog', 'ecog_score', 'performance_status'],
    'stage': ['stage', 'estadio', 'estadio_clinico', 't_stage', 'tnm_t'],
    'gleason': ['gleason', 'gleason_score', 'gleason_sum', 'score_gleason'],
    'cci': ['cci', 'charlson', 'charlson_index', 'comorbidity', 'indice_charlson'],
    'psad': ['psad', 'psa_density', 'densidad_psa'],
    'treatment': ['treatment', 'tratamiento', 'tx', 'terapia'],
    'risk': ['risk', 'riesgo', 'risk_level', 'nivel_riesgo'],
    'cure_rate': ['cure_rate', 'tasa_curacion', 'curacion'],
    'survival_5y': ['survival_5y', 'supervivencia_5', 'surv5', 'sobrevida_5'],
    'survival_10y': ['survival_10y', 'supervivencia_10', 'surv10', 'sobrevida_10'],
}


def _map_columns(df_columns: List[str]) -> Dict[str, Optional[str]]:
    """Maps Excel column names to expected model columns using aliases."""
    mapping = {}
    lower_cols = {c.lower().strip().replace(' ', '_'): c for c in df_columns}
    for target, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in lower_cols:
                found = lower_cols[alias]
                break
        mapping[target] = found
    return mapping


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        return JSONResponse({"ok": False, "error": "Solo se aceptan archivos .xlsx o .xls"})

    try:
        contents = await file.read()
        filepath = os.path.join(UPLOAD_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
        with open(filepath, 'wb') as f:
            f.write(contents)

        # Read Excel
        try:
            df = pd.read_excel(filepath, engine='openpyxl')
        except Exception:
            df = pd.read_excel(filepath)

        if df.empty:
            return JSONResponse({"ok": False, "error": "El archivo está vacío"})

        # Map columns
        col_map = _map_columns(list(df.columns))
        mapped_df = pd.DataFrame()
        mapping_info = []

        for target, source in col_map.items():
            if source and source in df.columns:
                mapped_df[target] = df[source]
                mapping_info.append({"expected": target, "mapped_to": source, "found": True})
            else:
                mapping_info.append({"expected": target, "mapped_to": None, "found": False})

        # Also keep unmapped columns for reference
        mapped_sources = {m['mapped_to'] for m in mapping_info if m['found']}
        for col in df.columns:
            if col not in mapped_sources:
                mapped_df[f"_extra_{col}"] = df[col]

        rows_loaded = len(mapped_df)
        cols_mapped = sum(1 for m in mapping_info if m['found'])

        # Append to patient database
        if _state["patient_db"] is None:
            _state["patient_db"] = mapped_df
        else:
            _state["patient_db"] = pd.concat([_state["patient_db"], mapped_df], ignore_index=True)

        _state["uploaded_files"].append({
            "filename": file.filename,
            "rows": rows_loaded,
            "cols_mapped": cols_mapped,
            "timestamp": datetime.now().isoformat(),
        })

        db_stats = {
            "total_rows": len(_state["patient_db"]),
            "files_loaded": len(_state["uploaded_files"]),
            "columns": len([c for c in _state["patient_db"].columns if not c.startswith('_extra_')]),
        }

        return JSONResponse({
            "ok": True,
            "rows_total": len(df),
            "rows_loaded": rows_loaded,
            "cols_mapped": cols_mapped,
            "mapping": mapping_info,
            "db_stats": db_stats,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/api/patients/sample")
async def api_patients_sample():
    if _state["patient_db"] is None:
        return JSONResponse({"rows": [], "columns": []})
    visible_cols = [c for c in _state["patient_db"].columns if not c.startswith('_extra_')]
    sample = _state["patient_db"][visible_cols].head(50)
    return JSONResponse({
        "columns": list(sample.columns),
        "rows": json.loads(sample.to_json(orient="records", default_handler=str)),
    })


if __name__ == "__main__":
    # Intentar cargar modelo existente
    try:
        model, artifacts = load_all()
        _state["model"] = model
        _state["artifacts"] = artifacts
        _state["trained"] = True
        report_path = os.path.join(OUTPUT_DIR, "evaluation_report.json")
        if os.path.exists(report_path):
            with open(report_path) as f:
                _state["report"] = json.load(f)
        print("✅ Modelo pre-entrenado cargado")
    except Exception:
        print("ℹ️  Sin modelo pre-entrenado. Entrena desde la interfaz web.")

    print("🚀 Servidor ML en http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
