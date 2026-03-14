# -*- coding: utf-8 -*-
"""
Modelo Multi-Output de Deep Learning para Cáncer de Próstata — PyTorch
"""
import os
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import OneHotEncoder, StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, mean_absolute_error
import joblib

SEED = 42
np.random.seed(SEED)
torch.manual_seed(SEED)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


# ============================================================================
# 1. DATOS SINTÉTICOS CON LÓGICA CLÍNICA
# ============================================================================
def generate_synthetic_data(num_samples: int = 3000) -> pd.DataFrame:
    np.random.seed(SEED)
    age = np.random.randint(45, 85, num_samples)
    psa = np.random.exponential(6, num_samples) + 0.5
    ecog = np.random.choice([0, 0, 0, 1, 1, 2], num_samples)
    stage = np.random.choice([1, 1, 2, 2, 2, 3, 3, 4], num_samples)
    gleason = np.random.choice([6, 6, 7, 7, 7, 8, 8, 9, 10], num_samples)
    cci = np.random.choice([0, 0, 0, 1, 1, 2, 2, 3, 4], num_samples)
    vol = np.random.uniform(25, 90, num_samples)
    psad = psa / vol

    # Risk scoring tipo D'Amico
    rs = np.zeros(num_samples)
    rs += np.where(gleason <= 6, 0, np.where(gleason == 7, 1, np.where(gleason == 8, 2, 3)))
    rs += np.where(psa < 10, 0, np.where(psa < 20, 1, 2))
    rs += np.where(stage <= 1, 0, np.where(stage == 2, 0.5, np.where(stage == 3, 1.5, 2.5)))
    rs += ecog * 0.5
    risk = np.where(rs < 2.0, 0, np.where(rs < 4.5, 1, 2))

    treatment = np.empty(num_samples, dtype=object)
    for i in range(num_samples):
        if risk[i] == 0:
            treatment[i] = np.random.choice(['vigilancia_activa', 'radioterapia', 'prostatectomia'], p=[0.50, 0.25, 0.25])
        elif risk[i] == 1:
            treatment[i] = np.random.choice(['prostatectomia', 'radioterapia', 'hormonoterapia', 'vigilancia_activa'], p=[0.35, 0.35, 0.20, 0.10])
        else:
            treatment[i] = np.random.choice(['hormonoterapia', 'quimioterapia', 'radioterapia', 'prostatectomia'], p=[0.35, 0.30, 0.20, 0.15])

    rs_norm = (rs - rs.min()) / (rs.max() - rs.min() + 1e-8)
    s5_base = 1.0 - rs_norm * 0.6
    age_f = np.clip((age - 45) / 40, 0, 1) * 0.15
    cci_f = cci * 0.05
    survival_5y = np.clip(s5_base - age_f - cci_f + np.random.normal(0, 0.05, num_samples), 0.05, 0.99)
    survival_10y = np.clip(survival_5y * np.random.uniform(0.55, 0.95, num_samples), 0.02, survival_5y - 0.01)
    cure_base = 1.0 - rs_norm * 0.7
    surg = np.where(treatment == 'prostatectomia', 0.10, 0.0)
    cure_rate = np.clip(cure_base + surg + np.random.normal(0, 0.06, num_samples), 0.01, 0.98)

    return pd.DataFrame({
        'age': age, 'psa': psa, 'ecog': ecog, 'stage': stage,
        'gleason': gleason, 'cci': cci, 'psad': psad,
        'treatment': treatment, 'risk': risk.astype(int),
        'cure_rate': cure_rate, 'survival_5y': survival_5y, 'survival_10y': survival_10y,
    })


