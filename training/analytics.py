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
    """Estima el 1RM de una serie vía Brzycki con conversión segura de tipos."""
    try:
        weight = float(weight_kg) if weight_kg is not None else 0.0
    except (ValueError, TypeError):
        weight = 0.0
    try:
        reps_i = int(reps or 0)
    except (ValueError, TypeError):
        reps_i = 0
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
    # select_related evita el problema de N+1 queries al iterar por cientos de series
    sets = (
        LoggedSet.objects
        .filter(logged_exercise__workout_session__athlete=athlete_profile)
        .select_related('logged_exercise__planned_exercise__exercise')
    )
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


def build_am_historical_ledger(
    athlete_profile,
    block_id: Optional[int] = None,
    session_block: Optional[str] = None,
    pain_filter: Optional[str] = None,
    limit: Optional[int] = 200,
) -> list[Dict[str, Any]]:
    """
    Construye el `Registro_Historico` estructurado del Sistema AM (§4.4):
    Cada fila representa una serie real registrada (`LoggedSet`) o un ejercicio omitido
    por lesión (`pain_status='omitted_injury'`), incluyendo:
      - Fecha, Bloque del Macrociclo, Semana, Día, Bloque Concurrente (B1..B5)
      - Ejercicio Prescrito vs Ejercicio Ejecutado (Opción A / Opción B / Omitido)
      - Nivel del Semáforo de Disposición Diaria (1 a 5) y Esquema activo
      - Serie #, Peso (kg), Repeticiones, RPE Real, Tonelaje (kg), 1RM Brzycki (kg) y sRPE de sesión.
    """
    from training.models import LoggedExercise

    logged_qs = (
        LoggedExercise.objects
        .filter(workout_session__athlete=athlete_profile)
        .select_related(
            'workout_session__workout_plan__macrocycle_block',
            'planned_exercise__exercise',
            'substituted_exercise',
        )
        .prefetch_related('sets')
        .order_by('-workout_session__date_completed', 'planned_exercise__order', 'id')
    )

    if block_id:
        logged_qs = logged_qs.filter(
            workout_session__workout_plan__macrocycle_block_id=block_id
        )
    if pain_filter:
        logged_qs = logged_qs.filter(pain_status=pain_filter)

    ledger: list[Dict[str, Any]] = []
    for le in logged_qs:
        session = le.workout_session
        plan = session.workout_plan
        macro_block = plan.macrocycle_block if plan else None
        planned = le.planned_exercise
        eff_block = planned.effective_session_block if planned else ''

        if session_block and eff_block != session_block:
            continue

        prescribed_ex = planned.exercise if planned else None
        executed_ex = le.active_exercise
        session_srpe = calculate_srpe(session.duration_minutes or 0, float(session.session_rpe or 0))
        date_str = session.date_completed.strftime('%Y-%m-%d') if session.date_completed else ''

        sets_list = list(le.sets.all().order_by('set_number', 'id'))
        if sets_list:
            for s in sets_list:
                w_kg = round(float(s.weight_kg or 0.0), 1)
                reps_i = int(s.reps or 0)
                rpe_f = round(float(s.rpe or 0.0), 1) if s.rpe is not None else None
                tonnage = round(w_kg * reps_i, 1)
                est_1rm = calculate_1rm_brzycki(w_kg, reps_i) if w_kg > 0 and reps_i > 0 else 0.0
                ledger.append({
                    'date': date_str,
                    'session_id': session.id,
                    'plan_id': plan.id if plan else None,
                    'plan_name': plan.name if plan else '',
                    'block_title': macro_block.title if macro_block else 'Plan Independiente',
                    'block_number': macro_block.block_number if macro_block else None,
                    'week_number': plan.week_number if plan else None,
                    'day_number': plan.day_number if plan else None,
                    'session_block': eff_block or 'General',
                    'session_block_short': planned.session_block_short if planned else 'GEN',
                    'prescribed_exercise': prescribed_ex.name if prescribed_ex else '',
                    'executed_exercise': executed_ex.name if executed_ex else '',
                    'pain_status': le.pain_status,
                    'pain_status_label': le.get_pain_status_display(),
                    'readiness_level': session.readiness_level,
                    'readiness_scheme': session.readiness_scheme,
                    'set_number': s.set_number,
                    'weight_kg': w_kg,
                    'reps': reps_i,
                    'rpe': rpe_f,
                    'tonnage_kg': tonnage,
                    'est_1rm_kg': est_1rm,
                    'session_srpe': session_srpe,
                })
        elif le.pain_status == 'omitted_injury':
            # Registrar explícitamente la omisión por lesión en el libro histórico
            ledger.append({
                'date': date_str,
                'session_id': session.id,
                'plan_id': plan.id if plan else None,
                'plan_name': plan.name if plan else '',
                'block_title': macro_block.title if macro_block else 'Plan Independiente',
                'block_number': macro_block.block_number if macro_block else None,
                'week_number': plan.week_number if plan else None,
                'day_number': plan.day_number if plan else None,
                'session_block': eff_block or 'General',
                'session_block_short': planned.session_block_short if planned else 'GEN',
                'prescribed_exercise': prescribed_ex.name if prescribed_ex else '',
                'executed_exercise': 'OMITIDO_POR_LESION',
                'pain_status': le.pain_status,
                'pain_status_label': 'OMITIDO_POR_LESION',
                'readiness_level': session.readiness_level,
                'readiness_scheme': session.readiness_scheme,
                'set_number': 0,
                'weight_kg': 0.0,
                'reps': 0,
                'rpe': None,
                'tonnage_kg': 0.0,
                'est_1rm_kg': 0.0,
                'session_srpe': session_srpe,
            })

        if limit and len(ledger) >= limit:
            return ledger[:limit]

    return ledger


