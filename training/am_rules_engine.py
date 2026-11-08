"""
Fase 4 — Motor Determinista de Reglas Algorítmicas (8 Módulos), Integración con ML
y Conector Universal LLM Opcional del Sistema AM (V2.1).

Arquitectura híbrida:
1. Los 8 módulos clínicos del Sistema AM se ejecutan SIEMPRE de forma 100 % determinista
   en Python para auditar la ficha de triage (`MMATriageProfile`) y filtrar el catálogo
   cerrado de ejercicios (`BD_Maestra_Ejercicios`).
2. Por defecto (`AM_LLM_ENABLED=False` en `.env`), el ensamblado de los 4 bloques del
   macrociclo utiliza el motor determinista del Sistema AM combinado con el predictor ML
   de cargas de la aplicación (`predict_next_load`).
3. Cuando se activa en `.env` (`AM_LLM_ENABLED=True` + credenciales de `AM_LLM_PROVIDER`),
   el sistema envía el payload clínico y el catálogo cerrado al LLM configurado
   (`openai`, `openai_compatible`, `anthropic` o `gemini`), valida que el JSON devuelto
   solo referencie ejercicios autorizados del catálogo y combina la pauta con el predictor ML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import json
import math
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.conf import settings
from django.utils import timezone

from training.am_macrocycle import CANONICAL_AM_BLOCKS, enforce_am_accessory_rir
from training.ml.predict import predict_next_load
from training.models import (
    Exercise,
    LoggedSet,
    Macrocycle,
    MacrocycleBlock,
    MMATriageProfile,
    PlannedExercise,
    WorkoutPlan,
)


COMPLEXITY_RANK: dict[str, int] = {
    'Nivel_0_Novato': 0,
    'Nivel_1_Base': 1,
    'Nivel_2_Intermedio': 2,
    'Nivel_3_Avanzado': 3,
}


@dataclass
class AMClinicalDiagnosis:
    """Resultado determinista de procesar un `MMATriageProfile` a través de los 8 módulos."""

    # Módulo 1: Fases y concurrencia (Prohibido ATR)
    weeks_until_fight: int | None
    days_until_fight: int | None
    active_phase_type: str
    active_subphase: str
    active_block_number: int
    phase_priority_focus: str

    # Módulo 2: Cortocircuito de Novato (Edad_Entrenamiento = 0)
    training_age: int
    is_novice_shortcircuit: bool
    uses_percentage_loads: bool
    prescribed_tempo: str
    max_complexity_rank: int

    # Módulo 3: Perfil de Fuerza, Candado Olímpico y Candado de Empuje
    squat_e1rm_kg: float | None
    squat_bw_ratio: float | None
    bench_e1rm_kg: float | None
    pullup_e1rm_kg: float | None
    push_pull_ratio: float | None
    olympic_lock_open: bool
    b3_fallback_route: str
    push_lock_active: bool

    # Módulo 4: Material y Regla RFD de Balón Medicinal
    available_equipment: set[str]
    has_light_medball: bool
    medball_rfd_transfer_active: bool

    # Módulo 5: Corte de Peso y Candado Excéntrico
    weight_cut_kg: float | None
    weight_cut_pct: float | None
    weigh_in_rule: str
    body_composition_goal: str
    eccentric_lock_active: bool

    # Módulo 6: Diagnóstico Doble Wingate
    wingate_modality: str
    wingate_sprint_1: float | None
    wingate_sprint_2: float | None
    wingate_drop_pct: float | None
    wingate_profile: str

    # Módulo 7: Biometría del Ángulo ISA
    isa_archetype: str
    b4_main_dominant_vector: str
    b4_accessory_bias_vectors: tuple[str, ...]

    # Módulo 8: Recálculo Dinámico de Calendario
    calendar_recalc_mode: str

    # Seguridad clínica adicional (Vetos, Dolores y Prompt Override)
    hard_overrides_locks: set[str] = field(default_factory=set)
    biomechanical_vetoes: set[str] = field(default_factory=set)
    joint_pain_zones: set[str] = field(default_factory=set)
    private_clinical_notes: str = ''
    active_rules_log: list[str] = field(default_factory=list)

    def is_eccentric_locked_for_phase(self, phase_type: str) -> bool:
        """
        El Candado Excéntrico se activa por override manual en cualquier fase o
        automáticamente en Training Camp / Fight Week ante corte de peso severo (Módulo 5).
        """
        if 'activar_candado_excentrico' in self.hard_overrides_locks:
            return True
        if phase_type in ('training_camp', 'fight_week') and self._has_severe_weight_cut():
            return True
        return False

    def is_olympic_open_for_phase(self, phase_type: str) -> bool:
        """
        El Candado Olímpico (Ruta 1 B3) se cierra automáticamente al entrar en Training Camp
        o Fight Week, salvo apertura manual explícita del entrenador (Módulo 3).
        """
        if self.is_novice_shortcircuit or 'cerrar_candado_olimpico' in self.hard_overrides_locks:
            return False
        if 'abrir_candado_olimpico' in self.hard_overrides_locks:
            return True
        if phase_type != 'off_season':
            return False
        return self.olympic_lock_open

    @property
    def b3_route(self) -> str:
        """Ruta activa del Bloque 3 (Potencia) para la fase actual."""
        if self.is_olympic_open_for_phase(self.active_phase_type):
            return 'Candado_Olimpico_R1'
        return self.b3_fallback_route

    @property
    def b5_protocol(self) -> str:
        """Código del protocolo energético activo en Bloque 5 (`LI`, `SI` o `RSS-P`)."""
        return self.b5_prescription_for_phase(self.active_phase_type, week_num=1)['protocol_code']

    def _has_severe_weight_cut(self) -> bool:
        cut_kg = self.weight_cut_kg or 0.0
        cut_pct = self.weight_cut_pct or 0.0
        if cut_kg > 6.0:
            return True
        if self.weigh_in_rule == 'profesional_24h' and cut_pct > 8.0:
            return True
        if self.weigh_in_rule == 'amateur_mismo_dia' and cut_pct >= 5.0:
            return True
        return False

    def b5_prescription_for_phase(self, phase_type: str, week_num: int = 1) -> dict[str, str]:
        """
        Devuelve la prescripción determinista del Bloque 5 (Sistemas Energéticos)
        cruzando el Módulo 6 (Doble Wingate) con la fase competitiva y semana.
        """
        # Si es Motor Diésel (Módulo 6) o fase de puesta a punto / Fight Week -> RSS-P 8"/52"
        if self.wingate_profile == 'motor_diesel_alactico' or phase_type in ('training_camp', 'fight_week'):
            sets = '4' if (phase_type == 'fight_week' or week_num == 4) else str(min(8, 5 + week_num))
            return {
                'protocol_code': 'RSS-P',
                'sets': sets,
                'reps': '8s',
                'rest': '52s pasivo',
                'rpe': '9',
                'focus': 'Potencia Aláctica RSS-P (8" sprint máximo / 52" descanso pasivo)',
                'notes': 'Módulo 6 Sistema AM: Sprints repetidos cortos alácticos (RSS-P 8"/52") para reclutamiento de fibras rápidas.',
            }

        # Caída > 20 % (Capacidad Aeróbica y Buffer Láctico) o perfil estándar en Off-Season / Pre-Camp
        if phase_type == 'off_season':
            sets = '3' if week_num in (1, 4) else '4'
            return {
                'protocol_code': 'LI',
                'sets': sets,
                'reps': '3 min',
                'rest': '2 min',
                'rpe': '8',
                'focus': 'Intervalos Largos (LI) — Capacidad Aeróbica y Buffer Láctico',
                'notes': 'Módulo 6 Sistema AM: Intervalos Largos (LI) en Off-Season para ampliar base oxidativa y aclarado de lactato.',
            }

        # Pre-Training Camp -> Intervalos Cortos (SI)
        sets = '2' if week_num == 4 else '3'
        return {
            'protocol_code': 'SI',
            'sets': sets,
            'reps': '6x30s/30s',
            'rest': '3 min entre bloques',
            'rpe': '8.5',
            'focus': 'Intervalos Cortos (SI) — Tolerancia Glucolítica Específica',
            'notes': 'Módulo 6 Sistema AM: Intervalos Cortos (SI) en Pre-Training Camp para potencia aeróbica y buffer láctico.',
        }


def _is_low_wingate_s1_peak(triage: MMATriageProfile) -> bool:
    """Detecta si el Pico S1 del Doble Wingate es bajo ('Motor Diésel' Δ <= -2)."""
    if triage.wingate_sprint_1 is None:
        return False
    s1 = float(triage.wingate_sprint_1)
    bw = float(triage.fasting_weight_kg or 75.0)
    notes_lower = (triage.private_clinical_notes or '').lower()
    if 'motor diesel' in notes_lower or 'motor diésel' in notes_lower:
        return True
    if triage.wingate_modality == 'airbike_w':
        # Umbral de potencia pico baja en 30s AirBike (< 7.0 W/kg o < 520 W absolutos)
        return (s1 / max(bw, 40.0)) < 7.0 or s1 < 520.0
    if triage.wingate_modality in ('pista_m', 'assault_runner_m'):
        return s1 < 195.0
    return False


def evaluate_am_rules(
    triage: MMATriageProfile,
    phase_override: str | None = None,
    reference_date: date | None = None,
) -> AMClinicalDiagnosis:
    """
    Evalúa de forma 100 % determinista los 8 Módulos del Sistema AM (V2.1)
    sobre la ficha `MMATriageProfile` del luchador.
    """
    ref_date = reference_date or timezone.now().date()
    locks = set(triage.hard_overrides_locks or [])
    vetoes = set(triage.biomechanical_vetoes or [])
    pains = set(triage.current_joint_pain_zones or [])
    equipment = set(triage.available_equipment or [])
    rules_log: list[str] = []

    # --- MÓDULO 1: Fases y Concurrencia (Prohibido ATR) ---
    if triage.next_fight_date:
        days_left = max(0, (triage.next_fight_date - ref_date).days)
        weeks_left: int | None = days_left // 7
    else:
        days_left = None
        weeks_left = None

    if weeks_left is None or weeks_left > 12:
        phase_type = 'off_season'
        subphase = 'none'
        block_num = 1
        priority_focus = 'fuerza_maxima_y_accesorios'
    elif 8 <= weeks_left <= 12:
        phase_type = 'pre_camp'
        subphase = 'none'
        block_num = 2
        priority_focus = 'fuerza_aplicada_y_potencia'
    elif 1 <= weeks_left <= 7:
        phase_type = 'training_camp'
        subphase = 'base' if weeks_left > 4 else 'tapering'
        block_num = 3
        priority_focus = 'velocidad_rfd'
    else:
        phase_type = 'fight_week'
        subphase = 'tapering'
        block_num = 4
        priority_focus = 'velocidad_rfd'

    effective_phase = phase_override or phase_type
    rules_log.append(
        f"Módulo 1: Fase activa '{effective_phase}' (subfase '{subphase}', prioridad '{priority_focus}')."
    )

    # --- MÓDULO 2: Cortocircuito de Novato (Edad_Entrenamiento = 0) ---
    is_novice = (
        triage.strength_experience == 'novato'
        or not triage.knows_rm_marks
        or 'cortocircuito_novato' in locks
    )
    if is_novice:
        training_age = 0
        uses_pct = False
        tempo = '3-1-0'
        max_comp = 1  # Nivel_0_Novato y Nivel_1_Base
        rules_log.append(
            "Módulo 2: Cortocircuito de Novato ACTIVO (Edad_Entrenamiento = 0, sin %, tempo 3-1-0, halterofilia prohibida)."
        )
    else:
        training_age = 1 if triage.strength_experience == 'intermedio' else 2
        uses_pct = True
        tempo = '2-0-X-0'
        max_comp = 2 if triage.olympic_lifts_relation == 'no_domina_motivado' else 3

    # --- MÓDULO 3: Perfil de Fuerza, Candado Olímpico y Candado de Empuje ---
    sq_e1rm = triage.squat_e1rm_kg
    sq_ratio = triage.squat_bw_ratio
    bn_e1rm = triage.bench_e1rm_kg
    pu_e1rm = triage.pullup_e1rm_kg
    pp_ratio = triage.push_pull_ratio

    has_barbell = 'Barra olímpica (20 kg) y discos' in equipment
    motivated_olympic = triage.olympic_lifts_relation in ('domina_motivado', 'no_domina_motivado')
    meets_squat_ratio = sq_ratio is not None and sq_ratio >= 1.5

    if is_novice or 'cerrar_candado_olimpico' in locks:
        olympic_open = False
    elif 'abrir_candado_olimpico' in locks:
        olympic_open = True
    else:
        olympic_open = bool(
            effective_phase == 'off_season'
            and meets_squat_ratio
            and has_barbell
            and motivated_olympic
        )

    b3_fallback = 'Ruta_Landmine_R2' if 'Landmine' in equipment else 'Ruta_Salto_Lastrado_R3'
    if not olympic_open:
        rules_log.append(
            f"Módulo 3: Candado Olímpico CERRADO -> deriva Bloque 3 a {b3_fallback}."
        )
    else:
        rules_log.append("Módulo 3: Candado Olímpico ABIERTO (Ruta 1 Halterofilia habilitada).")

    push_lock = bool(
        'activar_candado_empuje' in locks
        or (pp_ratio is not None and pp_ratio > 1.15)
    )
    if push_lock:
        rules_log.append(
            f"Módulo 3: Candado de Empuje ACTIVO (ratio Banca/Dominada={pp_ratio}) -> 100 % accesorios B4 a tracción/escápula."
        )

    # --- MÓDULO 4: Inventario Estricto y Regla RFD de Balón Medicinal ---
    has_medball = triage.has_light_medball
    medball_transfer = not has_medball
    if medball_transfer:
        rules_log.append(
            "Módulo 4: Sin Balón Medicinal ligero (<= 6 kg) -> transfiere cuota balística superior de B2 a Ruta 4 del B3."
        )

    # --- MÓDULO 5: Corte de Peso y Candado Excéntrico ---
    cut_kg = triage.weight_cut_kg
    cut_pct = triage.weight_cut_pct
    severe_cut = False
    if (cut_kg or 0.0) > 6.0:
        severe_cut = True
    elif triage.weigh_in_rule == 'profesional_24h' and (cut_pct or 0.0) > 8.0:
        severe_cut = True
    elif triage.weigh_in_rule == 'amateur_mismo_dia' and (cut_pct or 0.0) >= 5.0:
        severe_cut = True

    eccentric_lock = bool(
        'activar_candado_excentrico' in locks
        or (effective_phase in ('training_camp', 'fight_week') and severe_cut)
    )
    if eccentric_lock:
        rules_log.append(
            "Módulo 5: Candado Excéntrico ACTIVO -> prohíbe High/Fast Braking, RDL y sentadilla libre profunda; enruta a pines e Isopush."
        )

    # --- MÓDULO 6: Diagnóstico Doble Wingate ---
    drop_pct = triage.wingate_drop_pct
    if drop_pct is not None and drop_pct > 20.0:
        wingate_profile = 'capacidad_aerobica_buffer'
        rules_log.append(
            f"Módulo 6: Doble Wingate con caída {drop_pct}% (> 20%) -> prioriza LI (Off-Season) y SI (Pre-Camp)."
        )
    elif drop_pct is not None and drop_pct <= 20.0 and _is_low_wingate_s1_peak(triage):
        wingate_profile = 'motor_diesel_alactico'
        rules_log.append(
            f"Módulo 6: Perfil 'Motor Diésel' (caída {drop_pct}% <= 20% con S1 bajo) -> suprime LI/SI e impone RSS-P 8\"/52\"."
        )
    else:
        wingate_profile = 'estandar'

    # --- MÓDULO 7: Biometría del Ángulo ISA ---
    isa = (triage.isa_angle or 'neutro').strip().lower()
    if isa == 'estrecho':
        b4_main_vec = 'Dominante_Rodilla'
        b4_acc_bias = ('Dominante_Cadera', 'Traccion_Horizontal')
        rules_log.append(
            "Módulo 7: ISA Estrecho (< 85º) -> B4 Principal Dominante Rodilla y sesgo 2:1 Bisagra/Tracción en B4 Accesorios."
        )
    elif isa == 'ancho':
        b4_main_vec = 'Dominante_Cadera'
        b4_acc_bias = ('Dominante_Rodilla', 'Traccion_Vertical')
        rules_log.append(
            "Módulo 7: ISA Ancho (> 95º) -> B4 Principal Dominante Cadera y sesgo 2:1 Rodilla/Expansión en B4 Accesorios."
        )
    else:
        isa = 'neutro'
        b4_main_vec = 'Alterno'
        b4_acc_bias = ('Traccion_Horizontal', 'Dominante_Cadera', 'Traccion_Vertical')

    # --- MÓDULO 8: Modo de Recálculo Dinámico de Calendario ---
    if days_left is not None and days_left <= 14:
        recalc_mode = 'short_notice_14d'
    elif weeks_left == 3:
        recalc_mode = 'adelanto_3_sem'
    elif weeks_left == 5:
        recalc_mode = 'retraso_5_sem'
    elif weeks_left is not None and 6 <= weeks_left <= 8:
        recalc_mode = 'pendular_2_olas_6_8_sem'
    else:
        recalc_mode = 'estandar_4_sem'

    return AMClinicalDiagnosis(
        weeks_until_fight=weeks_left,
        days_until_fight=days_left,
        active_phase_type=effective_phase,
        active_subphase=subphase,
        active_block_number=block_num,
        phase_priority_focus=priority_focus,
        training_age=training_age,
        is_novice_shortcircuit=is_novice,
        uses_percentage_loads=uses_pct,
        prescribed_tempo=tempo,
        max_complexity_rank=max_comp,
        squat_e1rm_kg=sq_e1rm,
        squat_bw_ratio=sq_ratio,
        bench_e1rm_kg=bn_e1rm,
        pullup_e1rm_kg=pu_e1rm,
        push_pull_ratio=pp_ratio,
        olympic_lock_open=olympic_open,
        b3_fallback_route=b3_fallback,
        push_lock_active=push_lock,
        available_equipment=equipment,
        has_light_medball=has_medball,
        medball_rfd_transfer_active=medball_transfer,
        weight_cut_kg=cut_kg,
        weight_cut_pct=cut_pct,
        weigh_in_rule=triage.weigh_in_rule,
        body_composition_goal=triage.body_composition_goal,
        eccentric_lock_active=eccentric_lock,
        wingate_modality=triage.wingate_modality,
        wingate_sprint_1=float(triage.wingate_sprint_1) if triage.wingate_sprint_1 is not None else None,
        wingate_sprint_2=float(triage.wingate_sprint_2) if triage.wingate_sprint_2 is not None else None,
        wingate_drop_pct=drop_pct,
        wingate_profile=wingate_profile,
        isa_archetype=isa,
        b4_main_dominant_vector=b4_main_vec,
        b4_accessory_bias_vectors=b4_acc_bias,
        calendar_recalc_mode=recalc_mode,
        hard_overrides_locks=locks,
        biomechanical_vetoes=vetoes,
        joint_pain_zones=pains,
        private_clinical_notes=(triage.private_clinical_notes or '').strip(),
        active_rules_log=rules_log,
    )


def _has_required_equipment(exercise: Exercise, available_equipment: set[str]) -> bool:
    req = [
        item for item in (exercise.required_equipment or [])
        if item and item != 'Ninguno (Peso corporal)'
    ]
    if not req:
        return True
    return all(item in available_equipment for item in req)


def _is_vetoed_by_trainer(exercise: Exercise, vetoes: set[str]) -> bool:
    if not vetoes:
        return False
    name_low = (exercise.name or '').lower()
    req_eq = set(exercise.required_equipment or [])
    vec = exercise.patron_vector or ''
    mov = exercise.movement_pattern or ''

    if 'veto_empuje_vertical_overhead' in vetoes:
        if vec == 'Empuje_Vertical' or mov == 'empuje_vertical':
            return True
    if 'veto_empuje_horizontal_barra' in vetoes:
        if (vec == 'Empuje_Horizontal' or mov == 'empuje_horizontal') and (
            'Barra olímpica (20 kg) y discos' in req_eq or 'barra' in name_low
        ):
            return True
    if 'veto_traccion_pronacion' in vetoes:
        if 'pronad' in name_low or 'pronación' in name_low:
            return True
    if 'veto_impacto_pliometrico_inferior' in vetoes:
        if (
            exercise.category == 'pliometria'
            or exercise.lock_route == 'Ruta_Salto_Lastrado_R3'
            or exercise.contractile_regime in ('High_Braking', 'Fast_Braking')
        ):
            return True
    if 'veto_sprints_lineales_suelo' in vetoes:
        if exercise.lock_route == 'Candado_Sprint_Suelo':
            return True
    if 'veto_carga_axial_espinal' in vetoes:
        if (
            'Barra olímpica (20 kg) y discos' in req_eq
            and vec in ('Dominante_Rodilla', 'Dominante_Cadera', 'Triple_Extension')
            and exercise.compromised_joint == 'Lumbares'
        ):
            return True
    return False


def _is_prohibited_by_eccentric_lock(exercise: Exercise) -> bool:
    """Módulo 5: detecta ejercicios prohibidos durante el Candado Excéntrico."""
    if exercise.contractile_regime in ('High_Braking', 'Fast_Braking'):
        return True
    name_low = (exercise.name or '').lower()
    forbidden_terms = ('rumano', 'rdl', 'drop jump', 'depth jump', 'excéntric', 'excentric', 'profunda libre')
    return any(term in name_low for term in forbidden_terms)


def filter_am_catalog_for_diagnosis(
    diagnosis: AMClinicalDiagnosis,
    phase_type: str | None = None,
    queryset=None,
) -> dict[str, list[Exercise]]:
    """
    Filtra y ordena `BD_Maestra_Ejercicios` aplicando de forma estricta los Módulos 2, 3, 4, 5 y 7,
    además de los vetos biomecánicos del entrenador y la evasión autónoma de articulaciones con dolor.
    Devuelve un diccionario `{session_block: [Exercise, ...]}` con candidatos 100 % aptos.
    """
    eff_phase = phase_type or diagnosis.active_phase_type
    olympic_open = diagnosis.is_olympic_open_for_phase(eff_phase)
    eccentric_locked = diagnosis.is_eccentric_locked_for_phase(eff_phase)

    base_qs = (queryset if queryset is not None else Exercise.objects.all()).select_related(
        'regression_option_a',
        'regression_option_b',
    )
    if queryset is None and base_qs.exclude(session_block='').exists():
        base_qs = base_qs.exclude(session_block='')

    pools: dict[str, list[Exercise]] = {
        'B1_Movilidad': [],
        'B2_Velocidad': [],
        'B3_Potencia': [],
        'B4_Principal': [],
        'B4_Accesorio': [],
        'B4_Auxiliar': [],
        'B5_Cardio': [],
    }
    seen_ids_per_block: dict[str, set[int]] = {k: set() for k in pools}

    def _resolve_candidate(ex: Exercise, target_block: str) -> Exercise | None:
        # 1. Material requerido (Módulo 4)
        if not _has_required_equipment(ex, diagnosis.available_equipment):
            return None

        # 2. Nivel de complejidad (Módulo 2 y 3)
        comp_rank = COMPLEXITY_RANK.get(ex.complexity_level, 1)
        if comp_rank > diagnosis.max_complexity_rank:
            return None

        # 3. Candado Olímpico (Módulo 3)
        if ex.lock_route == 'Candado_Olimpico_R1' and not olympic_open:
            return None

        # 4. Regla RFD de Balón Medicinal (Módulo 4)
        if ex.lock_route == 'Candado_Balon_Ligero' and diagnosis.medball_rfd_transfer_active:
            return None

        # 5. Candado de Empuje en accesorios B4 (Módulo 3)
        if target_block == 'B4_Accesorio' and diagnosis.push_lock_active:
            if ex.patron_vector in ('Empuje_Horizontal', 'Empuje_Vertical') or ex.movement_pattern in (
                'empuje_horizontal',
                'empuje_vertical',
            ):
                return None

        # 6. Vetos biomecánicos del entrenador
        if _is_vetoed_by_trainer(ex, diagnosis.biomechanical_vetoes):
            return None

        # 7. Candado Excéntrico (Módulo 5): si está prohibido, intenta sustituir por Opción A isométrica
        if eccentric_locked and _is_prohibited_by_eccentric_lock(ex):
            opt_a = ex.regression_option_a
            if (
                opt_a is not None
                and not _is_prohibited_by_eccentric_lock(opt_a)
                and _has_required_equipment(opt_a, diagnosis.available_equipment)
                and not _is_vetoed_by_trainer(opt_a, diagnosis.biomechanical_vetoes)
            ):
                ex = opt_a
            else:
                return None

        # 8. Dolor articular reportado: si compromete una articulación dolorida, deriva a Opción A o B
        if ex.compromised_joint and ex.compromised_joint != 'Ninguna' and ex.compromised_joint in diagnosis.joint_pain_zones:
            substituted = None
            for fallback in (ex.regression_option_a, ex.regression_option_b):
                if (
                    fallback is not None
                    and fallback.compromised_joint not in diagnosis.joint_pain_zones
                    and _has_required_equipment(fallback, diagnosis.available_equipment)
                    and not _is_vetoed_by_trainer(fallback, diagnosis.biomechanical_vetoes)
                    and not (eccentric_locked and _is_prohibited_by_eccentric_lock(fallback))
                ):
                    substituted = fallback
                    break
            if substituted is None:
                return None
            ex = substituted

        # 9. Afinidad de Ángulo ISA (Módulo 7)
        if diagnosis.isa_archetype == 'estrecho' and ex.isa_tag == 'ISA_Ancho':
            return None
        if diagnosis.isa_archetype == 'ancho' and ex.isa_tag == 'ISA_Estrecho':
            return None

        return ex

    for raw_ex in base_qs:
        block_key = raw_ex.session_block or _infer_session_block_from_category(raw_ex)
        if block_key not in pools:
            continue
        candidate = _resolve_candidate(raw_ex, block_key)
        if candidate is None:
            continue
        if candidate.id not in seen_ids_per_block[block_key]:
            seen_ids_per_block[block_key].add(candidate.id)
            pools[block_key].append(candidate)

    # Ordenar cada pool según las prioridades biomecánicas de los Módulos 3, 4, 5 y 7
    for block_key, ex_list in pools.items():
        ex_list.sort(key=lambda e: _score_exercise_for_block(e, block_key, diagnosis, eff_phase))

    return pools


def _infer_session_block_from_category(ex: Exercise) -> str:
    mapping = {
        'movilidad': 'B1_Movilidad',
        'velocidad': 'B2_Velocidad',
        'pliometria': 'B2_Velocidad',
        'potencia': 'B3_Potencia',
        'fuerza': 'B4_Principal',
        'tecnica': 'B4_Auxiliar',
        'tactica': 'B5_Cardio',
        'otro': 'B4_Auxiliar',
    }
    return mapping.get(ex.category, 'B4_Accesorio')


def _score_exercise_for_block(
    ex: Exercise,
    block_key: str,
    diagnosis: AMClinicalDiagnosis,
    phase_type: str,
) -> tuple:
    """Calcula una tupla de ordenación (menor = mayor prioridad) según las reglas del Sistema AM."""
    # Afinidad ISA (Módulo 7)
    if diagnosis.isa_archetype == 'estrecho':
        isa_score = 0 if ex.isa_tag == 'ISA_Estrecho' else 1
    elif diagnosis.isa_archetype == 'ancho':
        isa_score = 0 if ex.isa_tag == 'ISA_Ancho' else 1
    else:
        isa_score = 0 if ex.isa_tag == 'Universal' else 1

    # Prioridad de ruta en Bloque 3 (Módulo 3 y Módulo 4)
    route_score = 2
    if block_key == 'B3_Potencia':
        if diagnosis.medball_rfd_transfer_active and ex.lock_route == 'Ruta_Balistica_Sup_R4':
            route_score = -1
        elif diagnosis.is_olympic_open_for_phase(phase_type) and ex.lock_route == 'Candado_Olimpico_R1':
            route_score = 0
        elif not diagnosis.is_olympic_open_for_phase(phase_type) and ex.lock_route == diagnosis.b3_fallback_route:
            route_score = 0
        elif ex.lock_route in ('Ruta_Landmine_R2', 'Ruta_Salto_Lastrado_R3', 'Ruta_Balistica_Sup_R4'):
            route_score = 1

    # Prioridad de régimen contráctil en Candado Excéntrico o ISA (Módulos 5 y 7)
    regime_score = 2
    if diagnosis.is_eccentric_locked_for_phase(phase_type):
        if ex.contractile_regime in ('Concentrico_Propulsivo', 'Isopush', 'Isohold'):
            regime_score = 0
    elif block_key in ('B2_Velocidad', 'B3_Potencia'):
        if diagnosis.isa_archetype == 'estrecho' and ex.contractile_regime == 'Fast_Braking':
            regime_score = 0
        elif diagnosis.isa_archetype == 'ancho' and ex.contractile_regime == 'Concentrico_Propulsivo':
            regime_score = 0

    # Prioridad de vector en B4 Principal y B4 Accesorio (Módulo 7)
    vector_score = 2
    if block_key == 'B4_Principal':
        if diagnosis.b4_main_dominant_vector != 'Alterno' and ex.patron_vector == diagnosis.b4_main_dominant_vector:
            vector_score = 0
    elif block_key == 'B4_Accesorio':
        if ex.patron_vector in diagnosis.b4_accessory_bias_vectors:
            vector_score = 0

    return (route_score, vector_score, regime_score, isa_score, ex.code or ex.name)


# ==============================================================================
# CONECTOR UNIVERSAL LLM OPCIONAL (ACTIVADO SOLO SI `AM_LLM_ENABLED=True` EN .env)
# ==============================================================================

class AMUniversalLLMClient:
    """
    Cliente ligero basado en `urllib.request` compatible con cualquier proveedor LLM
    configurado en `.env`:
      - `openai` / `openai_compatible` (OpenAI, DeepSeek, Groq, OpenRouter, Mistral, Ollama, vLLM...)
      - `anthropic` (Claude Messages API)
      - `gemini` (Google Gemini generateContent API)
    """

    @staticmethod
    def is_enabled_and_configured() -> bool:
        if not getattr(settings, 'AM_LLM_ENABLED', False):
            return False
        api_key = (getattr(settings, 'AM_LLM_API_KEY', '') or '').strip()
        base_url = (getattr(settings, 'AM_LLM_BASE_URL', '') or '').strip()
        return bool(api_key or base_url)

    @classmethod
    def request_structured_macrocycle(
        cls,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not cls.is_enabled_and_configured():
            return None

        provider = (getattr(settings, 'AM_LLM_PROVIDER', 'openai_compatible') or 'openai_compatible').strip().lower()
        api_key = (getattr(settings, 'AM_LLM_API_KEY', '') or '').strip()
        model = (getattr(settings, 'AM_LLM_MODEL', 'gpt-4o') or 'gpt-4o').strip()
        base_url = (getattr(settings, 'AM_LLM_BASE_URL', '') or '').strip()
        timeout = int(getattr(settings, 'AM_LLM_TIMEOUT_SECONDS', 45) or 45)

        try:
            if provider == 'anthropic':
                raw_text = cls._call_anthropic(system_prompt, user_payload, api_key, model, base_url, timeout)
            elif provider == 'gemini':
                raw_text = cls._call_gemini(system_prompt, user_payload, api_key, model, base_url, timeout)
            else:
                raw_text = cls._call_openai_compatible(system_prompt, user_payload, api_key, model, base_url, timeout)
            return cls._extract_json_object(raw_text)
        except (urllib_error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def _call_openai_compatible(
        system_prompt: str,
        user_payload: dict[str, Any],
        api_key: str,
        model: str,
        base_url: str,
        timeout: int,
    ) -> str:
        endpoint = base_url.rstrip('/') if base_url else 'https://api.openai.com/v1/chat/completions'
        if not endpoint.endswith('/chat/completions'):
            endpoint = f"{endpoint}/chat/completions"

        body = json.dumps({
            'model': model,
            'temperature': 0.1,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': json.dumps(user_payload, ensure_ascii=False)},
            ],
        }).encode('utf-8')

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f"Bearer {api_key}"

        req = urllib_request.Request(endpoint, data=body, headers=headers, method='POST')
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']

    @staticmethod
    def _call_anthropic(
        system_prompt: str,
        user_payload: dict[str, Any],
        api_key: str,
        model: str,
        base_url: str,
        timeout: int,
    ) -> str:
        endpoint = base_url.rstrip('/') if base_url else 'https://api.anthropic.com/v1/messages'
        body = json.dumps({
            'model': model,
            'max_tokens': 4096,
            'temperature': 0.1,
            'system': system_prompt,
            'messages': [
                {'role': 'user', 'content': json.dumps(user_payload, ensure_ascii=False)},
            ],
        }).encode('utf-8')

        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        }
        req = urllib_request.Request(endpoint, data=body, headers=headers, method='POST')
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['content'][0]['text']

    @staticmethod
    def _call_gemini(
        system_prompt: str,
        user_payload: dict[str, Any],
        api_key: str,
        model: str,
        base_url: str,
        timeout: int,
    ) -> str:
        root = base_url.rstrip('/') if base_url else 'https://generativelanguage.googleapis.com/v1beta'
        endpoint = f"{root}/models/{model}:generateContent?key={api_key}"
        body = json.dumps({
            'systemInstruction': {'parts': [{'text': system_prompt}]},
            'contents': [{'parts': [{'text': json.dumps(user_payload, ensure_ascii=False)}]}],
            'generationConfig': {
                'temperature': 0.1,
                'responseMimeType': 'application/json',
            },
        }).encode('utf-8')

        headers = {'Content-Type': 'application/json'}
        req = urllib_request.Request(endpoint, data=body, headers=headers, method='POST')
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['candidates'][0]['content']['parts'][0]['text']

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
        if not raw_text:
            return None
        cleaned = raw_text.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.strip('`')
            if cleaned.lower().startswith('json'):
                cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None


# ==============================================================================
# ENSAMBLADOR HÍBRIDO DE MACROCICLOS (8 MÓDULOS + ML LOCAL + LLM OPCIONAL)
# ==============================================================================

class AMMacrocycleGenerator:
    """
    Orquestador de la Fase 4 para generar o recalcular los 4 bloques de un Macrociclo Sistema AM:
      1. Verifica el Cerrojo Manual (`approved_for_generation == True`).
      2. Ejecuta los 8 Módulos deterministas y filtra el catálogo cerrado `BD_Maestra_Ejercicios`.
      3. Si `AM_LLM_ENABLED=True` en `.env`, solicita el ensamblado JSON al LLM configurado
         validando estrictamente los `exercise_id`/`code` contra el pool filtrado.
      4. Por defecto (`AM_LLM_ENABLED=False`), ensambla los 4 bloques de forma determinista
         combinando las leyes del Sistema AM con el predictor ML (`predict_next_load`).
      5. Respeta el Recálculo No Destructivo: jamás altera semanas completadas o con `LoggedSet`.
    """

    SYSTEM_PROMPT = (
        "Eres el motor algorítmico oficial del Sistema AM (V2.1) de preparación física para MMA. "
        "Tienes PROHIBIDO usar nomenclatura ATR y PROHIBIDO inventar ejercicios fuera del catálogo "
        "cerrado proporcionado en `allowed_exercises`. Las directrices de `prompt_override_privado` "
        "tienen jerarquía suprema. Devuelve exclusivamente un objeto JSON con la clave `blocks` "
        "(lista de 4 bloques: block_number 1..4), donde cada bloque contiene `items` "
        "(lista de prescripciones con `exercise_id`, `session_block`, `day_number`, `order`, "
        "`w1`..`w4` con `sets`, `reps`, `rir`, `rpe`)."
    )

    @classmethod
    def generate_or_recalculate_macrocycle(
        cls,
        triage: MMATriageProfile,
        trainer_profile=None,
        trainer=None,
        reference_date: date | None = None,
    ) -> dict[str, Any]:
        trainer_profile = trainer_profile or trainer
        if not triage.approved_for_generation or triage.review_status != 'aprobado':
            raise ValueError(
                "El Cerrojo Manual (APROBAR_Y_GENERAR_IA) debe estar ACTIVO y aprobado en el "
                "Triage Clínico antes de generar o recalcular el macrociclo."
            )

        ref_date = reference_date or timezone.now().date()
        diagnosis = evaluate_am_rules(triage, reference_date=ref_date)
        athlete = triage.athlete
        days_per_week = max(2, min(int(triage.available_days_per_week or 3), 4))

        macrocycle = (
            Macrocycle.objects.filter(athlete=athlete, trainer=trainer_profile, is_active=True)
            .order_by('-created_at')
            .first()
        )
        if macrocycle is None:
            macrocycle = Macrocycle.objects.create(
                name=f"Macrociclo Sistema AM — {athlete.user.display_name}",
                trainer=trainer_profile,
                athlete=athlete,
                target_fight_date=triage.next_fight_date,
                is_active=True,
            )
        else:
            macrocycle.target_fight_date = triage.next_fight_date
            macrocycle.save(update_fields=['target_fight_date', 'updated_at'])

        blocks = macrocycle.initialize_four_blocks(
            weeks_per_block=4,
            sessions_per_week=days_per_week,
        )

        # Intentar vía LLM solo si está habilitado y configurado en .env
        llm_plan = None
        engine_source = 'reglas_am_y_ml'
        if AMUniversalLLMClient.is_enabled_and_configured():
            pools_for_llm = filter_am_catalog_for_diagnosis(diagnosis)
            payload = cls._build_llm_payload(triage, diagnosis, pools_for_llm, days_per_week)
            llm_plan = AMUniversalLLMClient.request_structured_macrocycle(cls.SYSTEM_PROMPT, payload)
            if llm_plan and isinstance(llm_plan.get('blocks'), list):
                engine_source = f"llm_{getattr(settings, 'AM_LLM_PROVIDER', 'openai_compatible')}_y_ml"

        total_created_plans = 0
        total_generated_plans = 0
        total_preserved_plans = 0
        ml_predictions_used = 0

        for idx, block in enumerate(blocks):
            spec = CANONICAL_AM_BLOCKS[idx]
            block.phase_type = spec['phase_type']
            if block.phase_type == 'training_camp':
                block.subphase = diagnosis.active_subphase if diagnosis.active_phase_type == 'training_camp' else 'base'
            else:
                block.subphase = spec['subphase']
            block.sessions_per_week = days_per_week
            block.start_date = ref_date + timedelta(days=idx * 28)
            block.end_date = block.start_date + timedelta(days=(block.weeks_count * 7) - 1)
            block.trainer_notes = "\n".join(diagnosis.active_rules_log)
            block.save()

            block_pools = filter_am_catalog_for_diagnosis(diagnosis, phase_type=block.phase_type)
            allowed_by_id = {
                ex.id: ex
                for ex_list in block_pools.values()
                for ex in ex_list
            }

            llm_block_items = cls._extract_valid_llm_block_items(
                llm_plan, block.block_number, allowed_by_id
            )

            for day_num in range(1, days_per_week + 1):
                day_blueprints = (
                    [it for it in llm_block_items if int(it.get('day_number', 1)) == day_num]
                    if llm_block_items
                    else cls._build_deterministic_day_blueprints(
                        block.phase_type,
                        day_num,
                        block_pools,
                        diagnosis,
                    )
                )

                for week_num in block.week_numbers:
                    plan_date = block.start_date + timedelta(days=(week_num - 1) * 7 + (day_num - 1) * 2)
                    plan = (
                        WorkoutPlan.objects.filter(
                            macrocycle_block=block,
                            week_number=week_num,
                            day_number=day_num,
                        )
                        .order_by('id')
                        .first()
                    )
                    if plan is None:
                        plan = WorkoutPlan.objects.create(
                            name=f"{block.title} · Semana {week_num} · Día {day_num}",
                            trainer=trainer_profile,
                            athlete=athlete,
                            macrocycle_block=block,
                            week_number=week_num,
                            day_number=day_num,
                            sport='mma',
                            target_date=plan_date,
                        )
                        total_created_plans += 1

                    # Salvaguarda no destructiva (Flujo B / Módulo 8)
                    if plan.has_logged_activity:
                        total_preserved_plans += 1
                        continue

                    total_generated_plans += 1
                    plan.planned_exercises.all().delete()

                    for order_idx, bp in enumerate(day_blueprints, start=1):
                        ex: Exercise = bp['exercise']
                        s_block: str = bp['session_block']
                        w_key = f"w{min(week_num, 4)}"
                        w_spec = bp.get(w_key) or bp.get('w1') or {}

                        sets_str = str(w_spec.get('sets', '3'))
                        reps_str = str(w_spec.get('reps', '5'))
                        rir_str = str(w_spec.get('rir', '3'))
                        rpe_str = str(w_spec.get('rpe', '7'))

                        # Regla fisiológica de accesorios en Mantenimiento / Corte de Peso
                        rir_str, rpe_str = enforce_am_accessory_rir(
                            reps_str,
                            rir_str,
                            rpe_str,
                            s_block,
                            diagnosis.body_composition_goal,
                        )

                        load_str, load_note, used_ml = cls._resolve_hybrid_load(
                            athlete=athlete,
                            exercise=ex,
                            session_block=s_block,
                            week_num=week_num,
                            diagnosis=diagnosis,
                        )
                        if used_ml:
                            ml_predictions_used += 1

                        notes_parts = [bp.get('notes', '').strip(), load_note]
                        if diagnosis.private_clinical_notes and order_idx == 1:
                            # Se aplica la directriz clínica internamente sin exponer texto confidencial crudo
                            notes_parts.append("Pauta ajustada por auditoría biomecánica Sistema AM.")
                        final_notes = " · ".join(p for p in notes_parts if p)

                        PlannedExercise.objects.create(
                            workout_plan=plan,
                            exercise=ex,
                            session_block=s_block,
                            order=order_idx,
                            sets=sets_str,
                            reps=reps_str,
                            rir=rir_str,
                            rpe=rpe_str,
                            load=load_str,
                            tempo=bp.get('tempo') or diagnosis.prescribed_tempo,
                            rest=bp.get('rest', '90s'),
                            focus=bp.get('focus', ''),
                            notes=final_notes,
                        )

        return {
            'macrocycle': macrocycle,
            'diagnosis': diagnosis,
            'engine_source': engine_source,
            'created_plans': total_created_plans,
            'generated_plans': total_generated_plans,
            'preserved_plans': total_preserved_plans,
            'ml_predictions_used': ml_predictions_used,
        }

    @classmethod
    def recalculate_block_calendar(
        cls,
        block: MacrocycleBlock,
        new_fight_date: date | None,
        triage: MMATriageProfile | None = None,
        reference_date: date | None = None,
    ) -> dict[str, Any]:
        """
        Módulo 8 — Recálculo Dinámico de Calendario No Destructivo a mitad de bloque en curso:
          1. Adelanto a 3 semanas (`weeks_left == 3`): Elimina Semana 2 no registrada (`S1 -> S3 -> S4`,
             `weeks_count = 3`) y pasa el Bloque 5 a `RSS-P (8"/52")`.
          2. Short-Notice (`days_left <= 14`): Apaga Bloques 3 y 4 y deja solo `RSS-P` y
             *Neural Priming* (`B1_Movilidad` + `B2_Velocidad`) en las sesiones pendientes.
          3. Retraso a 5 semanas (`weeks_left == 5`): Clona la Semana 2 (`S1 -> S2 -> S2 -> S3 -> S4`,
             `weeks_count = 5`) respetando las series ya registradas.
          4. Retraso a 6-8 semanas (`6 <= weeks_left <= 8`): Activa el Modelo Pendular en 2 olas
             de 4 semanas cada una (`Pre-Training Camp` Ola 1 + `Training Camp` Ola 2).
        """
        ref_date = reference_date or timezone.now().date()
        macrocycle = block.macrocycle
        macrocycle.target_fight_date = new_fight_date
        macrocycle.save(update_fields=['target_fight_date', 'updated_at'])

        triage = triage or MMATriageProfile.objects.filter(athlete=macrocycle.athlete).first()
        if triage and triage.next_fight_date != new_fight_date:
            triage.next_fight_date = new_fight_date
            triage.save(update_fields=['next_fight_date', 'updated_at'])

        preserved_plans = sum(1 for p in block.workout_plans.all() if p.has_logged_activity)

        if new_fight_date is None:
            return {
                'mode': 'estandar_4_sem',
                'weeks_count': block.weeks_count,
                'preserved_plans': preserved_plans,
                'description': 'Calendario estándar de 4 semanas.',
            }

        days_left = max(0, (new_fight_date - ref_date).days)
        weeks_left = days_left // 7

        # --- Caso 1: Short-Notice (<= 14 días) ---
        if days_left <= 14:
            # Apagar Bloques 3 y 4 y dejar solo Neural Priming (B1 + B2) + RSS-P (B5) en sesiones pendientes
            macrocycle.blocks.filter(block_number__in=[3, 4]).update(is_published=False)
            block.weeks_count = max(1, min(2, math.ceil(max(days_left, 1) / 7)))
            block.subphase = 'tapering'
            block.save(update_fields=['weeks_count', 'subphase', 'updated_at'])

            # Eliminar semanas > weeks_count sin historial
            block.clear_unlogged_future_weeks(from_week=block.weeks_count + 1)

            for plan in block.workout_plans.all():
                if plan.has_logged_activity:
                    continue
                # Suprimir B3 y B4 pesados; mantener B1, B2 (Neural Priming) y pasar B5 a RSS-P 8"/52"
                for pe in list(plan.planned_exercises.all()):
                    eff = pe.effective_session_block
                    if eff in ('B3_Potencia', 'B4_Principal', 'B4_Accesorio', 'B4_Auxiliar'):
                        pe.delete()
                    elif eff == 'B5_Cardio':
                        pe.sets = '5'
                        pe.reps = '8s'
                        pe.rest = '52s pasivo'
                        pe.rpe = '9'
                        pe.focus = 'Short-Notice RSS-P (8"/52" pasivo)'
                        pe.save()
                    else:
                        pe.sets = '2'
                        pe.focus = 'Neural Priming (Activación SNC sin fatiga)'
                        pe.save()
            return {
                'mode': 'short_notice_14d',
                'weeks_count': block.weeks_count,
                'preserved_plans': preserved_plans,
                'description': 'Short-Notice (<= 14 días): activado Neural Priming (B1/B2) + RSS-P (8"/52").',
            }

        # --- Caso 2: Adelanto a 3 semanas (S1 -> S3 -> S4 + B5 a RSS-P 8"/52") ---
        if weeks_left == 3:
            w2_plans = list(block.workout_plans.filter(week_number=2))
            for p2 in w2_plans:
                if not p2.has_logged_activity:
                    p2.delete()

            # Desplazar S3 -> Sem 2 y S4 -> Sem 3 si no tienen historial conflictivo
            for old_w, new_w in ((3, 2), (4, 3)):
                for p in block.workout_plans.filter(week_number=old_w):
                    if not block.workout_plans.filter(week_number=new_w, day_number=p.day_number).exists():
                        p.week_number = new_w
                        p.name = f"{block.title} · Semana {new_w} · Día {p.day_number} (Adelanto S{old_w})"
                        p.save(update_fields=['week_number', 'name', 'updated_at'])

            block.weeks_count = 3
            block.subphase = 'tapering'
            block.save(update_fields=['weeks_count', 'subphase', 'updated_at'])

            # Pasar B5 a RSS-P (8"/52") en sesiones pendientes
            for plan in block.workout_plans.all():
                if plan.has_logged_activity:
                    continue
                for pe in plan.planned_exercises.filter(session_block='B5_Cardio'):
                    pe.sets = '6'
                    pe.reps = '8s'
                    pe.rest = '52s pasivo'
                    pe.rpe = '9'
                    pe.focus = 'RSS-P (8"/52") por adelanto a 3 semanas'
                    pe.save()
            return {
                'mode': 'adelanto_3_sem',
                'weeks_count': 3,
                'preserved_plans': preserved_plans,
                'description': 'Adelanto a 3 semanas (S1 -> S3 -> S4) y transición de B5 a RSS-P (8"/52").',
            }

        # --- Caso 3: Retraso a 5 semanas (Clona Semana 2: S1 -> S2 -> S2 -> S3 -> S4) ---
        if weeks_left == 5:
            block.weeks_count = 5
            block.save(update_fields=['weeks_count', 'updated_at'])

            # Desplazar de atrás hacia adelante: S4 -> Sem 5 y S3 -> Sem 4 (solo sesiones sin historial en destino)
            for old_w, new_w in ((4, 5), (3, 4)):
                for p in list(block.workout_plans.filter(week_number=old_w)):
                    if not p.has_logged_activity:
                        p.week_number = new_w
                        p.target_date = p.target_date + timedelta(days=7)
                        p.name = f"{block.title} · Semana {new_w} · Día {p.day_number}"
                        p.save(update_fields=['week_number', 'target_date', 'name', 'updated_at'])

            # Clonar Semana 2 en la nueva Semana 3
            for p2 in list(block.workout_plans.filter(week_number=2)):
                existing_w3 = block.workout_plans.filter(week_number=3, day_number=p2.day_number).first()
                if existing_w3 and existing_w3.has_logged_activity:
                    continue
                if existing_w3:
                    existing_w3.delete()
                cloned_plan = WorkoutPlan.objects.create(
                    name=f"{block.title} · Semana 3 (Clon Sem 2) · Día {p2.day_number}",
                    trainer=p2.trainer,
                    athlete=p2.athlete,
                    macrocycle_block=block,
                    week_number=3,
                    day_number=p2.day_number,
                    sport=p2.sport,
                    target_date=p2.target_date + timedelta(days=7),
                )
                for pe in p2.planned_exercises.all():
                    PlannedExercise.objects.create(
                        workout_plan=cloned_plan,
                        exercise=pe.exercise,
                        session_block=pe.session_block,
                        order=pe.order,
                        sets=pe.sets,
                        reps=pe.reps,
                        rir=pe.rir,
                        rpe=pe.rpe,
                        load=pe.load,
                        tempo=pe.tempo,
                        rest=pe.rest,
                        focus=pe.focus,
                        notes=pe.notes,
                    )
            return {
                'mode': 'retraso_5_sem',
                'weeks_count': 5,
                'preserved_plans': preserved_plans,
                'description': 'Retraso a 5 semanas: clonada Semana 2 (S1 -> S2 -> S2 -> S3 -> S4).',
            }

        # --- Caso 4: Retraso a 6-8 semanas (Modelo Pendular en 2 olas de 4 semanas) ---
        if 6 <= weeks_left <= 8:
            b2 = macrocycle.blocks.filter(block_number=2).first()
            b3 = macrocycle.blocks.filter(block_number=3).first()
            if b2:
                b2.weeks_count = 4
                b2.title = 'Bloque 2 — Pre-Training Camp (Ola Pendular 1)'
                b2.save(update_fields=['weeks_count', 'title', 'updated_at'])
            if b3:
                b3.weeks_count = 4
                b3.title = 'Bloque 3 — Training Camp (Ola Pendular 2)'
                b3.save(update_fields=['weeks_count', 'title', 'updated_at'])
            return {
                'mode': 'pendular_2_olas_6_8_sem',
                'weeks_count': 4,
                'preserved_plans': preserved_plans,
                'description': 'Retraso a 6-8 semanas: reestructurado en Modelo Pendular de 2 olas de 4 semanas.',
            }

        return {
            'mode': 'estandar_4_sem',
            'weeks_count': block.weeks_count,
            'preserved_plans': preserved_plans,
            'description': 'Calendario estándar de 4 semanas.',
        }

    @classmethod
    def _build_deterministic_day_blueprints(
        cls,
        phase_type: str,
        day_num: int,
        pools: dict[str, list[Exercise]],
        diagnosis: AMClinicalDiagnosis,
    ) -> list[dict[str, Any]]:
        """
        Construye los 5 bloques concurrentes de una sesión diaria (`Día 1..N`)
        respetando las leyes de los 8 módulos.
        """
        blueprints: list[dict[str, Any]] = []

        def _pick(block_key: str, index: int = 0) -> Exercise | None:
            candidates = pools.get(block_key) or []
            if not candidates:
                return None
            return candidates[index % len(candidates)]

        # 1. B1_Movilidad
        ex_b1 = _pick('B1_Movilidad', day_num - 1)
        if ex_b1:
            b1_focus = (
                'Expansión dorsal y rotación interna (ISA Estrecho)'
                if diagnosis.isa_archetype == 'estrecho'
                else 'Compresión oblicua y rotación externa (ISA Ancho)'
                if diagnosis.isa_archetype == 'ancho'
                else 'Movilidad articular e integridad escapular/cadera'
            )
            blueprints.append({
                'exercise': ex_b1,
                'session_block': 'B1_Movilidad',
                'tempo': 'Controlado',
                'rest': '45s',
                'focus': b1_focus,
                'w1': {'sets': '2', 'reps': '8/lado', 'rir': '', 'rpe': '6'},
                'w2': {'sets': '2', 'reps': '8/lado', 'rir': '', 'rpe': '6'},
                'w3': {'sets': '2', 'reps': '8/lado', 'rir': '', 'rpe': '6'},
                'w4': {'sets': '2', 'reps': '6/lado', 'rir': '', 'rpe': '5'},
            })

        # 2. B2_Velocidad
        ex_b2 = _pick('B2_Velocidad', day_num - 1)
        if ex_b2:
            blueprints.append({
                'exercise': ex_b2,
                'session_block': 'B2_Velocidad',
                'tempo': 'Explosivo',
                'rest': '90s',
                'focus': 'Velocidad pura, RFD y reactividad neural',
                'w1': {'sets': '3', 'reps': '4', 'rir': '', 'rpe': '7'},
                'w2': {'sets': '3', 'reps': '4', 'rir': '', 'rpe': '7.5'},
                'w3': {'sets': '4' if phase_type == 'training_camp' else '3', 'reps': '3', 'rir': '', 'rpe': '8'},
                'w4': {'sets': '2', 'reps': '3', 'rir': '', 'rpe': '6.5'},
            })

        # 3. B3_Potencia (con cuota extra si aplica Regla RFD de Balón Medicinal del Módulo 4)
        ex_b3 = _pick('B3_Potencia', day_num - 1)
        if ex_b3:
            b3_sets_w1 = '4' if diagnosis.medball_rfd_transfer_active else '3'
            b3_sets_w4 = '2'
            blueprints.append({
                'exercise': ex_b3,
                'session_block': 'B3_Potencia',
                'tempo': 'Concéntrico explosivo',
                'rest': '120s',
                'focus': (
                    'Potencia aplicada + cuota balística transferida (Regla RFD Sin Balón)'
                    if diagnosis.medball_rfd_transfer_active
                    else 'Potencia aplicada y transferencia al combate'
                ),
                'w1': {'sets': b3_sets_w1, 'reps': '3', 'rir': '3', 'rpe': '7'},
                'w2': {'sets': b3_sets_w1, 'reps': '3', 'rir': '2', 'rpe': '8'},
                'w3': {'sets': '3', 'reps': '2', 'rir': '2', 'rpe': '8'},
                'w4': {'sets': b3_sets_w4, 'reps': '2', 'rir': '3', 'rpe': '7'},
            })

        # 4. B4_Principal (Fuerza Estructural Principal con Nomenclatura Fraccionada)
        ex_b4p = _pick('B4_Principal', day_num - 1)
        if ex_b4p:
            if diagnosis.is_novice_shortcircuit:
                w_b4p = {
                    'w1': {'sets': '3', 'reps': '6', 'rir': '3', 'rpe': '7'},
                    'w2': {'sets': '3', 'reps': '6', 'rir': '3', 'rpe': '7'},
                    'w3': {'sets': '4', 'reps': '5', 'rir': '2', 'rpe': '8'},
                    'w4': {'sets': '2', 'reps': '5', 'rir': '3', 'rpe': '7'},
                }
            elif phase_type in ('training_camp', 'fight_week'):
                w_b4p = {
                    'w1': {'sets': '3', 'reps': '3', 'rir': '2', 'rpe': '8'},
                    'w2': {'sets': '3', 'reps': '3', 'rir': '2', 'rpe': '8'},
                    'w3': {'sets': '2', 'reps': '2', 'rir': '3', 'rpe': '7'},
                    'w4': {'sets': '2', 'reps': '2', 'rir': '3', 'rpe': '7'},
                }
            else:
                w_b4p = {
                    'w1': {'sets': '3', 'reps': '5', 'rir': '3', 'rpe': '7'},
                    'w2': {'sets': '4', 'reps': '4', 'rir': '2', 'rpe': '8'},
                    'w3': {'sets': '4', 'reps': '3', 'rir': '2', 'rpe': '8'},
                    'w4': {'sets': '2', 'reps': '3', 'rir': '3', 'rpe': '7'},
                }
            blueprints.append({
                'exercise': ex_b4p,
                'session_block': 'B4_Principal',
                'tempo': diagnosis.prescribed_tempo,
                'rest': '150s',
                'focus': 'Fuerza estructural principal (Nomenclatura Fraccionada AM)',
                **w_b4p,
            })

        # 5. B4_Accesorio (respeta Candado de Empuje y Regla de Composición Corporal RIR 3-4)
        ex_b4a = _pick('B4_Accesorio', day_num - 1)
        if ex_b4a and phase_type != 'fight_week':
            blueprints.append({
                'exercise': ex_b4a,
                'session_block': 'B4_Accesorio',
                'tempo': diagnosis.prescribed_tempo,
                'rest': '90s',
                'focus': (
                    'Tracción y estabilidad escapular (Candado de Empuje activo)'
                    if diagnosis.push_lock_active
                    else 'Fuerza estructural accesoria'
                ),
                'w1': {'sets': '3', 'reps': '6', 'rir': '3', 'rpe': '7'},
                'w2': {'sets': '3', 'reps': '6', 'rir': '2', 'rpe': '8'},
                'w3': {'sets': '3', 'reps': '5', 'rir': '2', 'rpe': '8'},
                'w4': {'sets': '2', 'reps': '5', 'rir': '4', 'rpe': '6'},
            })

        # 6. B4_Auxiliar (Cuello / Core anti-movimiento)
        ex_b4x = _pick('B4_Auxiliar', day_num - 1)
        if ex_b4x and phase_type != 'fight_week':
            blueprints.append({
                'exercise': ex_b4x,
                'session_block': 'B4_Auxiliar',
                'tempo': 'Isométrico / Controlado',
                'rest': '60s',
                'focus': 'Blindaje cervical y transmisión de fuerzas en core',
                'w1': {'sets': '2', 'reps': '10', 'rir': '3', 'rpe': '7'},
                'w2': {'sets': '3', 'reps': '10', 'rir': '3', 'rpe': '7'},
                'w3': {'sets': '3', 'reps': '8', 'rir': '3', 'rpe': '7'},
                'w4': {'sets': '2', 'reps': '8', 'rir': '4', 'rpe': '6'},
            })

        # 7. B5_Cardio (Sistemas Energéticos según Módulo 6 Doble Wingate)
        ex_b5 = _pick('B5_Cardio', day_num - 1)
        if ex_b5:
            b5_w1 = diagnosis.b5_prescription_for_phase(phase_type, week_num=1)
            b5_w2 = diagnosis.b5_prescription_for_phase(phase_type, week_num=2)
            b5_w3 = diagnosis.b5_prescription_for_phase(phase_type, week_num=3)
            b5_w4 = diagnosis.b5_prescription_for_phase(phase_type, week_num=4)
            blueprints.append({
                'exercise': ex_b5,
                'session_block': 'B5_Cardio',
                'tempo': 'Específico ESD',
                'rest': b5_w1['rest'],
                'focus': b5_w1['focus'],
                'notes': b5_w1['notes'],
                'w1': {'sets': b5_w1['sets'], 'reps': b5_w1['reps'], 'rir': '', 'rpe': b5_w1['rpe']},
                'w2': {'sets': b5_w2['sets'], 'reps': b5_w2['reps'], 'rir': '', 'rpe': b5_w2['rpe']},
                'w3': {'sets': b5_w3['sets'], 'reps': b5_w3['reps'], 'rir': '', 'rpe': b5_w3['rpe']},
                'w4': {'sets': b5_w4['sets'], 'reps': b5_w4['reps'], 'rir': '', 'rpe': b5_w4['rpe']},
            })

        return blueprints

    @classmethod
    def _resolve_hybrid_load(
        cls,
        athlete,
        exercise: Exercise,
        session_block: str,
        week_num: int,
        diagnosis: AMClinicalDiagnosis,
    ) -> tuple[str, str, bool]:
        """
        Calcula la carga objetivo combinando:
          - Módulo 2 (Cortocircuito de Novato): bloquea % y usa autorregulación por RIR/RPE.
          - Predictor ML de la aplicación (`predict_next_load`) cuando hay historial o modelo.
          - Marcas e1RM del atleta (Módulo 3) escaladas por semana (S1 78%, S2 82%, S3 85%, S4 75%).
        """
        if session_block in ('B1_Movilidad', 'B2_Velocidad', 'B5_Cardio'):
            return '', '', False

        if diagnosis.is_novice_shortcircuit or not diagnosis.uses_percentage_loads:
            return (
                'Autorregulado RIR',
                'Módulo 2 (Edad Entrenamiento = 0): carga por RIR/RPE sin porcentajes.',
                False,
            )

        previous_sets = list(
            LoggedSet.objects.filter(
                logged_exercise__workout_session__athlete=athlete,
                logged_exercise__planned_exercise__exercise=exercise,
            ).order_by('completed_at')[:10]
        )
        ml_pred = predict_next_load(athlete, exercise, previous_sets)
        week_factor = {1: 0.97, 2: 1.00, 3: 1.03, 4: 0.90}.get(min(week_num, 4), 1.0)

        if ml_pred.get('suggested_weight_kg', 0) > 0:
            w_kg = round(float(ml_pred['suggested_weight_kg']) * week_factor, 1)
            return (
                f"{w_kg} kg",
                f"Carga sugerida por ML ({ml_pred['source']}): {ml_pred['recommendation_note']}",
                True,
            )

        # Fallback determinista desde las marcas e1RM validadas (Módulo 3)
        pct_by_week = {1: 0.78, 2: 0.82, 3: 0.85, 4: 0.74}.get(min(week_num, 4), 0.78)
        ref_e1rm = None
        if exercise.patron_vector in ('Dominante_Rodilla', 'Dominante_Cadera', 'Triple_Extension'):
            ref_e1rm = diagnosis.squat_e1rm_kg
        elif exercise.patron_vector in ('Empuje_Horizontal', 'Empuje_Vertical'):
            ref_e1rm = diagnosis.bench_e1rm_kg
        elif exercise.patron_vector in ('Traccion_Vertical', 'Traccion_Horizontal'):
            ref_e1rm = diagnosis.pullup_e1rm_kg

        if ref_e1rm and session_block == 'B4_Principal':
            w_kg = round((ref_e1rm * pct_by_week) / 2.5) * 2.5
            return (
                f"{w_kg:.1f} kg",
                f"Módulo 3 e1RM ({int(pct_by_week * 100)}% de {ref_e1rm} kg) + ML ({ml_pred['source']}).",
                True,
            )

        return 'Según RIR pautado', f"Guía ML ({ml_pred['source']}): {ml_pred['recommendation_note']}", True

    @staticmethod
    def _build_llm_payload(
        triage: MMATriageProfile,
        diagnosis: AMClinicalDiagnosis,
        pools: dict[str, list[Exercise]],
        days_per_week: int,
    ) -> dict[str, Any]:
        allowed_exercises = [
            {
                'exercise_id': ex.id,
                'code': ex.code,
                'name': ex.name,
                'session_block': block_key,
                'patron_vector': ex.patron_vector,
                'lock_route': ex.lock_route,
                'contractile_regime': ex.contractile_regime,
            }
            for block_key, ex_list in pools.items()
            for ex in ex_list
        ]
        return {
            'athlete': {
                'fasting_weight_kg': float(triage.fasting_weight_kg or 0),
                'target_weight_category_kg': float(triage.target_weight_category_kg or 0),
                'tactical_style': triage.tactical_style,
                'body_composition_goal': triage.body_composition_goal,
                'days_per_week': days_per_week,
            },
            'diagnosis': {
                'active_phase_type': diagnosis.active_phase_type,
                'active_subphase': diagnosis.active_subphase,
                'training_age': diagnosis.training_age,
                'is_novice_shortcircuit': diagnosis.is_novice_shortcircuit,
                'olympic_lock_open': diagnosis.olympic_lock_open,
                'push_lock_active': diagnosis.push_lock_active,
                'medball_rfd_transfer_active': diagnosis.medball_rfd_transfer_active,
                'eccentric_lock_active': diagnosis.eccentric_lock_active,
                'wingate_profile': diagnosis.wingate_profile,
                'isa_archetype': diagnosis.isa_archetype,
                'active_rules_log': diagnosis.active_rules_log,
            },
            'prompt_override_privado': diagnosis.private_clinical_notes,
            'allowed_exercises': allowed_exercises,
        }

    @staticmethod
    def _extract_valid_llm_block_items(
        llm_plan: dict[str, Any] | None,
        block_number: int,
        allowed_by_id: dict[int, Exercise],
    ) -> list[dict[str, Any]]:
        """
        Valida que el JSON devuelto por un LLM externo referencie únicamente ejercicios
        existentes dentro del catálogo cerrado pre-filtrado (`allowed_by_id`).
        """
        if not llm_plan or not isinstance(llm_plan.get('blocks'), list):
            return []
        target_block = next(
            (b for b in llm_plan['blocks'] if int(b.get('block_number', 0)) == block_number),
            None,
        )
        if not target_block or not isinstance(target_block.get('items'), list):
            return []

        valid_items = []
        for raw_item in target_block['items']:
            try:
                ex_id = int(raw_item.get('exercise_id'))
            except (TypeError, ValueError):
                continue
            ex = allowed_by_id.get(ex_id)
            if ex is None:
                # Prohibido inventar o inyectar ejercicios fuera del pool filtrado
                continue
            valid_items.append({
                'exercise': ex,
                'session_block': raw_item.get('session_block') or ex.session_block or 'B4_Principal',
                'day_number': int(raw_item.get('day_number', 1)),
                'order': int(raw_item.get('order', 1)),
                'tempo': raw_item.get('tempo', ''),
                'rest': raw_item.get('rest', '90s'),
                'focus': raw_item.get('focus', ''),
                'notes': raw_item.get('notes', ''),
                'w1': raw_item.get('w1') or {},
                'w2': raw_item.get('w2') or {},
                'w3': raw_item.get('w3') or {},
                'w4': raw_item.get('w4') or {},
            })
        return valid_items
