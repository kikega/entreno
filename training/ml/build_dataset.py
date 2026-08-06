"""
Feature engineering y construcción del dataset supervisado para el predictor
de carga de los planes de entrenamiento.

Cada muestra se construye a partir del contexto del deportista y del ejercicio
justo ANTES de una serie registrada (LoggedSet), y su etiqueta (target) es el
peso real (kg) ejecutado en esa serie. De este modo el modelo aprende a sugerir
la siguiente carga del microciclo.
"""
from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from training.analytics import calculate_1rm_brzycki, calculate_acwr
from training.models import LoggedSet, WorkoutSession

# Número de series previas usadas para las características de tendencia.
WINDOW_SIZE = 5

# Número mínimo de muestras necesario para entrenar el modelo.
MIN_SAMPLES_FOR_TRAINING = 30

CATEGORICAL_FEATURES = [
    'experience_level',
    'sport',
    'training_goal',
    'category',
    'movement_pattern',
]

# Valores ordenados de cada variable categórica. El orden es fijo para que las
# columnas one-hot de entrenamiento y predicción siempre coincidan.
CATEGORY_VALUES = {
    'experience_level': ['principiante', 'intermedio', 'avanzado', 'elite'],
    'sport': ['mma', 'karate', 'bjj', 'crossfit', 'hyrox', 'weight_loss', 'otro'],
    'training_goal': [
        'fuerza_maxima', 'potencia_explosiva', 'resistencia_muscular',
        'hipertrofia', 'perdida_grasa', 'acondicionamiento_combate',
    ],
    'category': [
        'fuerza', 'potencia', 'movilidad', 'velocidad', 'pliometria',
        'tecnica', 'tactica', 'otro',
    ],
    'movement_pattern': [
        'empuje_horizontal', 'empuje_vertical', 'traccion_horizontal',
        'traccion_vertical', 'dominante_cadera', 'dominante_rodilla',
        'potencia_olimpica', 'metabolico', 'isometria_agarre',
        'core_rotacional', 'otro',
    ],
}

NUMERIC_FEATURES = [
    'athlete_weight_kg',
    'athlete_height_cm',
    'last_weight_kg',
    'last_reps',
    'last_rpe',
    'last_est_1rm',
    'est_1rm_trend',
    'set_number',
    'days_since_last_exercise',
    'days_since_last_session',
    'acwr_ratio',
    'acute_load_7d',
    'chronic_load_28d',
    'sessions_last_14d',
]


def feature_columns() -> List[str]:
    """Devuelve la lista completa y ordenada de columnas del vector de entrada."""
    cols = list(NUMERIC_FEATURES)
    for feat in CATEGORICAL_FEATURES:
        cols.extend(f'{feat}__{cat}' for cat in CATEGORY_VALUES[feat])
    return cols


def encode_row(features: Dict) -> List[float]:
    """Convierte un dict de características (categóricas como strings) en un
    vector numérico de longitud fija apto para el modelo."""
    row = []
    for name in NUMERIC_FEATURES:
        row.append(float(features.get(name, 0.0) or 0.0))
    for feat in CATEGORICAL_FEATURES:
        value = features.get(feat, '') or ''
        for cat in CATEGORY_VALUES[feat]:
            row.append(1.0 if value == cat else 0.0)
    return row


def athlete_context(athlete_profile) -> Dict:
    """Contexto global reciente del deportista (cargas y sesiones)."""
    acwr = calculate_acwr(athlete_profile)
    now = timezone.now().date()
    date_14d_ago = now - timedelta(days=14)

    sessions_14d = list(WorkoutSession.objects.filter(
        athlete=athlete_profile,
        date_completed__date__gte=date_14d_ago,
        date_completed__date__lte=now,
    ))

    return {
        'acwr_ratio': float(acwr['acwr_ratio']),
        'acute_load_7d': float(acwr['acute_load']),
        'chronic_load_28d': float(acwr['chronic_load']),
        'sessions_last_14d': len(sessions_14d),
    }


def _days_since(session_dates: List, current: object) -> int:
    """Días transcurridos desde la sesión anterior a `current`."""
    idx = bisect_left(session_dates, current)
    if idx <= 0:
        return 0
    delta = (current - session_dates[idx - 1]).total_seconds() / 86400.0
    return int(round(delta))


def build_row(
    current_set,
    window: List[LoggedSet],
    athlete_profile,
    exercise,
    ctx: Dict,
    session_dates: List,
) -> Dict:
    """Características que describen el estado del deportista+ejercicio ANTES de
    la serie actual."""
    current_session_date = current_set.logged_exercise.workout_session.date_completed
    last = window[-1] if window else None

    if last is None:
        last_weight = 0.0
        last_reps = 0
        last_rpe = 0.0
        last_1rm = 0.0
        est_1rm_trend = 0.0
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
        days_since_last_exercise = _days_since(
            session_dates, current_session_date
        )

    return {
        'athlete_weight_kg': float(athlete_profile.weight or 0.0),
        'athlete_height_cm': float(athlete_profile.height or 0.0),
        'last_weight_kg': last_weight,
        'last_reps': last_reps,
        'last_rpe': last_rpe,
        'last_est_1rm': last_1rm,
        'est_1rm_trend': est_1rm_trend,
        'set_number': int(current_set.set_number or 1),
        'days_since_last_exercise': days_since_last_exercise,
        'days_since_last_session': _days_since(session_dates, current_session_date),
        'acwr_ratio': ctx['acwr_ratio'],
        'acute_load_7d': ctx['acute_load_7d'],
        'chronic_load_28d': ctx['chronic_load_28d'],
        'sessions_last_14d': ctx['sessions_last_14d'],
        'experience_level': athlete_profile.experience_level,
        'sport': athlete_profile.sport,
        'training_goal': athlete_profile.training_goal,
        'category': exercise.category,
        'movement_pattern': exercise.movement_pattern,
    }


def build_supervised_dataset() -> Tuple[List[Dict], List[float]]:
    """
    Construye el dataset supervisado: para cada serie registrada con peso > 0,
    genera una muestra con las características del contexto previo y como
    etiqueta el peso real ejecutado en esa serie.
    """
    rows: List[Dict] = []
    targets: List[float] = []

    sets_qs = (
        LoggedSet.objects
        .filter(weight_kg__gt=0)
        .select_related(
            'logged_exercise__workout_session',
            'logged_exercise__workout_session__athlete',
            'logged_exercise__planned_exercise__exercise',
        )
        .order_by('completed_at')
    )

    by_athlete: Dict = defaultdict(list)
    for s in sets_qs.iterator():
        by_athlete[s.logged_exercise.workout_session.athlete_id].append(s)

    for athlete_id, athlete_sets in by_athlete.items():
        athlete = athlete_sets[0].logged_exercise.workout_session.athlete
        ctx = athlete_context(athlete)
        session_dates = sorted({
            s.logged_exercise.workout_session.date_completed for s in athlete_sets
        })

        by_exercise: Dict = defaultdict(list)
        for s in athlete_sets:
            by_exercise[s.logged_exercise.planned_exercise.exercise_id].append(s)

        for ex_sets in by_exercise.values():
            exercise = ex_sets[0].logged_exercise.planned_exercise.exercise
            for i, s in enumerate(ex_sets):
                window = ex_sets[max(0, i - WINDOW_SIZE):i]
                row = build_row(s, window, athlete, exercise, ctx, session_dates)
                target = float(s.weight_kg)
                if target <= 0:
                    continue
                rows.append(row)
                targets.append(target)

    return rows, targets