def build_am_visual_dashboard(athlete_profile) -> Dict[str, Any]:
    """
    Construye el `Dashboard_Visual` integral del Sistema AM (§4.4 / Fase 6):
      1. KPIs globales (ACWR, Tonelaje Total, sRPE medio, % Disposición Verde, Alertas Articulares).
      2. Evolución semanal de Tonelaje (kg) y Carga Interna (sRPE) con barras normalizadas para gráfico SVG.
      3. Distribución del Semáforo de Disposición Diaria (Verde 3-5, Amarillo 2, Rojo 1).
      4. Telemetría del Árbol Autónomo de Dolor Articular (Normal, Opción A, Opción B, OMITIDO_POR_LESION).
      5. Evolución de 1RM Estimado (Brzycki) y Récords Personales por ejercicio.
      6. Progreso de adherencia por bloque del Macrociclo activo.
    """
    from training.models import LoggedExercise, Macrocycle, WorkoutSession

    sport_metrics = get_athlete_sport_metrics(athlete_profile)
    rm_evolution = exercise_1rm_evolution(athlete_profile)

    sessions = list(
        WorkoutSession.objects
        .filter(athlete=athlete_profile)
        .select_related('workout_plan__macrocycle_block')
        .order_by('date_completed', 'id')
    )

    readiness_counts = {
        'green': 0,   # Niveles 3, 4, 5
        'yellow': 0,  # Nivel 2 (Fatiga Moderada)
        'red': 0,     # Nivel 1 (Colapso Sistémico)
    }
    srpe_values = []
    weekly_buckets: Dict[str, Dict[str, Any]] = {}

    for s in sessions:
        lvl = int(s.readiness_level or 4)
        if lvl >= 3:
            readiness_counts['green'] += 1
        elif lvl == 2:
            readiness_counts['yellow'] += 1
        else:
            readiness_counts['red'] += 1

        srpe = calculate_srpe(s.duration_minutes or 45, float(s.session_rpe or 7.0))
        srpe_values.append(srpe)

        plan = s.workout_plan
        if plan and plan.macrocycle_block_id and plan.week_number:
            w_key = f"B{plan.macrocycle_block.block_number}·S{plan.week_number}"
            w_label = f"Bloque {plan.macrocycle_block.block_number} · Semana {plan.week_number}"
        else:
            iso_year, iso_week, _ = s.date_completed.isocalendar()
            w_key = f"{iso_year}-W{iso_week:02d}"
            w_label = f"Sem {iso_week} ({iso_year})"

        bucket = weekly_buckets.setdefault(w_key, {
            'key': w_key,
            'label': w_label,
            'srpe_total': 0.0,
            'tonnage_kg': 0.0,
            'sessions_count': 0,
        })
        bucket['srpe_total'] = round(bucket['srpe_total'] + srpe, 1)
        bucket['sessions_count'] += 1

    # Tonelaje y telemetría articular desde LoggedExercise / LoggedSet
    logged_exercises = list(
        LoggedExercise.objects
        .filter(workout_session__athlete=athlete_profile)
        .select_related(
            'workout_session__workout_plan__macrocycle_block',
            'planned_exercise__exercise',
            'substituted_exercise',
        )
        .prefetch_related('sets')
    )

    pain_counts = {
        'normal': 0,
        'option_a': 0,
        'option_b': 0,
        'omitted_injury': 0,
    }
    pain_incidents = []
    tonnage_by_block_code: Dict[str, float] = {
        'B1_Movilidad': 0.0,
        'B2_Velocidad': 0.0,
        'B3_Potencia': 0.0,
        'B4_Principal': 0.0,
        'B4_Accesorio': 0.0,
        'B5_Cardio': 0.0,
    }

    for le in logged_exercises:
        p_status = le.pain_status or 'normal'
        pain_counts[p_status] = pain_counts.get(p_status, 0) + 1
        s = le.workout_session
        plan = s.workout_plan
        eff_block = le.planned_exercise.effective_session_block if le.planned_exercise else ''

        if p_status != 'normal':
            pain_incidents.append({
                'date': s.date_completed.strftime('%Y-%m-%d') if s.date_completed else '',
                'prescribed_exercise': le.planned_exercise.exercise.name if le.planned_exercise else '',
                'active_exercise': le.active_exercise.name if le.active_exercise else '',
                'pain_status': p_status,
                'pain_status_label': le.get_pain_status_display(),
                'session_block': eff_block,
            })

        if plan and plan.macrocycle_block_id and plan.week_number:
            w_key = f"B{plan.macrocycle_block.block_number}·S{plan.week_number}"
        else:
            iso_year, iso_week, _ = s.date_completed.isocalendar()
            w_key = f"{iso_year}-W{iso_week:02d}"

        ex_tonnage = 0.0
        for st in le.sets.all():
            ex_tonnage += float(st.weight_kg or 0.0) * int(st.reps or 0)
        ex_tonnage = round(ex_tonnage, 1)

        if w_key in weekly_buckets:
            weekly_buckets[w_key]['tonnage_kg'] = round(
                weekly_buckets[w_key]['tonnage_kg'] + ex_tonnage, 1
            )
        if eff_block in tonnage_by_block_code:
            tonnage_by_block_code[eff_block] = round(
                tonnage_by_block_code[eff_block] + ex_tonnage, 1
            )

    weekly_series = list(weekly_buckets.values())[-8:]
    max_weekly_tonnage = max((w['tonnage_kg'] for w in weekly_series), default=0.0) or 1.0
    max_weekly_srpe = max((w['srpe_total'] for w in weekly_series), default=0.0) or 1.0
    for w in weekly_series:
        w['tonnage_pct'] = max(6, int(round((w['tonnage_kg'] / max_weekly_tonnage) * 100))) if w['tonnage_kg'] > 0 else 0
        w['srpe_pct'] = max(6, int(round((w['srpe_total'] / max_weekly_srpe) * 100))) if w['srpe_total'] > 0 else 0

    total_sessions_count = len(sessions)
    green_readiness_pct = (
        round((readiness_counts['green'] / total_sessions_count) * 100, 1)
        if total_sessions_count > 0
        else 100.0
    )
    avg_srpe = round(sum(srpe_values) / len(srpe_values), 1) if srpe_values else 0.0

    # Adherencia por bloques del Macrociclo activo
    active_macrocycle = (
        Macrocycle.objects.filter(athlete=athlete_profile, is_active=True)
        .prefetch_related('blocks__workout_plans')
        .order_by('-created_at')
        .first()
    )
    macrocycle_adherence = []
    if active_macrocycle:
        for blk in active_macrocycle.blocks.all().order_by('block_number'):
            plans = list(blk.workout_plans.all())
            total_p = len(plans)
            comp_p = sum(1 for p in plans if p.is_completed)
            pct = int(round((comp_p / total_p) * 100)) if total_p > 0 else 0
            macrocycle_adherence.append({
                'block': blk,
                'total_plans': total_p,
                'completed_plans': comp_p,
                'adherence_pct': pct,
            })

    # Récords 1RM ordenados de mayor a menor
    pr_table = [
        {'exercise_name': name, 'max_1rm_kg': round(val, 1)}
        for name, val in sorted(
            sport_metrics['max_1rm_records'].items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
    ]

    return {
        'metrics': sport_metrics,
        'acwr': sport_metrics['acwr'],
        'total_sessions': total_sessions_count,
        'avg_srpe': avg_srpe,
        'green_readiness_pct': green_readiness_pct,
        'readiness_counts': readiness_counts,
        'pain_counts': pain_counts,
        'pain_Swap_total': pain_counts['option_a'] + pain_counts['option_b'] + pain_counts['omitted_injury'],
        'pain_incidents': pain_incidents[:15],
        'weekly_series': weekly_series,
        'tonnage_by_block': tonnage_by_block_code,
        'rm_evolution': rm_evolution,
        'pr_table': pr_table,
        'active_macrocycle': active_macrocycle,
        'macrocycle_adherence': macrocycle_adherence,
    }

