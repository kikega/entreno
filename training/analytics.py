import math
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Avg, F
from typing import Dict, Any, Optional

def calculate_1rm_brzycki(weight_kg: float, reps: int) -> float:
    """
    Calcula la estimación de 1RM mediante la fórmula de Brzycki.
    """
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    if reps == 1:
        return round(float(weight_kg), 2)
    # Brzycki formula: weight / (1.0278 - 0.0278 * reps)
    denom = 1.0278 - (0.0278 * reps)
    if denom <= 0:
        return round(float(weight_kg * 1.5), 2)
    return round(float(weight_kg) / denom, 2)


def calculate_srpe(duration_minutes: float, rpe: float) -> float:
    """
    Calcula la Carga Interna (sRPE = Duración en min * RPE).
    """
    if not duration_minutes or not rpe:
        return 0.0
    return round(float(duration_minutes) * float(rpe), 2)


# Categorías y patrones de movimiento con carga ponderada (aplican cálculos de 1RM / %carga relativa).
RM_BASED_CATEGORIES = {'fuerza', 'potencia', 'velocidad'}
RM_BASED_PATTERNS = {
    'empuje_horizontal', 'empuje_vertical', 'traccion_horizontal',
    'traccion_vertical', 'dominante_cadera', 'dominante_rodilla',
    'potencia_olimpica', 'isometria_agarre',
}


def is_rm_based_exercise(planned_exercise) -> bool:
    """
    Determina si un ejercicio (PlannedExercise) usa cargas con RM calculable.
    Se basa en la categoría y el patrón de movimiento del ejercicio base.
    """
    exercise = planned_exercise.exercise
    if exercise.category in RM_BASED_CATEGORIES:
        return True
    return exercise.movement_pattern in RM_BASED_PATTERNS


def estimate_1rm(weight_kg, reps) -> float:
    """Estima el 1RM de una serie vía Brzycki."""
    weight = float(weight_kg) if weight_kg is not None else 0.0
    reps_i = int(reps or 0)
    if weight <= 0 or reps_i <= 0:
        return 0.0
    return calculate_1rm_brzycki(weight, reps_i)


def pct_of_1rm(weight_kg, est_1rm) -> float:
    """Devuelve el % de la carga respecto al 1RM, redondeado a 1 decimal."""
    weight = float(weight_kg) if weight_kg is not None else 0.0
    if est_1rm and est_1rm > 0:
        return round((weight / est_1rm) * 100, 1)
    return 0.0


def exercise_1rm_evolution(athlete_profile, exclude_logged=None) -> Dict[str, list]:
    """
    Devuelve la evolución del mejor 1RM estimado por ejercicio a lo largo del tiempo.
    Formato: { 'nombre_ejercicio': [ {'date': '2026-01-01', '1rm': 120.0}, ... ] }
    Ordenado cronológicamente usando el mejor 1RM de cada ejercicio en cada sesión.
    """
    from training.models import LoggedSet

    qs = LoggedSet.objects.filter(
        logged_exercise__workout_session__athlete=athlete_profile
    )
    if exclude_logged:
        qs = qs.exclude(logged_exercise=exclude_logged)
    qs = qs.select_related(
        'logged_exercise__workout_session',
        'logged_exercise__planned_exercise__exercise',
    ).order_by('logged_exercise__workout_session__date_completed', 'set_number')

    # Acumular mejor 1RM por (ejercicio, sesión)
    best_by_key: Dict[tuple, dict] = {}
    for s in qs:
        planned = s.logged_exercise.planned_exercise
        if not is_rm_based_exercise(planned):
            continue
        est = estimate_1rm(s.weight_kg, s.reps)
        if est <= 0:
            continue
        session = s.logged_exercise.workout_session
        key = (planned.exercise.name, session.pk)
        meta = best_by_key.setdefault(key, {
            'date': session.date_completed.strftime('%Y-%m-%d'),
            'best': 0.0,
        })
        if est > meta['best']:
            meta['best'] = est

    # Agrupar por nombre en orden cronológico
    evolution: Dict[str, list] = {}
    for (name, _session_pk), meta in best_by_key.items():
        evolution.setdefault(name, []).append({'date': meta['date'], '1rm': round(meta['best'], 1)})
    for name in evolution:
        evolution[name].sort(key=lambda p: p['date'])
    return evolution