# ============================================================================
# 2. PREPROCESAMIENTO
# ============================================================================
def preprocess_data(df: pd.DataFrame):
    df = df.copy()
    df['psa_log'] = np.log1p(df['psa'])
    cat_cols = ['stage', 'gleason']
    encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    encoded = encoder.fit_transform(df[cat_cols].astype(str))
    num_cols = ['age', 'psa_log', 'ecog', 'cci', 'psad']
    scaler = StandardScaler()
    scaled = scaler.fit_transform(df[num_cols])
    X = np.concatenate([scaled, encoded], axis=1)

    risk_encoder = LabelEncoder()
    y_risk = risk_encoder.fit_transform(df['risk'])
    treatment_encoder = LabelEncoder()
    y_treatment = treatment_encoder.fit_transform(df['treatment'])

    artifacts = {
        'encoder': encoder, 'scaler': scaler,
        'risk_encoder': risk_encoder, 'treatment_encoder': treatment_encoder,
        'feature_names': num_cols + list(encoder.get_feature_names_out(cat_cols)),
        'num_cols': num_cols, 'cat_cols': cat_cols,
    }
    return X, y_risk, y_treatment, df['cure_rate'].values, df['survival_5y'].values, df['survival_10y'].values, artifacts


# ============================================================================
# 3. MODELO PYTORCH
# ============================================================================
class ProstateCancerNet(nn.Module):
    def __init__(self, input_dim, n_risk, n_treatment):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, 64), nn.ReLU(), nn.BatchNorm1d(64), nn.Dropout(0.25),
            nn.Linear(64, 128), nn.ReLU(), nn.BatchNorm1d(128), nn.Dropout(0.25),
            nn.Linear(128, 64), nn.ReLU(), nn.BatchNorm1d(64), nn.Dropout(0.2),
        )
        self.risk_head = nn.Linear(64, n_risk)
        self.treatment_head = nn.Linear(64, n_treatment)
        self.cure_head = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())
        self.surv5_head = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())
        self.surv10_head = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())

    def forward(self, x):
        h = self.shared(x)
        return (
            self.risk_head(h),
            self.treatment_head(h),
            self.cure_head(h).squeeze(-1),
            self.surv5_head(h).squeeze(-1),
            self.surv10_head(h).squeeze(-1),
        )


