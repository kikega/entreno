"""
Motor estructural de Macrociclos, Publicación Progresiva, Matriz de Mesociclo (4 semanas)
y Nomenclatura Fraccionada de Intensidad del Sistema AM (V2.1).

Regla taxonómica estricta (Módulo 1):
Queda prohibida la nomenclatura clásica "ATR". Todo macrociclo se estructura en los
4 bloques competitivos oficiales del Sistema AM:
  1. Bloque 1 — Off-Season
  2. Bloque 2 — Pre-Training Camp
  3. Bloque 3 — Training Camp
  4. Bloque 4 — Fight Week
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import MacrocycleBlock, PlannedExercise


CANONICAL_AM_BLOCKS: tuple[dict, ...] = (
    {
        'block_number': 1,
        'phase_type': 'off_season',
        'subphase': 'none',
        'title': 'Bloque 1 — Off-Season',
        'horizon_label': '> 12 sem o sin fecha',
    },
    {
        'block_number': 2,
        'phase_type': 'pre_camp',
        'subphase': 'none',
        'title': 'Bloque 2 — Pre-Training Camp',
        'horizon_label': '8 a 12 sem',
    },
    {
        'block_number': 3,
        'phase_type': 'training_camp',
        'subphase': 'base',
        'title': 'Bloque 3 — Training Camp',
        'horizon_label': '1 a 7 sem',
    },
    {
        'block_number': 4,
        'phase_type': 'fight_week',
        'subphase': 'tapering',
        'title': 'Bloque 4 — Fight Week',
        'horizon_label': '< 1 sem',
    },
)


SESSION_BLOCK_SORT_ORDER: dict[str, int] = {
    'B1_Movilidad': 10,
    'B2_Velocidad': 20,
    'B3_Potencia': 30,
    'B4_Principal': 40,
    'B4_Accesorio': 41,
    'B4_Auxiliar': 42,
    'B5_Cardio': 50,
    '': 99,
}


SESSION_BLOCK_UI_META: dict[str, dict[str, str]] = {
    'B1_Movilidad': {
        'short': 'B1 · Movilidad',
        'label': 'Bloque 1 · Movilidad e Integridad Articular',
        'badge_class': 'bg-teal-50 text-teal-800 border-teal-200',
    },
    'B2_Velocidad': {
        'short': 'B2 · Velocidad',
        'label': 'Bloque 2 · Velocidad, RFD y Potencia Pura',
        'badge_class': 'bg-violet-50 text-violet-800 border-violet-200',
    },
    'B3_Potencia': {
        'short': 'B3 · Potencia',
        'label': 'Bloque 3 · Potencia Aplicada y Fuerza Explosiva',
        'badge_class': 'bg-amber-50 text-amber-800 border-amber-200',
    },
    'B4_Principal': {
        'short': 'B4 · Principal',
        'label': 'Bloque 4 · Fuerza Estructural — Principal',
        'badge_class': 'bg-sky-50 text-sky-800 border-sky-200',
    },
    'B4_Accesorio': {
        'short': 'B4 · Accesorio',
        'label': 'Bloque 4 · Fuerza Estructural — Accesorio',
        'badge_class': 'bg-indigo-50 text-indigo-800 border-indigo-200',
    },
    'B4_Auxiliar': {
        'short': 'B4 · Auxiliar',
        'label': 'Bloque 4 · Fuerza Estructural — Auxiliar / Cuello / Core',
        'badge_class': 'bg-slate-100 text-slate-700 border-slate-200',
    },
    'B5_Cardio': {
        'short': 'B5 · ESD',
        'label': 'Bloque 5 · Sistemas Energéticos (ESD)',
        'badge_class': 'bg-rose-50 text-rose-800 border-rose-200',
    },
    '': {
        'short': 'General',
        'label': 'Bloque General',
        'badge_class': 'bg-slate-100 text-slate-600 border-slate-200',
    },
}


_CLEAN_INT_RE = re.compile(r'^\s*(\d+)\s*$')
_RIR_RANGE_RE = re.compile(r'^\s*(\d+)\s*[-–/]\s*(\d+)\s*$')
_LEADING_INT_RE = re.compile(r'^\s*(\d+)')


def parse_positive_int(raw: object) -> int | None:
    """Devuelve un entero positivo solo cuando el texto es puramente numérico (ej. '3', '6')."""
    if raw is None:
        return None
    m = _CLEAN_INT_RE.match(str(raw))
    if not m:
        return None
    val = int(m.group(1))
    return val if val > 0 else None


def parse_sets_count(raw: object, default: int = 1) -> int:
    """Extrae el número entero de series prescritas (ej. '3' o '3 series' -> 3)."""
    if raw is None:
        return default
    m = _LEADING_INT_RE.match(str(raw))
    if not m:
        return default
    val = int(m.group(1))
    return max(1, min(val, 10))


def parse_rir_value(raw: object) -> int | None:
    """
    Convierte una pauta RIR en entero de reserva.
    Si recibe un rango conservador como '3-4' o 'RIR 3-4', toma el límite superior (4)
    para reflejar las repeticiones totales posibles sin fallo (ej. 5 + 4 = 5(9) @ RPE 6).
    """
    if raw is None:
        return None
    cleaned = re.sub(r'(?i)^\s*rir\s*:?\s*', '', str(raw)).strip()
    if not cleaned:
        return None
    m_int = _CLEAN_INT_RE.match(cleaned)
    if m_int:
        return int(m_int.group(1))
    m_range = _RIR_RANGE_RE.match(cleaned)
    if m_range:
        return max(int(m_range.group(1)), int(m_range.group(2)))
    return None


def _parse_rpe_float(raw: object) -> float | None:
    if raw is None:
        return None
    cleaned = re.sub(r'(?i)^\s*@?\s*rpe\s*:?\s*', '', str(raw)).strip().replace(',', '.')
    if not cleaned:
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return val if 1.0 <= val <= 10.0 else None


def clean_rpe_display(raw_rpe: object, fallback_rir: int | None = None) -> str:
    """Normaliza la etiqueta numérica de RPE (ej. '7.0' -> '7', '8.5' -> '8.5')."""
    val = _parse_rpe_float(raw_rpe)
    if val is None and fallback_rir is not None:
        val = float(max(1, min(10, 10 - fallback_rir)))
    if val is None:
        return ''
    if val.is_integer():
        return str(int(val))
    return f"{val:.1f}".rstrip('0').rstrip('.')


def enforce_am_accessory_rir(
    reps: object,
    rir: object,
    rpe: object,
    session_block: str,
    body_comp_goal: str,
) -> tuple[str, str]:
    """
    Regla fisiológica del Sistema AM (§4.2):
    Si el atleta tiene objetivo de 'mantenimiento' o 'corte_peso', los ejercicios de
    'B4_Accesorio' fuerzan un RIR 3-4 (RPE 6-7, ej. '5(9) @ RPE 6') para evitar hipertrofia
    sarcoplasmática y daño muscular innecesario.
    """
    rir_str = str(rir or '').strip()
    rpe_str = str(rpe or '').strip()

    if session_block != 'B4_Accesorio' or body_comp_goal not in ('mantenimiento', 'corte_peso'):
        return rir_str, rpe_str

    rir_val = parse_rir_value(rir_str)
    rpe_val = _parse_rpe_float(rpe_str)

    # Si ya está dentro de la ventana RIR 3-4, sincronizar RPE máximo (6 o 7)
    if rir_val in (3, 4):
        expected_rpe = 10 - rir_val
        if rpe_val is None or rpe_val > expected_rpe:
            return rir_str, str(expected_rpe)
        return rir_str, clean_rpe_display(rpe_val)

    # Si no se especificó RIR o se pautó demasiado cerca del fallo (RIR < 3) o fuera de rango:
    if rpe_val is not None and rpe_val <= 6.0:
        return '4', '6'
    if body_comp_goal == 'corte_peso':
        return '4', '6'
    # Mantenimiento: fuerza RIR 3 (@ RPE 7) como suelo protector (RIR 3-4)
    return '3', '7'


def format_am_reps_fraction(reps: object, rir: object) -> str:
    """
    Devuelve 'Repeticiones_Objetivo(Repeticiones_Totales_Posibles)', p.ej. '3(6)' o '6(8)'.
    Si las repeticiones son por tiempo/distancia ('30s', '8/lado') o no hay RIR entero, devuelve ''.
    """
    reps_int = parse_positive_int(reps)
    rir_int = parse_rir_value(rir)
    if reps_int is None or rir_int is None or rir_int < 0:
        return ''
    total_possible = reps_int + rir_int
    return f"{reps_int}({total_possible})"


def format_am_fractional_intensity(reps: object, rir: object = '', rpe: object = '') -> str:
    """
    Formatea la Nomenclatura Fraccionada de Intensidad del Sistema AM (§4.2):
        Repeticiones_Objetivo(Repeticiones_Totales_Posibles) @ RPE X
    Ejemplos:
        reps='3', rir='3', rpe='7' -> '3(6) @ RPE 7'
        reps='6', rir='2', rpe='8' -> '6(8) @ RPE 8'
        reps='5', rir='4', rpe='6' -> '5(9) @ RPE 6'
    """
    fraction = format_am_reps_fraction(reps, rir)
    if not fraction:
        return ''
    rir_int = parse_rir_value(rir)
    rpe_clean = clean_rpe_display(rpe, fallback_rir=rir_int)
    if rpe_clean:
        return f"{fraction} @ RPE {rpe_clean}"
    return fraction


def format_am_series_prescription(
    sets: object,
    reps: object,
    rir: object = '',
    rpe: object = '',
) -> str:
    """
    Formatea la cabecera completa de celda de la Matriz de Mesociclo (§4.3):
        '3 Series x 3(5) @ RPE 8'
        '2 Series x 2(5) @ RPE 7'
    Y ofrece fallback legible para bloques no fraccionados (B1/B2/B5, ej. '2 Series x 8/lado').
    """
    sets_str = str(sets or '').strip()
    reps_str = str(reps or '').strip()
    fractional = format_am_fractional_intensity(reps_str, rir, rpe)

    if fractional:
        if sets_str:
            return f"{sets_str} Series x {fractional}"
        return fractional

    parts = []
    if sets_str and reps_str:
        parts.append(f"{sets_str} Series x {reps_str}")
    elif reps_str:
        parts.append(reps_str)
    elif sets_str:
        parts.append(f"{sets_str} Series")

    rpe_clean = clean_rpe_display(rpe)
    if rpe_clean:
        parts.append(f"@ RPE {rpe_clean}")
    return ' '.join(parts)


def build_mesocycle_matrix(block: 'MacrocycleBlock', day_number: int = 1) -> dict:
    """
    Construye la estructura matricial de 4 semanas (o `block.weeks_count` semanas)
    para un día de entrenamiento concreto dentro de un `MacrocycleBlock`.

    - Alinea horizontalmente el mismo ejercicio a través de Semana 1..N.
    - Ordena las filas según los 5 bloques concurrentes del Sistema AM (B1 -> B5).
    - Calcula `max_sets` por fila y marca con `is_locked=True` las series excedentes
      en semanas de descarga / Tapering (p.ej. Semana 3 o 4 con 2 series frente a 3-4 en Semana 1-2).
    """
    week_numbers = block.week_numbers
    plans_qs = (
        block.workout_plans.filter(day_number=day_number)
        .prefetch_related(
            'planned_exercises__exercise',
            'session__logged_exercises__sets',
        )
        .order_by('week_number', 'id')
    )

    week_plans: dict[int, object | None] = {w: None for w in week_numbers}
    for plan in plans_qs:
        if plan.week_number in week_plans and week_plans[plan.week_number] is None:
            week_plans[plan.week_number] = plan

    # Mapa: clave de fila -> metadatos + diccionario {week_number: PlannedExercise}
    rows_map: dict[tuple, dict] = {}
    for w in week_numbers:
        plan = week_plans.get(w)
        if not plan:
            continue
        session = getattr(plan, 'session', None)
        logged_map = {}
        if session is not None:
            logged_map = {
                le.planned_exercise_id: list(le.sets.all())
                for le in session.logged_exercises.all()
            }

        for pe in plan.planned_exercises.all():
            eff_block = pe.effective_session_block
            # Agrupamos por bloque y ejercicio (y orden base si aparece duplicado)
            row_key = (eff_block, pe.exercise_id, pe.order)
            if row_key not in rows_map:
                block_meta = SESSION_BLOCK_UI_META.get(eff_block, SESSION_BLOCK_UI_META[''])
                rows_map[row_key] = {
                    'session_block': eff_block,
                    'block_short': block_meta['short'],
                    'block_label': block_meta['label'],
                    'block_badge_class': block_meta['badge_class'],
                    'sort_key': (
                        SESSION_BLOCK_SORT_ORDER.get(eff_block, 99),
                        pe.order,
                        pe.exercise.name.lower(),
                    ),
                    'exercise': pe.exercise,
                    'order': pe.order,
                    'focus': pe.focus,
                    'tempo': pe.tempo,
                    'rest': pe.rest,
                    'notes': pe.notes,
                    'weeks_data': {},
                }
            rows_map[row_key]['weeks_data'][w] = {
                'planned': pe,
                'plan': plan,
                'prescribed_sets': parse_sets_count(pe.sets, default=1),
                'logged_sets': logged_map.get(pe.id, []),
            }

    sorted_rows = sorted(rows_map.values(), key=lambda r: r['sort_key'])

    matrix_rows = []
    for row in sorted_rows:
        prescribed_counts = [
            cell['prescribed_sets'] for cell in row['weeks_data'].values()
        ]
        max_sets = max(prescribed_counts) if prescribed_counts else 1

        cells = []
        for w in week_numbers:
            w_data = row['weeks_data'].get(w)
            plan = week_plans.get(w)
            if not w_data:
                cells.append({
                    'week_number': w,
                    'plan': plan,
                    'planned': None,
                    'prescription': '',
                    'load': '',
                    'prescribed_sets': 0,
                    'max_sets': max_sets,
                    'set_slots': [
                        {'set_number': idx, 'is_locked': True, 'logged': None}
                        for idx in range(1, max_sets + 1)
                    ],
                })
                continue

            pe: 'PlannedExercise' = w_data['planned']
            p_sets = w_data['prescribed_sets']
            logged_by_num = {s.set_number: s for s in w_data['logged_sets']}

            set_slots = []
            for idx in range(1, max_sets + 1):
                is_locked = idx > p_sets
                set_slots.append({
                    'set_number': idx,
                    'is_locked': is_locked,
                    'logged': None if is_locked else logged_by_num.get(idx),
                })

            cells.append({
                'week_number': w,
                'plan': plan,
                'planned': pe,
                'prescription': pe.am_series_prescription,
                'fractional_intensity': pe.am_fractional_intensity,
                'load': pe.load,
                'prescribed_sets': p_sets,
                'max_sets': max_sets,
                'set_slots': set_slots,
            })

        matrix_rows.append({
            **row,
            'max_sets': max_sets,
            'cells': cells,
        })

    week_headers = [
        {
            'week_number': w,
            'label': f"Semana {w}",
            'plan': week_plans.get(w),
        }
        for w in week_numbers
    ]

    return {
        'block': block,
        'day_number': day_number,
        'day_numbers': list(range(1, (block.sessions_per_week or 3) + 1)),
        'week_numbers': week_numbers,
        'week_headers': week_headers,
        'rows': matrix_rows,
    }
