"""
Tests de Fase 4 — Motor de Reglas Algorítmicas (8 Módulos del Sistema AM V2.1),
Integración con el Predictor ML de la Aplicación y Conector LLM Opcional vía `.env`.
"""

from datetime import timedelta
import io
import json
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from training.am_rules_engine import (
    AMMacrocycleGenerator,
    AMUniversalLLMClient,
    evaluate_am_rules,
    filter_am_catalog_for_diagnosis,
)
from training.models import (
    Exercise,
    LoggedExercise,
    LoggedSet,
    Macrocycle,
    MacrocycleBlock,
    MMATriageProfile,
    PlannedExercise,
    WorkoutPlan,
    WorkoutSession,
)
from users.models import AthleteProfile, CustomUser, TrainerProfile


def _seed_am_master_catalog() -> dict[str, Exercise]:
    """Crea un catálogo completo representativo de `BD_Maestra_Ejercicios` para todos los bloques."""
    b1_narrow = Exercise.objects.create(
        code='B1_001',
        name='Respiración Cocodrilo + Rotación Torácica',
        category='movilidad',
        session_block='B1_Movilidad',
        patron_vector='Rotacional_Core',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=[],
        isa_tag='ISA_Estrecho',
        contractile_regime='Dinamico_Estandar',
        compromised_joint='Ninguna',
    )
    b1_wide = Exercise.objects.create(
        code='B1_002',
        name='90/90 Hip Switch con Exhalación Oblicua',
        category='movilidad',
        session_block='B1_Movilidad',
        patron_vector='Rotacional_Core',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=[],
        isa_tag='ISA_Ancho',
        contractile_regime='Dinamico_Estandar',
        compromised_joint='Ninguna',
    )
    b1_univ = Exercise.objects.create(
        code='B1_003',
        name='Movilidad Escapular y Bisagra Universal',
        category='movilidad',
        session_block='B1_Movilidad',
        patron_vector='Rotacional_Core',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=[],
        isa_tag='Universal',
        contractile_regime='Dinamico_Estandar',
        compromised_joint='Ninguna',
    )

    b2_medball = Exercise.objects.create(
        code='B2_001',
        name='Lanzamiento Rotacional Balón Medicinal Ligero',
        category='velocidad',
        session_block='B2_Velocidad',
        patron_vector='Rotacional_Core',
        lock_route='Candado_Balon_Ligero',
        complexity_level='Nivel_1_Base',
        required_equipment=['Balones medicinales LIGEROS (<= 6 kg)'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Hombros',
    )
    b2_jump = Exercise.objects.create(
        code='B2_002',
        name='Salto al Cajón Reactivo Concéntrico',
        category='pliometria',
        session_block='B2_Velocidad',
        patron_vector='Triple_Extension',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Cajón pliométrico'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Ninguna',
    )

    b3_olympic = Exercise.objects.create(
        code='B3_001',
        name='Hang Power Clean (Cargada Colgado)',
        category='potencia',
        session_block='B3_Potencia',
        patron_vector='Triple_Extension',
        lock_route='Candado_Olimpico_R1',
        complexity_level='Nivel_3_Avanzado',
        required_equipment=['Barra olímpica (20 kg) y discos'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Munecas',
    )
    b3_landmine = Exercise.objects.create(
        code='B3_002',
        name='Landmine Punch Throw Explosivo',
        category='potencia',
        session_block='B3_Potencia',
        patron_vector='Triple_Extension',
        lock_route='Ruta_Landmine_R2',
        complexity_level='Nivel_1_Base',
        required_equipment=['Landmine', 'Barra olímpica (20 kg) y discos'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Ninguna',
    )
    b3_r4 = Exercise.objects.create(
        code='B3_004',
        name='Push Press Balístico con Mancuernas (Ruta 4)',
        category='potencia',
        session_block='B3_Potencia',
        patron_vector='Empuje_Vertical',
        lock_route='Ruta_Balistica_Sup_R4',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Mancuernas'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Ninguna',
    )

    b4p_iso = Exercise.objects.create(
        code='B4P_ISO_01',
        name='Sentadilla Isométrica contra Pines (Squat Isopush)',
        category='fuerza',
        session_block='B4_Principal',
        patron_vector='Dominante_Rodilla',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Barra olímpica (20 kg) y discos', 'Rack'],
        isa_tag='Universal',
        contractile_regime='Isopush',
        compromised_joint='Ninguna',
    )
    b4p_squat = Exercise.objects.create(
        code='B4P_001',
        name='Sentadilla Barra Alta Excéntrica Acelerada',
        category='fuerza',
        session_block='B4_Principal',
        patron_vector='Dominante_Rodilla',
        lock_route='Libre',
        complexity_level='Nivel_1_Base',
        required_equipment=['Barra olímpica (20 kg) y discos', 'Rack'],
        isa_tag='Universal',
        contractile_regime='High_Braking',
        compromised_joint='Lumbares',
        regression_option_a=b4p_iso,
    )
    b4p_hinge = Exercise.objects.create(
        code='B4P_002',
        name='Peso Muerto Trap Bar desde Pines',
        category='fuerza',
        session_block='B4_Principal',
        patron_vector='Dominante_Cadera',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Trap Bar'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Ninguna',
    )

    b4a_push = Exercise.objects.create(
        code='B4A_001',
        name='Press Inclinado con Mancuernas',
        category='fuerza',
        session_block='B4_Accesorio',
        patron_vector='Empuje_Horizontal',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Mancuernas', 'Banco plano/inclinado'],
        isa_tag='Universal',
        contractile_regime='Dinamico_Estandar',
        compromised_joint='Hombros',
    )
    b4a_pull = Exercise.objects.create(
        code='B4A_002',
        name='Remo Seal con Mancuernas en Banco',
        category='fuerza',
        session_block='B4_Accesorio',
        patron_vector='Traccion_Horizontal',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Mancuernas', 'Banco plano/inclinado'],
        isa_tag='Universal',
        contractile_regime='Dinamico_Estandar',
        compromised_joint='Ninguna',
    )

    b4x_core = Exercise.objects.create(
        code='B4X_001',
        name='Press Pallof Anti-Rotación en Polea',
        category='fuerza',
        session_block='B4_Auxiliar',
        patron_vector='Anti_Movimiento_Core',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['Bandas elásticas'],
        isa_tag='Universal',
        contractile_regime='Isohold',
        compromised_joint='Ninguna',
    )

    b5_airbike = Exercise.objects.create(
        code='B5_001',
        name='AirBike ESD Específico MMA',
        category='tactica',
        session_block='B5_Cardio',
        patron_vector='Ninguno',
        lock_route='Libre',
        complexity_level='Nivel_0_Novato',
        required_equipment=['AirBike'],
        isa_tag='Universal',
        contractile_regime='Concentrico_Propulsivo',
        compromised_joint='Ninguna',
    )

    return {
        'b1_narrow': b1_narrow,
        'b1_wide': b1_wide,
        'b1_univ': b1_univ,
        'b2_medball': b2_medball,
        'b2_jump': b2_jump,
        'b3_olympic': b3_olympic,
        'b3_landmine': b3_landmine,
        'b3_r4': b3_r4,
        'b4p_iso': b4p_iso,
        'b4p_squat': b4p_squat,
        'b4p_hinge': b4p_hinge,
        'b4a_push': b4a_push,
        'b4a_pull': b4a_pull,
        'b4x_core': b4x_core,
        'b5_airbike': b5_airbike,
    }


@pytest.fixture
def am_phase4_setup(db):
    """Inicializa entrenador, atleta MMA, catálogo maestro y ficha de Triage aprobada."""
    catalog = _seed_am_master_catalog()

    trainer_user = CustomUser.objects.create_user(
        email='jorge.phase4@entrenopro.com',
        password='Password123!',
        first_name='Jorge',
        last_name='Alcaraz',
    )
    trainer = TrainerProfile.objects.create(user=trainer_user)

    athlete_user = CustomUser.objects.create_user(
        email='fighter.phase4@entrenopro.com',
        password='Password123!',
        first_name='Ilia',
        last_name='Topuria',
    )
    athlete = AthleteProfile.objects.create(
        user=athlete_user,
        assigned_trainer=trainer_user,
        trainer_confirmed=True,
        sport='mma',
        weight=77.0,
    )

    full_equipment = list(Exercise.AM_CANONICAL_EQUIPMENT)
    triage = MMATriageProfile.objects.create(
        athlete=athlete,
        weigh_in_rule='profesional_24h',
        fasting_weight_kg=77.0,
        target_weight_category_kg=70.0,
        next_fight_date=None,  # Off-Season por defecto
        tactical_style='striker',
        body_composition_goal='mantenimiento',
        strength_experience='avanzado',
        olympic_lifts_relation='domina_motivado',
        available_days_per_week=3,
        tatami_weekly_volume='medio_6_10h',
        can_separate_block_5=False,
        available_equipment=full_equipment,
        isa_angle='neutro',
        knows_rm_marks=True,
        rm_format='1rm',
        back_squat_rm_kg=130.0,  # 1.69x BW (> 1.5x BW)
        bench_press_rm_kg=100.0,
        strict_pullup_external_load_kg=25.0,  # 77 + 25 = 102 kg -> ratio 0.98 (<= 1.15)
        wingate_modality='airbike_w',
        wingate_sprint_1=750.0,
        wingate_sprint_2=550.0,  # Drop 26.67% (> 20%)
        current_joint_pain_zones=['Ninguna'],
        par_q_has_risk=False,
        accepted_terms_of_service=True,
        accepted_privacy_policy=True,
        accepted_medical_waiver=True,
        approved_for_generation=True,
        review_status='aprobado',
    )
    return {
        'trainer_user': trainer_user,
        'trainer': trainer,
        'athlete_user': athlete_user,
        'athlete': athlete,
        'triage': triage,
        'catalog': catalog,
    }


@pytest.mark.django_db
class TestAM8ModulesEngine:
    """Verifica exhaustivamente los 8 Módulos Algorítmicos del Sistema AM (V2.1)."""

    def test_module_1_concurrent_phases_no_atr(self, am_phase4_setup):
        """Módulo 1: Cálculo de fases por semanas hasta el combate sin periodización ATR."""
        triage = am_phase4_setup['triage']
        today = timezone.now().date()

        # Sin fecha (> 12 semanas) -> Off-Season
        triage.next_fight_date = None
        diag = evaluate_am_rules(triage, reference_date=today)
        assert diag.active_phase_type == 'off_season'
        assert diag.active_subphase == 'none'

        # 10 semanas -> Pre-Training Camp
        triage.next_fight_date = today + timedelta(weeks=10)
        diag = evaluate_am_rules(triage, reference_date=today)
        assert diag.active_phase_type == 'pre_camp'

        # 6 semanas -> Training Camp (Subfase Base > 4 sem)
        triage.next_fight_date = today + timedelta(weeks=6)
        diag = evaluate_am_rules(triage, reference_date=today)
        assert diag.active_phase_type == 'training_camp'
        assert diag.active_subphase == 'base'

        # 3 semanas -> Training Camp (Subfase Tapering <= 4 sem)
        triage.next_fight_date = today + timedelta(weeks=3)
        diag = evaluate_am_rules(triage, reference_date=today)
        assert diag.active_phase_type == 'training_camp'
        assert diag.active_subphase == 'tapering'

        # 4 días -> Fight Week (< 1 sem)
        triage.next_fight_date = today + timedelta(days=4)
        diag = evaluate_am_rules(triage, reference_date=today)
        assert diag.active_phase_type == 'fight_week'

    def test_module_2_novice_shortcircuit(self, am_phase4_setup):
        """Módulo 2: Cortocircuito de Novato fija Edad_Entrenamiento=0, bloquea % y fuerza tempo 3-1-0."""
        triage = am_phase4_setup['triage']
        triage.strength_experience = 'novato'
        triage.save()

        diag = evaluate_am_rules(triage)
        assert diag.is_novice_shortcircuit is True
        assert diag.training_age == 0
        assert diag.uses_percentage_loads is False
        assert diag.prescribed_tempo == '3-1-0'
        assert diag.max_complexity_rank == 1
        assert diag.olympic_lock_open is False

        pools = filter_am_catalog_for_diagnosis(diag)
        for block_list in pools.values():
            for ex in block_list:
                assert ex.complexity_level in ('Nivel_0_Novato', 'Nivel_1_Base')
                assert ex.lock_route != 'Candado_Olimpico_R1'

    def test_module_3_olympic_lock_and_push_lock(self, am_phase4_setup):
        """Módulo 3: Candado Olímpico R1 (4 condiciones) y Candado de Empuje (> 1.15)."""
        triage = am_phase4_setup['triage']

        # Caso 1: Cumple las 4 condiciones en Off-Season -> Candado Olímpico ABIERTO
        diag_open = evaluate_am_rules(triage)
        assert diag_open.olympic_lock_open is True
        assert diag_open.b3_route == 'Candado_Olimpico_R1'
        assert diag_open.push_lock_active is False

        # Caso 2: Entra en Training Camp -> Candado Olímpico CERRADO (deriva a R2/R3)
        triage.next_fight_date = timezone.now().date() + timedelta(weeks=5)
        diag_camp = evaluate_am_rules(triage)
        assert diag_camp.olympic_lock_open is False
        assert diag_camp.b3_route in ('Ruta_Landmine_R2', 'Ruta_Salto_Lastrado_R3')

        # Caso 3: Desbalance Empuje/Tracción (Banca 125 kg vs Dominada 77+15=92 kg -> ratio 1.36 > 1.15)
        triage.bench_press_rm_kg = 125.0
        triage.strict_pullup_external_load_kg = 15.0
        diag_push = evaluate_am_rules(triage)
        assert diag_push.push_lock_active is True

        pools = filter_am_catalog_for_diagnosis(diag_push)
        for ex in pools['B4_Accesorio']:
            assert ex.patron_vector not in ('Empuje_Horizontal', 'Empuje_Vertical')

    def test_module_4_equipment_filter_and_medball_rfd_transfer(self, am_phase4_setup):
        """Módulo 4: Descarte de material ausente y transferencia RFD cuando falta balón ligero (<= 6 kg)."""
        triage = am_phase4_setup['triage']
        triage.available_equipment = [
            eq for eq in triage.available_equipment
            if eq != 'Balones medicinales LIGEROS (<= 6 kg)'
        ]
        triage.save()

        diag = evaluate_am_rules(triage)
        assert diag.has_light_medball is False
        assert diag.medball_rfd_transfer_active is True

        pools = filter_am_catalog_for_diagnosis(diag)
        assert all(ex.lock_route != 'Candado_Balon_Ligero' for ex in pools['B2_Velocidad'])
        # La Ruta 4 Balística Superior encabeza la prioridad de B3_Potencia
        assert pools['B3_Potencia'][0].lock_route == 'Ruta_Balistica_Sup_R4'

    def test_module_5_weight_cut_and_eccentric_lock(self, am_phase4_setup):
        """Módulo 5: Corte severo en Camp activa Candado Excéntrico y sustituye High_Braking por Isopush."""
        triage = am_phase4_setup['triage']
        triage.next_fight_date = timezone.now().date() + timedelta(weeks=5)
        triage.fasting_weight_kg = 79.0
        triage.target_weight_category_kg = 70.0  # 9 kg de corte (> 6 kg y > 8%)
        triage.save()

        diag = evaluate_am_rules(triage)
        assert diag.eccentric_lock_active is True

        pools = filter_am_catalog_for_diagnosis(diag)
        for block_list in pools.values():
            for ex in block_list:
                assert ex.contractile_regime not in ('High_Braking', 'Fast_Braking')
        # Verifica que `B4P_001` (High_Braking) fue sustituido automáticamente por su Opción A (`B4P_ISO_01`)
        assert any(ex.code == 'B4P_ISO_01' for ex in pools['B4_Principal'])

    def test_module_6_double_wingate_diagnosis(self, am_phase4_setup):
        """Módulo 6: Diagnóstico Doble Wingate (> 20% Drop -> LI/SI vs <= 20% Motor Diésel -> RSS-P 8"/52")."""
        triage = am_phase4_setup['triage']

        # Drop > 20% en Off-Season -> Long Intervals (LI)
        triage.next_fight_date = None
        triage.wingate_sprint_1 = 800.0
        triage.wingate_sprint_2 = 560.0  # Drop 30%
        diag_li = evaluate_am_rules(triage)
        assert diag_li.b5_protocol == 'LI'

        # Drop > 20% en Pre-Camp -> Short Intervals (SI)
        triage.next_fight_date = timezone.now().date() + timedelta(weeks=10)
        diag_si = evaluate_am_rules(triage)
        assert diag_si.b5_protocol == 'SI'

        # Drop <= 20% con S1 bajo ("Motor Diésel") -> Fuerza RSS-P (8"/52") incluso en Off-Season
        triage.next_fight_date = None
        triage.wingate_sprint_1 = 420.0
        triage.wingate_sprint_2 = 385.0  # Drop 8.3% y S1 < 520W
        diag_diesel = evaluate_am_rules(triage)
        assert diag_diesel.wingate_profile == 'motor_diesel_alactico'
        assert diag_diesel.b5_protocol == 'RSS-P'

    def test_module_7_isa_biometrics_and_vetoes(self, am_phase4_setup):
        """Módulo 7: Biometría ISA (Estrecho vs Ancho) y Vetos Biomecánicos del Entrenador."""
        triage = am_phase4_setup['triage']

        # ISA Estrecho (< 85º): B4_Principal -> Dominante_Rodilla y descarta ISA_Ancho
        triage.isa_angle = 'estrecho'
        triage.biomechanical_vetoes = ['veto_carga_axial_espinal']
        diag_narrow = evaluate_am_rules(triage)
        assert diag_narrow.b4_main_dominant_vector == 'Dominante_Rodilla'

        pools_narrow = filter_am_catalog_for_diagnosis(diag_narrow)
        for block_list in pools_narrow.values():
            for ex in block_list:
                assert ex.isa_tag != 'ISA_Ancho'
                assert ex.code != 'B4P_001'  # Vetado por carga axial espinal sobre Lumbares

        # ISA Ancho (> 95º): B4_Principal -> Dominante_Cadera y descarta ISA_Estrecho
        triage.isa_angle = 'ancho'
        triage.biomechanical_vetoes = []
        diag_wide = evaluate_am_rules(triage)
        assert diag_wide.b4_main_dominant_vector == 'Dominante_Cadera'
        pools_wide = filter_am_catalog_for_diagnosis(diag_wide)
        for block_list in pools_wide.values():
            for ex in block_list:
                assert ex.isa_tag != 'ISA_Estrecho'


@pytest.mark.django_db
class TestModule8AndHybridGeneration:
    """Verifica la generación híbrida (8 Módulos + ML vs LLM `.env`) y el Módulo 8 de Calendario."""

    def test_gatekeeper_blocks_unapproved_generation(self, am_phase4_setup):
        """El Cerrojo Manual bloquea `generate_or_recalculate_macrocycle` si `approved_for_generation=False`."""
        triage = am_phase4_setup['triage']
        triage.approved_for_generation = False
        triage.save()

        with pytest.raises(ValueError, match="Cerrojo Manual"):
            AMMacrocycleGenerator.generate_or_recalculate_macrocycle(
                triage=triage,
                trainer_profile=am_phase4_setup['trainer'],
            )

    def test_default_engine_uses_8_modules_and_ml_preserving_history(self, am_phase4_setup, client):
        """Por defecto (`AM_LLM_ENABLED=False`), genera los 4 bloques con los 8 módulos + ML sin destruir historial."""
        triage = am_phase4_setup['triage']
        trainer = am_phase4_setup['trainer']

        result = AMMacrocycleGenerator.generate_or_recalculate_macrocycle(
            triage=triage,
            trainer_profile=trainer,
        )
        assert result['engine_source'] == 'reglas_am_y_ml'
        assert result['generated_plans'] == 4 * 4 * 3  # 4 bloques * 4 semanas * 3 días
        assert result['preserved_plans'] == 0
        assert result['ml_predictions_used'] > 0

        macro = result['macrocycle']
        block1 = macro.blocks.get(block_number=1)
        w1_d1 = block1.workout_plans.get(week_number=1, day_number=1)
        session_blocks = list(w1_d1.planned_exercises.values_list('session_block', flat=True))
        # Verifica concurrencia de los 5 bloques (Módulo 1)
        assert 'B1_Movilidad' in session_blocks
        assert 'B2_Velocidad' in session_blocks
        assert 'B3_Potencia' in session_blocks
        assert 'B4_Principal' in session_blocks
        assert 'B5_Cardio' in session_blocks

        # Simulamos que el atleta completa Semana 1 Día 1 con serie real registrada
        session = WorkoutSession.objects.create(
            athlete=am_phase4_setup['athlete'],
            workout_plan=w1_d1,
        )
        first_pe = w1_d1.planned_exercises.first()
        first_pe.load = 'MARCA_HISTORICA_PROTEGIDA'
        first_pe.save()
        le = LoggedExercise.objects.create(
            workout_session=session,
            planned_exercise=first_pe,
        )
        LoggedSet.objects.create(
            logged_exercise=le,
            set_number=1,
            reps=5,
            weight_kg=110.0,
            rpe=8.0,
        )

        # Recalculamos desde el endpoint HTTP del entrenador
        client.force_login(am_phase4_setup['trainer_user'])
        resp = client.post(
            reverse('training:macrocycle_generate', kwargs={'athlete_id': am_phase4_setup['athlete'].pk})
        )
        assert resp.status_code == 302
        first_pe.refresh_from_db()
        assert first_pe.load == 'MARCA_HISTORICA_PROTEGIDA'

    @override_settings(
        AM_LLM_ENABLED=True,
        AM_LLM_PROVIDER='openai_compatible',
        AM_LLM_API_KEY='sk-test-env-key',
        AM_LLM_MODEL='gpt-4o-mini',
        AM_LLM_BASE_URL='https://api.example.com/v1/chat/completions',
    )
    def test_optional_env_llm_connector_and_closed_catalog_guard(self, am_phase4_setup):
        """
        Cuando se configura `AM_LLM_ENABLED=True` y `AM_LLM_API_KEY` en `.env`, utiliza el conector
        LLM universal validando estrictamente que ningún ejercicio salga de `BD_Maestra_Ejercicios`.
        """
        triage = am_phase4_setup['triage']
        diag = evaluate_am_rules(triage)
        pools = filter_am_catalog_for_diagnosis(diag)

        valid_b1 = pools['B1_Movilidad'][0].id
        valid_b4 = pools['B4_Principal'][0].id
        fake_invented_id = 999999  # ID inexistente / prohibido fuera del catálogo filtrado

        mock_llm_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "blocks": [
                                {
                                    "block_number": 1,
                                    "items": [
                                        {
                                            "exercise_id": valid_b1,
                                            "session_block": "B1_Movilidad",
                                            "day_number": 1,
                                            "order": 1,
                                            "w1": {"sets": "2", "reps": "8/lado", "rir": "", "rpe": "6"},
                                        },
                                        {
                                            "exercise_id": valid_b4,
                                            "session_block": "B4_Principal",
                                            "day_number": 1,
                                            "order": 2,
                                            "w1": {"sets": "4", "reps": "4", "rir": "2", "rpe": "8"},
                                        },
                                        {
                                            "exercise_id": fake_invented_id,
                                            "session_block": "B3_Potencia",
                                            "day_number": 1,
                                            "order": 3,
                                        },
                                    ],
                                }
                            ]
                        })
                    }
                }
            ]
        }

        class DummyHTTPResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch(
            'urllib.request.urlopen',
            return_value=DummyHTTPResponse(json.dumps(mock_llm_payload).encode('utf-8')),
        ):
            assert AMUniversalLLMClient.is_enabled_and_configured() is True
            res = AMMacrocycleGenerator.generate_or_recalculate_macrocycle(
                triage=triage,
                trainer_profile=am_phase4_setup['trainer'],
            )
            assert res['engine_source'] == 'llm_openai_compatible_y_ml'
            macro = res['macrocycle']
            b1 = macro.blocks.get(block_number=1)
            w1_d1 = b1.workout_plans.get(week_number=1, day_number=1)
            prescribed_ids = list(w1_d1.planned_exercises.values_list('exercise_id', flat=True))
            assert valid_b1 in prescribed_ids
            assert valid_b4 in prescribed_ids
            # El ID inventado 999999 fue rechazado de raíz por la validación contra el catálogo cerrado
            assert fake_invented_id not in prescribed_ids

    def test_module_8_dynamic_calendar_recalculation_modes(self, am_phase4_setup, client):
        """
        Módulo 8: Verifica los 4 escenarios de cambio de fecha de pelea a mitad de bloque:
          1. Adelanto a 3 semanas (S1 -> S3 -> S4 + RSS-P).
          2. Short-Notice (<= 14 días: anula B3/B4 y deja solo Priming Neural B1/B2 + RSS-P).
          3. Retraso a 5 semanas (clona Semana 2 -> S1 -> S2 -> S2 -> S3 -> S4).
          4. Retraso a 6–8 semanas (Modelo Pendular de 2 olas de 4 semanas).
        """
        triage = am_phase4_setup['triage']
        trainer = am_phase4_setup['trainer']
        res = AMMacrocycleGenerator.generate_or_recalculate_macrocycle(
            triage=triage,
            trainer_profile=trainer,
        )
        macro = res['macrocycle']
        block3 = macro.blocks.get(block_number=3)
        today = timezone.now().date()

        # 1. Adelanto a 3 semanas (21 días)
        r_3w = AMMacrocycleGenerator.recalculate_block_calendar(
            block=block3,
            new_fight_date=today + timedelta(days=21),
            triage=triage,
            reference_date=today,
        )
        block3.refresh_from_db()
        assert r_3w['mode'] == 'adelanto_3_sem'
        assert block3.weeks_count == 3
        assert set(block3.workout_plans.values_list('week_number', flat=True)) == {1, 2, 3}

        # 2. Retraso a 5 semanas (35 días): sobre Bloque 2 intacto de 4 semanas
        block2 = macro.blocks.get(block_number=2)
        r_5w = AMMacrocycleGenerator.recalculate_block_calendar(
            block=block2,
            new_fight_date=today + timedelta(days=35),
            triage=triage,
            reference_date=today,
        )
        block2.refresh_from_db()
        assert r_5w['mode'] == 'retraso_5_sem'
        assert block2.weeks_count == 5
        assert set(block2.workout_plans.values_list('week_number', flat=True)) == {1, 2, 3, 4, 5}

        # 3. Retraso a 7 semanas (49 días -> Modelo Pendular 2 olas)
        block1 = macro.blocks.get(block_number=1)
        r_pendular = AMMacrocycleGenerator.recalculate_block_calendar(
            block=block1,
            new_fight_date=today + timedelta(days=49),
            triage=triage,
            reference_date=today,
        )
        assert r_pendular['mode'] == 'pendular_2_olas_6_8_sem'

        # 4. Short-Notice <= 14 días vía endpoint HTTP del entrenador
        client.force_login(am_phase4_setup['trainer_user'])
        short_notice_date = (today + timedelta(days=10)).isoformat()
        resp = client.post(
            reverse('training:block_recalculate_calendar', kwargs={'block_id': block3.id}),
            data={'next_fight_date': short_notice_date},
        )
        assert resp.status_code == 302
        block3.refresh_from_db()
        assert block3.subphase == 'tapering'
        # En planes no completados de Short-Notice solo quedan B1_Movilidad, B2_Velocidad y B5_Cardio (RSS-P)
        remaining_blocks = set(
            PlannedExercise.objects.filter(workout_plan__macrocycle_block=block3)
            .values_list('session_block', flat=True)
        )
        assert remaining_blocks.issubset({'B1_Movilidad', 'B2_Velocidad', 'B5_Cardio'})
