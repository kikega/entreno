from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from training.am_macrocycle import (
    build_mesocycle_matrix,
    format_am_fractional_intensity,
    format_am_series_prescription,
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
from users.models import AthleteProfile, TrainerProfile

User = get_user_model()


class SistemaAMPhase3MacrocycleTests(TestCase):
    """
    Suite integral de pruebas de la Fase 3 del Sistema AM (V2.1):
    - Arquitectura de Macrociclo en 4 bloques competitivos (sin nomenclatura ATR).
    - Publicación progresiva bloque a bloque (`Panel_Control` -> `Entrenamiento_Activo`).
    - Aislamiento estricto de bloques no publicados y notas privadas del entrenador.
    - Nomenclatura Fraccionada de Intensidad (`3(6) @ RPE 7`, `3 Series x 3(5) @ RPE 8`).
    - Regla fisiológica de accesorios en Mantenimiento / Corte de Peso (fuerza RIR 3-4, ej. `5(9) @ RPE 6`).
    - Matriz de 4 semanas con sombreado de series inactivas en descarga (Tapering) y recálculo no destructivo.
    """

    def setUp(self):
        self.trainer_user = User.objects.create_user(
            email='jorge.am@test.com',
            password='Password123!',
            first_name='Jorge',
            last_name='Alcaraz',
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        self.other_trainer_user = User.objects.create_user(
            email='ajeno.coach@test.com',
            password='Password123!',
            first_name='Coach',
            last_name='Ajeno',
        )
        self.other_trainer = TrainerProfile.objects.create(user=self.other_trainer_user)

        self.fighter_user = User.objects.create_user(
            email='fighter.mma@test.com',
            password='Password123!',
            first_name='Ilia',
            last_name='Fighter',
        )
        self.fighter = AthleteProfile.objects.create(
            user=self.fighter_user,
            sport='mma',
            weight=74.0,
            height=175.0,
            assigned_trainer=self.trainer_user,
            trainer_confirmed=True,
        )

        self.triage = MMATriageProfile.objects.create(
            athlete=self.fighter,
            fasting_weight_kg=74.0,
            target_weight_category_kg=70.3,
            next_fight_date=date.today() + timedelta(days=56),
            body_composition_goal='corte_peso',
            available_days_per_week=3,
            accepted_terms_of_service=True,
            accepted_privacy_policy=True,
            accepted_medical_waiver=True,
            approved_for_generation=True,
            review_status='aprobado',
        )

        self.ex_mobility = Exercise.objects.create(
            code='B1_010',
            name='90/90 Cadera Activa',
            category='movilidad',
            session_block='B1_Movilidad',
        )
        self.ex_main = Exercise.objects.create(
            code='B4P_010',
            name='Zercher Squat desde Pines',
            category='fuerza',
            movement_pattern='dominante_rodilla',
            session_block='B4_Principal',
        )
        self.ex_accessory = Exercise.objects.create(
            code='B4A_010',
            name='Remo con Mancuerna Apoyado',
            category='fuerza',
            movement_pattern='traccion_horizontal',
            session_block='B4_Accesorio',
        )
        self.ex_esd = Exercise.objects.create(
            code='B5_010',
            name='AirBike RSS-P Aláctico',
            category='velocidad',
            session_block='B5_Cardio',
        )

    def test_macrocycle_init_creates_four_official_am_blocks_without_atr(self):
        """Inicializar un macrociclo crea los 4 bloques oficiales del Sistema AM con 4 semanas y en borrador oculto."""
        self.client.force_login(self.trainer_user)
        res = self.client.post(reverse('training:macrocycle_init', kwargs={'athlete_id': self.fighter.pk}))
        self.assertEqual(res.status_code, 302)

        macrocycle = Macrocycle.objects.get(athlete=self.fighter)
        blocks = list(macrocycle.blocks.order_by('block_number'))
        self.assertEqual(len(blocks), 4)

        expected_phases = ['off_season', 'pre_camp', 'training_camp', 'fight_week']
        self.assertEqual([b.phase_type for b in blocks], expected_phases)

        for b in blocks:
            self.assertEqual(b.weeks_count, 4)
            self.assertEqual(b.sessions_per_week, 3)
            self.assertFalse(b.is_published)
            for forbidden_atr in ('acumulación', 'transformación', 'realización', 'atr'):
                self.assertNotIn(forbidden_atr, b.title.lower())
                self.assertNotIn(forbidden_atr, b.get_phase_type_display().lower())

    def test_progressive_publication_strictly_isolates_unpublished_blocks_from_athlete(self):
        """
        Los bloques con `is_published=False` son 100 % invisibles e inaccesibles para el deportista
        en su panel, detalle de sesión, modo en vivo y vista `Entrenamiento_Activo`.
        """
        macrocycle = Macrocycle.objects.create(
            name='Macrociclo Campamento',
            trainer=self.trainer,
            athlete=self.fighter,
        )
        blocks = macrocycle.initialize_four_blocks()
        block_1, block_2 = blocks[0], blocks[1]
        block_1.trainer_notes = 'SECRETO_CLINICO_BLOQUE_1_SOLO_COACH'
        block_1.save()

        plan_b1 = WorkoutPlan.objects.create(
            name='B1 Sem 1 Día 1',
            trainer=self.trainer,
            athlete=self.fighter,
            macrocycle_block=block_1,
            week_number=1,
            day_number=1,
            sport='mma',
            target_date=date.today() + timedelta(days=1),
        )
        pe_b1 = PlannedExercise.objects.create(
            workout_plan=plan_b1,
            exercise=self.ex_main,
            order=1,
            sets='3',
            reps='3',
            rir='3',
            rpe='7',
            load='110 kg',
        )
        plan_b2 = WorkoutPlan.objects.create(
            name='B2 Sem 1 Día 1 Secreto',
            trainer=self.trainer,
            athlete=self.fighter,
            macrocycle_block=block_2,
            week_number=1,
            day_number=1,
            sport='mma',
            target_date=date.today() + timedelta(days=29),
        )

        # 1. Con Bloque 1 aún sin publicar: el entrenador SÍ puede ver el plan; el atleta recibe 404/403
        self.client.force_login(self.trainer_user)
        self.assertEqual(
            self.client.get(reverse('training:plan_detail', kwargs={'pk': plan_b1.pk})).status_code,
            200,
        )

        self.client.force_login(self.fighter_user)
        home_res = self.client.get(reverse('home') + '?tab=athlete')
        self.assertEqual(home_res.status_code, 200)
        self.assertIsNone(home_res.context['active_block_summary'])
        self.assertEqual(home_res.context['visible_plans'], [])
        self.assertNotContains(home_res, 'B1 Sem 1 Día 1')

        self.assertEqual(
            self.client.get(reverse('training:plan_detail', kwargs={'pk': plan_b1.pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('training:live_workout', kwargs={'pk': plan_b1.pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse('training:log_set_htmx', kwargs={'planned_id': pe_b1.pk}),
                {'weight_kg': '110', 'reps': '3', 'rpe': '7'},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"{reverse('training:athlete_active_block')}?block={block_1.pk}").status_code,
            404,
        )

        # El atleta jamás puede publicar un bloque por su cuenta
        self.assertEqual(
            self.client.post(reverse('training:block_toggle_publish', kwargs={'block_id': block_1.pk})).status_code,
            403,
        )

        # 2. El entrenador marca `[X] Publicar Bloque 1` desde Panel_Control
        self.client.force_login(self.trainer_user)
        pub_res = self.client.post(
            reverse('training:block_toggle_publish', kwargs={'block_id': block_1.pk}),
            {'mode': 'checkbox', 'is_published': '1'},
        )
        self.assertEqual(pub_res.status_code, 302)
        block_1.refresh_from_db()
        self.assertTrue(block_1.is_published)
        self.assertIsNotNone(block_1.published_at)

        # 3. Ahora el atleta ve Bloque 1 en su panel y en Entrenamiento_Activo, pero Bloque 2 y notas privadas siguen 100 % ocultos
        self.client.force_login(self.fighter_user)
        home_after = self.client.get(reverse('home') + '?tab=athlete')
        self.assertIsNotNone(home_after.context['active_block_summary'])
        self.assertEqual(home_after.context['active_block_summary']['block'], block_1)
        self.assertContains(home_after, 'B1 Sem 1 Día 1')
        self.assertNotContains(home_after, 'B2 Sem 1 Día 1 Secreto')

        active_res = self.client.get(reverse('training:athlete_active_block'))
        self.assertEqual(active_res.status_code, 200)
        self.assertContains(active_res, block_1.title)
        self.assertContains(active_res, '3 Series x 3(6) @ RPE 7')
        self.assertNotContains(active_res, 'SECRETO_CLINICO_BLOQUE_1_SOLO_COACH')
        self.assertNotContains(active_res, block_2.title)

        # Intentar forzar por URL el Bloque 2 no publicado devuelve 404
        self.assertEqual(
            self.client.get(f"{reverse('training:athlete_active_block')}?block={block_2.pk}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('training:plan_detail', kwargs={'pk': plan_b2.pk})).status_code,
            404,
        )

    def test_fractional_intensity_nomenclature_and_body_composition_accessory_rule(self):
        """
        Verifica la fórmula `Reps_Objetivo(Reps_Totales_Posibles) @ RPE X` y que los accesorios
        en Mantenimiento / Corte de Peso fuercen RIR 3-4 automáticamente (ej. `5(9) @ RPE 6`).
        """
        self.assertEqual(format_am_fractional_intensity('3', '3', '7'), '3(6) @ RPE 7')
        self.assertEqual(format_am_fractional_intensity('6', '2', '8'), '6(8) @ RPE 8')
        self.assertEqual(format_am_series_prescription('3', '3', '2', '8'), '3 Series x 3(5) @ RPE 8')
        self.assertEqual(format_am_series_prescription('2', '2', '3', '7'), '2 Series x 2(5) @ RPE 7')
        # Prescripciones por tiempo o lado (B1/B5) no generan fracciones numéricas inválidas
        self.assertEqual(format_am_fractional_intensity('8/lado', '', ''), '')

        plan = WorkoutPlan.objects.create(
            name='Sesión Fuerza MMA',
            trainer=self.trainer,
            athlete=self.fighter,  # triage.body_composition_goal == 'corte_peso'
            sport='mma',
            target_date=date.today(),
        )

        # 1. Ejercicio Principal B4_Principal en corte de peso: conserva RIR 2 (@ RPE 8) neural
        pe_main = PlannedExercise.objects.create(
            workout_plan=plan,
            exercise=self.ex_main,
            order=1,
            sets='3',
            reps='3',
            rir='2',
            rpe='8',
            load='120 kg',
        )
        self.assertEqual(pe_main.am_fractional_intensity, '3(5) @ RPE 8')
        self.assertEqual(pe_main.am_series_prescription, '3 Series x 3(5) @ RPE 8')

        # 2. Ejercicio Accesorio B4_Accesorio en corte de peso con intento cercano al fallo (RIR 1 / RPE 9):
        #    se corrige automáticamente a RIR 4 / RPE 6 -> `5(9) @ RPE 6`
        pe_acc_cut = PlannedExercise.objects.create(
            workout_plan=plan,
            exercise=self.ex_accessory,
            order=2,
            sets='3',
            reps='5',
            rir='1',
            rpe='9',
            load='32 kg',
        )
        self.assertEqual(pe_acc_cut.rir, '4')
        self.assertEqual(pe_acc_cut.rpe, '6')
        self.assertEqual(pe_acc_cut.am_fractional_intensity, '5(9) @ RPE 6')

        # 3. En Mantenimiento también fuerza RIR 3-4 (ej. RIR 3 @ RPE 7)
        self.triage.body_composition_goal = 'mantenimiento'
        self.triage.save()
        pe_acc_maint = PlannedExercise.objects.create(
            workout_plan=plan,
            exercise=self.ex_accessory,
            order=3,
            sets='3',
            reps='6',
            rir='0',
            rpe='10',
        )
        self.assertEqual(pe_acc_maint.rir, '3')
        self.assertEqual(pe_acc_maint.rpe, '7')
        self.assertEqual(pe_acc_maint.am_fractional_intensity, '6(9) @ RPE 7')

        # 4. En Ganancia Muscular (Off-Season) permite RIR 2 @ RPE 8 sin capar
        self.triage.body_composition_goal = 'ganancia_muscular'
        self.triage.save()
        pe_acc_gain = PlannedExercise.objects.create(
            workout_plan=plan,
            exercise=self.ex_accessory,
            order=4,
            sets='3',
            reps='8',
            rir='2',
            rpe='8',
        )
        self.assertEqual(pe_acc_gain.am_fractional_intensity, '8(10) @ RPE 8')

    def test_mesocycle_matrix_concurrent_ordering_tapering_locks_and_nondestructive_guard(self):
        """
        Verifica:
        1. Orden concurrente B1 -> B4_Principal -> B4_Accesorio -> B5_Cardio en la matriz.
        2. Celdas sombreadas/bloqueadas (`is_locked=True`) en semanas de descarga (2 series vs 4 series).
        3. Protección no destructiva: recalcular o re-pautar jamás sobrescribe la Semana 1 con `LoggedSet`.
        """
        macrocycle = Macrocycle.objects.create(
            name='Macrociclo Tapering Test',
            trainer=self.trainer,
            athlete=self.fighter,
        )
        block_3 = macrocycle.initialize_four_blocks()[2]  # Bloque 3 — Training Camp
        block_3.set_published(True)

        self.client.force_login(self.trainer_user)
        prescribe_url = reverse('training:block_prescribe_exercise', kwargs={'block_id': block_3.pk})

        # Pautamos primero B5 y luego B1 y B4 para comprobar que la matriz los ordena como B1 -> B4 -> B5
        self.client.post(prescribe_url, {
            'exercise': self.ex_esd.pk,
            'day_number': 1,
            'order': 1,
            'w1_sets': '6', 'w1_reps': '8s', 'w1_rir': '', 'w1_rpe': '',
            'w2_sets': '6', 'w2_reps': '8s', 'w2_rir': '', 'w2_rpe': '',
            'w3_sets': '5', 'w3_reps': '8s', 'w3_rir': '', 'w3_rpe': '',
            'w4_sets': '4', 'w4_reps': '8s', 'w4_rir': '', 'w4_rpe': '',
        })
        self.client.post(prescribe_url, {
            'exercise': self.ex_main.pk,
            'day_number': 1,
            'order': 1,
            'w1_sets': '3', 'w1_reps': '3', 'w1_rir': '2', 'w1_rpe': '8', 'w1_load': '115 kg',
            'w2_sets': '4', 'w2_reps': '3', 'w2_rir': '2', 'w2_rpe': '8', 'w2_load': '120 kg',
            'w3_sets': '2', 'w3_reps': '2', 'w3_rir': '3', 'w3_rpe': '7', 'w3_load': '120 kg',
            'w4_sets': '2', 'w4_reps': '2', 'w4_rir': '3', 'w4_rpe': '7', 'w4_load': '115 kg',
        })
        self.client.post(prescribe_url, {
            'exercise': self.ex_mobility.pk,
            'day_number': 1,
            'order': 1,
            'w1_sets': '2', 'w1_reps': '8/lado', 'w1_rir': '', 'w1_rpe': '',
        })

        matrix = build_mesocycle_matrix(block_3, day_number=1)
        self.assertEqual(
            [r['session_block'] for r in matrix['rows']],
            ['B1_Movilidad', 'B4_Principal', 'B5_Cardio'],
        )

        # En Zercher Squat: max_sets = 4 (Semana 2 tiene 4 series), Semana 3 y 4 tienen 2 series -> S3 y S4 bloqueadas
        main_row = matrix['rows'][1]
        self.assertEqual(main_row['max_sets'], 4)
        w3_cell = main_row['cells'][2]
        self.assertEqual(w3_cell['prescription'], '2 Series x 2(5) @ RPE 7')
        self.assertEqual([s['is_locked'] for s in w3_cell['set_slots']], [False, False, True, True])

        # El atleta registra una serie real en la Semana 1
        w1_plan = WorkoutPlan.objects.get(macrocycle_block=block_3, week_number=1, day_number=1)
        w1_pe = PlannedExercise.objects.get(workout_plan=w1_plan, exercise=self.ex_main)
        session = WorkoutSession.objects.create(workout_plan=w1_plan, athlete=self.fighter)
        logged_ex = LoggedExercise.objects.create(workout_session=session, planned_exercise=w1_pe)
        LoggedSet.objects.create(logged_exercise=logged_ex, set_number=1, reps=3, weight_kg=117.5, rpe=7.5)

        # Ahora el entrenador re-pauta una nueva progresión cambiando cargas/series:
        # La Semana 1 (con LoggedSet) debe quedar 100 % INTACTA, mientras Semanas 2-4 se actualizan
        self.client.post(prescribe_url, {
            'exercise': self.ex_main.pk,
            'day_number': 1,
            'order': 1,
            'w1_sets': '5', 'w1_reps': '5', 'w1_rir': '1', 'w1_rpe': '9', 'w1_load': '999 kg',
            'w2_sets': '3', 'w2_reps': '2', 'w2_rir': '3', 'w2_rpe': '7', 'w2_load': '122.5 kg',
            'w3_sets': '2', 'w3_reps': '2', 'w3_rir': '3', 'w3_rpe': '7', 'w3_load': '122.5 kg',
            'w4_sets': '2', 'w4_reps': '2', 'w4_rir': '4', 'w4_rpe': '6', 'w4_load': '110 kg',
        })

        w1_pe.refresh_from_db()
        self.assertEqual(w1_pe.load, '115 kg')
        self.assertEqual(w1_pe.sets, '3')
        self.assertEqual(LoggedSet.objects.filter(logged_exercise=logged_ex).count(), 1)

        w2_plan = WorkoutPlan.objects.get(macrocycle_block=block_3, week_number=2, day_number=1)
        w2_pe = PlannedExercise.objects.get(workout_plan=w2_plan, exercise=self.ex_main)
        self.assertEqual(w2_pe.load, '122.5 kg')
        self.assertEqual(w2_pe.am_series_prescription, '3 Series x 2(5) @ RPE 7')

        # Y `clear_unlogged_future_weeks(from_week=1)` protege Semana 1 y solo limpia Semanas 2-4 no registradas
        result = block_3.clear_unlogged_future_weeks(from_week=1)
        self.assertEqual(result['preserved'], 1)
        self.assertEqual(result['deleted'], 3)
        self.assertTrue(WorkoutPlan.objects.filter(pk=w1_plan.pk).exists())
        self.assertEqual(LoggedSet.objects.filter(logged_exercise=logged_ex).count(), 1)

    def test_foreign_trainer_cannot_access_or_mutate_macrocycle(self):
        """Un entrenador ajeno recibe 404 en todas las vistas de macrociclo y bloques de otro entrenador."""
        macrocycle = Macrocycle.objects.create(
            name='Macrociclo Privado',
            trainer=self.trainer,
            athlete=self.fighter,
        )
        block_1 = macrocycle.initialize_four_blocks()[0]

        self.client.force_login(self.other_trainer_user)
        self.assertEqual(
            self.client.post(reverse('training:macrocycle_init', kwargs={'athlete_id': self.fighter.pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('training:macrocycle_control', kwargs={'pk': macrocycle.pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse('training:block_toggle_publish', kwargs={'block_id': block_1.pk})).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse('training:block_prescribe_exercise', kwargs={'block_id': block_1.pk})).status_code,
            404,
        )
