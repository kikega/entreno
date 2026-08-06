"""
Predicción de la próxima carga de un ejercicio.

Flujo:
1. Si existe un modelo entrenado y el deportista tiene historial suficiente,
   se usa la predicción del modelo de ML (fuente 'modelo').
2. En caso contrario (cold start) se cae a una progresión determinista basada
   en reglas deportivas (ACWR + RPE), que también actúa como guía de seguridad.

La decisión final de la planificación siempre la toma el entrenador: el
resultado es una sugerencia revisable.
"""
from datetime import timedelta
from functools import lru_cache
from typing import Dict, List, Optional

import joblib
import numpy as np

from django.utils import timezone

from training.analytics import calculate_1rm_brzycki, calculate_acwr
from training.models import LoggedSet, WorkoutSession

from .build_dataset import (
    MIN_SAMPLES_FOR_TRAINING,
    encode_row,
    feature_columns,
)
from .model import MODEL_PATH

# Margen máximo de ajuste respecto al último peso registrado para que el modelo
# no produzca sugerencias irreales cuando generaliza mal (zona de seguridad).
MAX_ADJUSTMENT = 0.15


def _days_since_last_session(athlete_profile) -> int:
    last_session = (
        WorkoutSession.objects
        .filter(athlete=athlete_profile)
        .order_by('-date_completed')
        .first()
    )
    if last_session is None:
        return 0
    return max(0, (timezone.now() - last_session.date_completed).days)


def build_prediction_features(athlete_profile, exercise, previous_logs: List[LoggedSet]) -> Dict:
    """Construye las características del estado actual del deportista+ejercicio
    para predecir la siguiente serie."""
    athlete_weight = float(athlete_profile.weight or 0.0)
    athlete_height = float(athlete_profile.height or 0.0)

    window = previous_logs[-5:] if previous_logs else []
    last = window[-1] if window else None

    if last is None:
        last_weight = 0.0
        last_reps = 0
        last_rpe = 0.0
        last_1rm = 0.0
        est_1rm_trend = 0.0
        next_set_number = 1
        days_since_last_exercise = 0
    else:
        last_weight = float(last.weight_kg)
        last_reps = int(last.reps or 0)
        last_rpe = float(last.rpe or 0.0)
        last_1rm = calculate_1rm_brzycki(last_weight, last_reps)
        first_1rm = calculate_1rm_brzycki(
            float(window[0].weight_kg), int(window[0].reps or 0)
        )
        est_1rm_trend = last_1rm - first_1rm
        next_set_number = int(last.set_number or 1) + 1
        days_since_last_exercise = max(
            0, (timezone.now() - last.completed_at).days
        )

    acwr = calculate_acwr(athlete_profile)

    return {
        'athlete_weight_kg': athlete_weight,
        'athlete_height_cm': athlete_height,
        'last_weight_kg': last_weight,
        'last_reps': last_reps,
        'last_rpe': last_rpe,
        'last_est_1rm': last_1rm,
        'est_1rm_trend': est_1rm_trend,
        'set_number': next_set_number,
        'days_since_last_exercise': days_since_last_exercise,
        'days_since_last_session': _days_since_last_session(athlete_profile),
        'acwr_ratio': float(acwr['acwr_ratio']),
        'acute_load_7d': float(acwr['acute_load']),
        'chronic_load_28d': float(acwr['chronic_load']),
        'sessions_last_14d': WorkoutSession.objects.filter(
            athlete=athlete_profile,
            date_completed__gte=timezone.now() - timedelta(days=14),
        ).count(),
        'experience_level': athlete_profile.experience_level,
        'sport': athlete_profile.sport,
        'training_goal': athlete_profile.training_goal,
        'category': exercise.category,
        'movement_pattern': exercise.movement_pattern,
    }


@lru_cache(maxsize=1)
def _load_model(model_path=MODEL_PATH):
    """Carga el modelo persistido (con caché). Devuelve None si no existe."""
    try:
        return joblib.load(model_path)
    except FileNotFoundError:
        return None


def is_model_available(model_path=MODEL_PATH) -> bool:
    return _load_model(model_path) is not None


