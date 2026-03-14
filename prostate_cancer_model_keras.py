import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Dense, Input, Dropout, BatchNormalization
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.preprocessing import OneHotEncoder, StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split

# 1️⃣ **Generación de datos sintéticos**
def generate_synthetic_data(num_samples=1000):
    np.random.seed(42)  # Fijamos la semilla para reproducibilidad

    age = np.random.randint(50, 80, num_samples)
    psa = np.random.exponential(5, num_samples)  # Valores positivos
    ecog = np.random.randint(0, 3, num_samples)
    stage = np.random.randint(1, 4, num_samples)
    gleason = np.random.randint(6, 10, num_samples)
    treatment = np.random.choice(['hormonal', 'chemo', 'radio', 'surgery', 'watch'], num_samples)
    cci = np.random.randint(0, 5, num_samples)  # Comorbidity Index
    psad = np.random.uniform(0, 50, num_samples)  # PSA Density

    df = pd.DataFrame({
        'age': age, 'psa': psa, 'ecog': ecog, 'stage': stage,
        'gleason': gleason, 'treatment': treatment, 'cci': cci, 'psad': psad
    })

    # Variables objetivo (etiquetas)
    df['risk'] = np.random.randint(0, 3, num_samples)  # Riesgo (bajo, medio, alto)
    df['cure_rate'] = np.random.rand(num_samples)  # Tasa de curación (0-1)
    df['survival_5y'] = np.random.rand(num_samples)  # Supervivencia a 5 años (0-1)
    df['survival_10y'] = np.random.rand(num_samples)  # Supervivencia a 10 años (0-1)

    return df

# 2️⃣ **Preprocesamiento de datos**
def preprocess_data(df):
    df['psa'] = np.log1p(df['psa'])  # Aplicar transformación logarítmica

    encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)  
    encoded_features = encoder.fit_transform(df[['stage', 'gleason', 'treatment']])

    scaler = StandardScaler()
    numerical_features = ['age', 'psa', 'ecog', 'cci', 'psad']  
    scaled_features = scaler.fit_transform(df[numerical_features])

    X = np.concatenate([scaled_features, encoded_features], axis=1)

    label_encoder = LabelEncoder()
    y_risk = label_encoder.fit_transform(df['risk'])
    y_cure_rate = df['cure_rate'].values
    y_survival_5y = df['survival_5y'].values
    y_survival_10y = df['survival_10y'].values

    return X, y_risk, y_cure_rate, y_survival_5y, y_survival_10y, encoder, label_encoder

# 3️⃣ **Entrenamiento del modelo**
def build_and_train_model(X_train, y_risk_train, y_cure_rate_train, y_survival_5y_train, y_survival_10y_train, 
                          X_test, y_risk_test, y_cure_rate_test, y_survival_5y_test, y_survival_10y_test, 
                          epochs=50, batch_size=32):

    input_layer = Input(shape=(X_train.shape[1],), name="input_features")

    x = Dense(128, activation='relu')(input_layer)
    x = BatchNormalization()(x)
    x = Dropout(0.3)(x)

    x = Dense(256, activation='relu')(x)
    x = BatchNormalization()(x)
    x = Dropout(0.3)(x)

    x = Dense(128, activation='relu')(x)
    x = BatchNormalization()(x)
    x = Dropout(0.3)(x)

    # CORRECTION: The target variable passed is 'y_risk' which has 3 classes (0, 1, 2).
    # The original code named this 'treatment_output' with 5 units, which matches the number of treatments,
    # but 'treatment' is an input feature, not an output target in this code. 
    # The variable y_risk is passed to this output, so we rename it to 'risk_output' and size it correctly to 3.
    risk_output = Dense(3, activation='softmax', name="risk_output")(x)
    
    cure_rate_output = Dense(1, activation='sigmoid', name="cure_rate_output")(x)
    survival_5y_output = Dense(1, activation='sigmoid', name="survival_5y_output")(x)
    survival_10y_output = Dense(1, activation='sigmoid', name="survival_10y_output")(x)

    model = Model(inputs=input_layer, outputs=[risk_output, cure_rate_output, survival_5y_output, survival_10y_output])

    model.compile(optimizer='adam',
                  loss={'risk_output': 'sparse_categorical_crossentropy',
                        'cure_rate_output': 'mse',
                        'survival_5y_output': 'mse',
                        'survival_10y_output': 'mse'},
                  metrics={'risk_output': 'accuracy',
                           'cure_rate_output': 'mae',
                           'survival_5y_output': 'mae',
                           'survival_10y_output': 'mae'})

    early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)

    history = model.fit(
        X_train, {'risk_output': y_risk_train, 'cure_rate_output': y_cure_rate_train,
                  'survival_5y_output': y_survival_5y_train, 'survival_10y_output': y_survival_10y_train},
        validation_data=(X_test, {'risk_output': y_risk_test, 'cure_rate_output': y_cure_rate_test,
                                  'survival_5y_output': y_survival_5y_test, 'survival_10y_output': y_survival_10y_test}),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=[early_stopping],
        verbose=1
    )

    return model, history

if __name__ == "__main__":
    # 4️⃣ **Ejecutar el proceso de entrenamiento**
    print("Generando datos sintéticos...")
    df = generate_synthetic_data()
    print("Preprocesando datos...")
    X, y_risk, y_cure_rate, y_survival_5y, y_survival_10y, encoder, label_encoder = preprocess_data(df)

    X_train, X_test, y_risk_train, y_risk_test, y_cure_rate_train, y_cure_rate_test, y_survival_5y_train, y_survival_5y_test, y_survival_10y_train, y_survival_10y_test = train_test_split(
        X, y_risk, y_cure_rate, y_survival_5y, y_survival_10y, test_size=0.2, random_state=42
    )

    print("Entrenando el modelo...")
    # **Entrenar el modelo y generar la variable `history`**
    model, history = build_and_train_model(
        X_train, y_risk_train, y_cure_rate_train, y_survival_5y_train, y_survival_10y_train, 
        X_test, y_risk_test, y_cure_rate_test, y_survival_5y_test, y_survival_10y_test
    )
    print("Entrenamiento completado.")
    
    # Save model
    model.save("prostate_cancer_keras_model.h5")
    print("Modelo guardado en prostate_cancer_keras_model.h5")
