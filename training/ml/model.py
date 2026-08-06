"""
Entrenamiento del modelo de regresión para la progresión de carga.

El modelo predice el siguiente peso sugerido (kg) a partir de las características
del deportista, del ejercicio y de su historial reciente.
"""
from pathlib import Path

import joblib
import numpy as np
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from .build_dataset import encode_row, feature_columns

MODEL_PATH = Path(__file__).resolve().parent / 'model.joblib'


def train_model(rows: list, targets: list, model_path=None):
    """
    Entrena un LGBMRegressor con las muestras y etiquetas proporcionadas,
    evalúa la generalización con una partición de validación y guarda el
    modelo junto con las columnas del dataset en `model_path`.
    """
    X = np.array([encode_row(r) for r in rows], dtype=np.float64)
    y = np.array(targets, dtype=np.float64)

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        random_state=42,
        verbose=-1,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_train_pred = model.predict(X_train)
    y_val_pred = model.predict(X_val)

    metrics = {
        'n_samples': int(len(y)),
        'train_mae': float(mean_absolute_error(y_train, y_train_pred)),
        'val_mae': float(mean_absolute_error(y_val, y_val_pred)),
        'train_r2': float(r2_score(y_train, y_train_pred)),
        'val_r2': float(r2_score(y_val, y_val_pred)),
    }

    output_path = Path(model_path) if model_path else MODEL_PATH
    joblib.dump({'model': model, 'columns': feature_columns()}, output_path)

    return model, metrics