def calculate_acwr(athlete_profile, target_date=None) -> Dict[str, Any]:
    """
    Calcula la Relación Carga Aguda:Crónica (ACWR) para el deportista.
    - Carga Aguda: Suma de sRPE en los últimos 7 días.
    - Carga Crónica: Promedio semanal de sRPE en los últimos 28 días.
    - Ratio ACWR = Carga Aguda / Carga Crónica.
    - Zonas de Riesgo:
        - < 0.8: Carga baja (Riesgo de desacondicionamiento)
        - 0.8 - 1.3: Zona Óptima ("Sweet Spot")
        - 1.31 - 1.49: Carga Elevada
        - >= 1.5: Zona de Alto Riesgo de Lesión ("Danger Zone")
    """
    if target_date is None:
        target_date = timezone.now().date()

    from training.models import WorkoutSession

    date_7d_ago = target_date - timedelta(days=7)
    date_28d_ago = target_date - timedelta(days=28)

    sessions_7d = WorkoutSession.objects.filter(
        athlete=athlete_profile,
        date_completed__date__gte=date_7d_ago,
        date_completed__date__lte=target_date
    )

    sessions_28d = WorkoutSession.objects.filter(
        athlete=athlete_profile,
        date_completed__date__gte=date_28d_ago,
        date_completed__date__lte=target_date
    )

    acute_load = 0.0
    for s in sessions_7d:
        duration = s.duration_minutes or 45
        rpe = s.session_rpe or 7.0
        acute_load += calculate_srpe(duration, rpe)

    chronic_total = 0.0
    for s in sessions_28d:
        duration = s.duration_minutes or 45
        rpe = s.session_rpe or 7.0
        chronic_total += calculate_srpe(duration, rpe)

    # Promedio semanal en 28 días (4 semanas)
    chronic_load = chronic_total / 4.0 if chronic_total > 0 else 1.0

    acwr_ratio = round(acute_load / chronic_load, 2) if chronic_load > 0 else 1.0

    if acwr_ratio < 0.8:
        risk_status = 'bajo'
        status_label = 'Subentrenamiento (Desacondicionamiento)'
        status_color = 'amber'
    elif 0.8 <= acwr_ratio <= 1.3:
        risk_status = 'optimo'
        status_label = 'Zona Óptima de Carga (Sweet Spot)'
        status_color = 'emerald'
    elif 1.3 < acwr_ratio < 1.5:
        risk_status = 'elevado'
        status_label = 'Carga Elevada (Precaución)'
        status_color = 'orange'
    else:
        risk_status = 'alto'
        status_label = 'Alto Riesgo de Lesión (> 1.5 ACWR)'
        status_color = 'rose'

    return {
        'acute_load': round(acute_load, 1),
        'chronic_load': round(chronic_load, 1),
        'acwr_ratio': acwr_ratio,
        'risk_status': risk_status,
        'status_label': status_label,
        'status_color': status_color,
    }


def get_athlete_sport_metrics(athlete_profile) -> Dict[str, Any]:
    """
    Recopila métricas globales del deportista para el dashboard del entrenador y el deportista.
    """
    from training.models import LoggedSet, WorkoutSession

    acwr_data = calculate_acwr(athlete_profile)
    completed_sessions = WorkoutSession.objects.filter(athlete=athlete_profile).count()

    # Cálculo de Volumen Total acumulado (series * reps * weight)
    sets = LoggedSet.objects.filter(logged_exercise__workout_session__athlete=athlete_profile)
    total_volume_kg = 0.0
    max_1rm_records = {}

    for s in sets:
        vol = float(s.weight_kg) * s.reps
        total_volume_kg += vol
        e_name = s.logged_exercise.planned_exercise.exercise.name
        est_1rm = calculate_1rm_brzycki(float(s.weight_kg), s.reps)
        if e_name not in max_1rm_records or est_1rm > max_1rm_records[e_name]:
            max_1rm_records[e_name] = est_1rm

    return {
        'acwr': acwr_data,
        'completed_sessions': completed_sessions,
        'total_volume_kg': round(total_volume_kg, 1),
        'max_1rm_records': max_1rm_records,
        'sport': athlete_profile.get_sport_display(),
        'experience_level': athlete_profile.get_experience_level_display(),
        'training_goal': athlete_profile.get_training_goal_display(),
    }