def predict_with_model(features: Dict, model_path=MODEL_PATH) -> Optional[float]:
    """Predice la siguiente carga (kg) con el modelo entrenado. Devuelve None
    si no hay modelo disponible."""
    data = _load_model(model_path)
    if data is None:
        return None
    X = np.array([encode_row(features)], dtype=np.float64)
    return float(data['model'].predict(X)[0])


def _clamp_prediction(raw: float, last_weight: float) -> float:
    """Limita la predicción a un margen razonable respecto al último peso real."""
    if last_weight <= 0:
        return raw if raw > 0 else 0.0
    return max(
        round(last_weight * (1 - MAX_ADJUSTMENT), 1),
        min(round(last_weight * (1 + MAX_ADJUSTMENT), 1), round(raw, 1)),
    )


def _rule_based_prediction(athlete_profile, previous_logs: List[LoggedSet]) -> Dict:
    """Progresión determinista basada en zonas de ACWR y RPE (guía de seguridad)."""
    acwr_ratio = calculate_acwr(athlete_profile)['acwr_ratio']

    if not previous_logs:
        return {
            'suggested_weight_kg': 0.0,
            'suggested_reps': 8,
            'suggested_rpe': 7.5,
            'estimated_1rm': 0.0,
            'recommendation_note': 'Carga base inicial. Evaluar en la primera serie.',
            'source': 'reglas',
        }

    recent_set = previous_logs[-1]
    last_weight = float(recent_set.weight_kg)
    last_reps = recent_set.reps
    last_rpe = float(recent_set.rpe or 8.0)
    est_1rm = calculate_1rm_brzycki(last_weight, last_reps)

    if acwr_ratio > 1.4:
        factor = 0.92
        note = (f'⚠️ Carga Aguda Elevada (ACWR {acwr_ratio}). '
                'Se sugiere descarga del 8% por seguridad.')
        suggested_rpe = 7.0
    elif acwr_ratio < 0.8:
        factor = 1.04
        note = (f'📈 Atleta recuperado (ACWR {acwr_ratio}). '
                'Progresión sugerida +4%.')
        suggested_rpe = 8.0
    else:
        if last_rpe < 7.5:
            factor = 1.05
            note = '🔥 RPE previo holgado (< 7.5). Incremento de carga +5%.'
            suggested_rpe = 8.0
        elif last_rpe > 9.0:
            factor = 1.00
            note = '🎯 RPE previo exigente (>= 9.0). Mantener peso y afianzar repeticiones.'
            suggested_rpe = 8.5
        else:
            factor = 1.025
            note = '✅ Progresión lineal estándar +2.5%.'
            suggested_rpe = 8.0

    return {
        'suggested_weight_kg': round(last_weight * factor, 1),
        'suggested_reps': last_reps,
        'suggested_rpe': suggested_rpe,
        'estimated_1rm': est_1rm,
        'recommendation_note': note,
        'source': 'reglas',
    }


def predict_next_load(athlete_profile, exercise, previous_logs: List[LoggedSet]) -> Dict:
    """
    Sugiere la carga óptima para la siguiente sesión de un ejercicio concreto.

    Usa el modelo de ML entrenado cuando está disponible; en caso contrario,
    cae a la progresión por reglas (cold start). El resultado es una sugerencia
    que el entrenador debe revisar y ajustar.
    """
    features = build_prediction_features(athlete_profile, exercise, previous_logs)
    raw_prediction = predict_with_model(features)

    if raw_prediction is not None and raw_prediction > 0:
        last_weight = features['last_weight_kg']
        suggested_weight = _clamp_prediction(raw_prediction, last_weight)
        last_reps = features['last_reps']

        if last_reps > 0:
            suggested_reps = last_reps
        else:
            suggested_reps = 8

        acwr_ratio = features['acwr_ratio']
        if acwr_ratio > 1.4:
            suggested_rpe = 7.0
        elif acwr_ratio < 0.8:
            suggested_rpe = 8.0
        else:
            suggested_rpe = 8.0

        return {
            'suggested_weight_kg': suggested_weight,
            'suggested_reps': suggested_reps,
            'suggested_rpe': suggested_rpe,
            'estimated_1rm': calculate_1rm_brzycki(suggested_weight, suggested_reps),
            'recommendation_note': (
                '🤖 Predicción del modelo ML basada en tu historial '
                'de series y contexto de carga.'
            ),
            'source': 'modelo',
        }

    return _rule_based_prediction(athlete_profile, previous_logs)