def train_model(model, X_train, X_test, targets_train, targets_test,
                epochs=100, batch_size=32, lr=0.001):
    model.to(DEVICE)

    X_tr = torch.tensor(X_train, dtype=torch.float32).to(DEVICE)
    X_te = torch.tensor(X_test, dtype=torch.float32).to(DEVICE)
    y_risk_tr = torch.tensor(targets_train['risk_output'], dtype=torch.long).to(DEVICE)
    y_treat_tr = torch.tensor(targets_train['treatment_output'], dtype=torch.long).to(DEVICE)
    y_cure_tr = torch.tensor(targets_train['cure_rate_output'], dtype=torch.float32).to(DEVICE)
    y_s5_tr = torch.tensor(targets_train['survival_5y_output'], dtype=torch.float32).to(DEVICE)
    y_s10_tr = torch.tensor(targets_train['survival_10y_output'], dtype=torch.float32).to(DEVICE)

    y_risk_te = torch.tensor(targets_test['risk_output'], dtype=torch.long).to(DEVICE)
    y_treat_te = torch.tensor(targets_test['treatment_output'], dtype=torch.long).to(DEVICE)
    y_cure_te = torch.tensor(targets_test['cure_rate_output'], dtype=torch.float32).to(DEVICE)
    y_s5_te = torch.tensor(targets_test['survival_5y_output'], dtype=torch.float32).to(DEVICE)
    y_s10_te = torch.tensor(targets_test['survival_10y_output'], dtype=torch.float32).to(DEVICE)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=7, factor=0.5, min_lr=1e-6)
    ce_loss = nn.CrossEntropyLoss()
    mse_loss = nn.MSELoss()

    loss_weights = {'risk': 2.0, 'treatment': 1.5, 'cure': 1.0, 'surv5': 1.5, 'surv10': 1.0}

    best_val_loss = float('inf')
    patience_counter = 0
    best_state = None
    history = {'loss': [], 'val_loss': []}

    n = len(X_tr)
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n).to(DEVICE)
        epoch_loss = 0.0
        n_batches = 0

        for i in range(0, n, batch_size):
            idx = perm[i:i+batch_size]
            r, t, c, s5, s10 = model(X_tr[idx])
            loss = (loss_weights['risk'] * ce_loss(r, y_risk_tr[idx]) +
                    loss_weights['treatment'] * ce_loss(t, y_treat_tr[idx]) +
                    loss_weights['cure'] * mse_loss(c, y_cure_tr[idx]) +
                    loss_weights['surv5'] * mse_loss(s5, y_s5_tr[idx]) +
                    loss_weights['surv10'] * mse_loss(s10, y_s10_tr[idx]))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1

        avg_train_loss = epoch_loss / max(n_batches, 1)

        # Validation
        model.eval()
        with torch.no_grad():
            r, t, c, s5, s10 = model(X_te)
            val_loss = (loss_weights['risk'] * ce_loss(r, y_risk_te) +
                        loss_weights['treatment'] * ce_loss(t, y_treat_te) +
                        loss_weights['cure'] * mse_loss(c, y_cure_te) +
                        loss_weights['surv5'] * mse_loss(s5, y_s5_te) +
                        loss_weights['surv10'] * mse_loss(s10, y_s10_te)).item()

        history['loss'].append(avg_train_loss)
        history['val_loss'].append(val_loss)
        scheduler.step(val_loss)

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1:3d}/{epochs} — train_loss: {avg_train_loss:.4f} — val_loss: {val_loss:.4f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= 15:
                print(f"  ⏹  EarlyStopping en epoch {epoch+1}")
                break

    if best_state:
        model.load_state_dict(best_state)
    model.eval()
    return history


# ============================================================================
# 4. EVALUACIÓN
# ============================================================================
def evaluate_model(model, X_test, targets_test, artifacts):
    model.eval()
    model.to(DEVICE)
    X_te = torch.tensor(X_test, dtype=torch.float32).to(DEVICE)

    with torch.no_grad():
        r, t, c, s5, s10 = model(X_te)
        risk_probs = torch.softmax(r, dim=1).cpu().numpy()
        risk_pred = np.argmax(risk_probs, axis=1)
        treat_pred = np.argmax(torch.softmax(t, dim=1).cpu().numpy(), axis=1)
        cure_pred = c.cpu().numpy()
        surv5_pred = s5.cpu().numpy()
        surv10_pred = s10.cpu().numpy()

    y_risk = targets_test['risk_output']
    y_treat = targets_test['treatment_output']
    y_cure = targets_test['cure_rate_output']
    y_s5 = targets_test['survival_5y_output']
    y_s10 = targets_test['survival_10y_output']

    report = {}
    risk_names = [f"Riesgo_{c}" for c in artifacts['risk_encoder'].classes_]
    print("\n" + "=" * 60)
    print("📊 EVALUACIÓN: NIVEL DE RIESGO")
    print("=" * 60)
    print(classification_report(y_risk, risk_pred, target_names=risk_names))
    report['risk_accuracy'] = float(np.mean(risk_pred == y_risk))

    try:
        auc = roc_auc_score(y_risk, risk_probs, multi_class='ovr', average='weighted')
        report['risk_auc_roc'] = float(auc)
        print(f"  AUC-ROC (weighted): {auc:.4f}")
    except Exception:
        report['risk_auc_roc'] = None

    treat_names = [str(c) for c in artifacts['treatment_encoder'].classes_]
    print("\n💊 EVALUACIÓN: TRATAMIENTO")
    print(classification_report(y_treat, treat_pred, target_names=treat_names, zero_division=0))
    report['treatment_accuracy'] = float(np.mean(treat_pred == y_treat))

    report['cure_rate_mae'] = float(mean_absolute_error(y_cure, cure_pred))
    report['survival_5y_mae'] = float(mean_absolute_error(y_s5, surv5_pred))
    report['survival_10y_mae'] = float(mean_absolute_error(y_s10, surv10_pred))
    violations = int(np.sum(surv10_pred > surv5_pred))
    report['survival_constraint_violations'] = violations

    print(f"\n📈 Cure MAE: {report['cure_rate_mae']:.4f}")
    print(f"📈 Surv5 MAE: {report['survival_5y_mae']:.4f}")
    print(f"📈 Surv10 MAE: {report['survival_10y_mae']:.4f}")
    print(f"⚕️  Constraint violations: {violations}/{len(surv5_pred)}")
    return report


# ============================================================================
# 5. PREDICCIÓN
# ============================================================================
def predict_patient(model, artifacts, patient_data: dict) -> dict:
    df = pd.DataFrame([patient_data])
    if 'psad' not in df.columns or pd.isna(df['psad'].iloc[0]):
        df['psad'] = df['psa'] / patient_data.get('volumen_prostatico', 40)
    df['psa_log'] = np.log1p(df['psa'])

    encoded = artifacts['encoder'].transform(df[artifacts['cat_cols']].astype(str))
    scaled = artifacts['scaler'].transform(df[artifacts['num_cols']])
    X = np.concatenate([scaled, encoded], axis=1)

    model.eval()
    model.to(DEVICE)
    with torch.no_grad():
        x_t = torch.tensor(X, dtype=torch.float32).to(DEVICE)
        r, t, c, s5, s10 = model(x_t)
        risk_probs = torch.softmax(r, dim=1).cpu().numpy()[0]
        treat_probs = torch.softmax(t, dim=1).cpu().numpy()[0]
        cure = float(c.cpu().numpy()[0])
        surv5 = float(s5.cpu().numpy()[0])
        surv10 = min(float(s10.cpu().numpy()[0]), surv5)

    risk_classes = artifacts['risk_encoder'].classes_
    treat_classes = artifacts['treatment_encoder'].classes_
    risk_labels = {0: "BAJO", 1: "INTERMEDIO", 2: "ALTO"}

    return {
        "riesgo": {
            "nivel": risk_labels.get(risk_classes[np.argmax(risk_probs)], "?"),
            "probabilidades": {risk_labels.get(int(c), str(c)): f"{p:.1%}" for c, p in zip(risk_classes, risk_probs)}
        },
        "tratamiento_recomendado": {
            "principal": str(treat_classes[np.argmax(treat_probs)]),
            "probabilidades": {str(c): f"{p:.1%}" for c, p in zip(treat_classes, treat_probs)}
        },
        "tasa_curacion": f"{cure:.1%}",
        "supervivencia_5_anios": f"{surv5:.1%}",
        "supervivencia_10_anios": f"{surv10:.1%}",
    }


# ============================================================================
# 6. PERSISTENCIA
# ============================================================================
def save_all(model, artifacts, report, output_dir=None):
    out = output_dir or OUTPUT_DIR
    torch.save(model.state_dict(), os.path.join(out, "model_weights.pt"))
    meta = {'input_dim': model.shared[0].in_features,
            'n_risk': model.risk_head.out_features,
            'n_treatment': model.treatment_head.out_features}
    joblib.dump({'artifacts': artifacts, 'model_meta': meta}, os.path.join(out, "artifacts.pkl"))
    with open(os.path.join(out, "evaluation_report.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"✅ Modelo y artefactos guardados en {out}")


def load_all(output_dir=None):
    out = output_dir or OUTPUT_DIR
    data = joblib.load(os.path.join(out, "artifacts.pkl"))
    meta = data['model_meta']
    model = ProstateCancerNet(meta['input_dim'], meta['n_risk'], meta['n_treatment'])
    model.load_state_dict(torch.load(os.path.join(out, "model_weights.pt"), weights_only=True))
    model.eval()
    return model, data['artifacts']
