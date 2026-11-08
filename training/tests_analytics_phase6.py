"""
Tests de Integración de la Fase 6 — Sistema AM (Jorge Alcaraz Montenegro):
  1. `Registro_Historico` (`build_am_historical_ledger`):
     - Trazabilidad de series reales (Tonelaje, 1RM Brzycki, sRPE), Semáforo de Disposición (1-5),
       sustituciones del Árbol de Dolor Articular (Opción A / Opción B) y filas explícitas `OMITIDO_POR_LESION`.
  2. `Dashboard_Visual` (`build_am_visual_dashboard`):
     - KPIs de Carga Interna/Externa (ACWR, Tonelaje, sRPE medio, % Semáforo Verde, telemetría articular,
       ondulación semanal, tabla de récords 1RM y adherencia de bloques del Macrociclo).
  3. Vistas, Exportación CSV compatible con Excel y Control de Acceso (RBAC):
     - `am_visual_dashboard`, `my_am_visual_dashboard` y `export_am_historical_csv` accesibles solo al
       entrenador asignado y al propio deportista (`404` para terceros).
  4. Retroalimentación del Pipeline ML (`predict_next_load` y `build_supervised_dataset`):
     - Ajuste protector de carga cuando la sesión previa registró molestia articular o Semáforo Nivel 1-2,
       y atribución de series al ejercicio activo ejecutado (`active_exercise`).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from training.analytics import build_am_historical_ledger, build_am_visual_dashboard
from training.ml.build_dataset import build_supervised_dataset
from training.ml.predict import predict_next_load
from training.models import (
    AthleteProfile,
    Exercise,
    LoggedExercise,
    LoggedSet,
    Macrocycle,
    PlannedExercise,
    TrainerProfile,
    WorkoutPlan,
    WorkoutSession,
)

User = get_user_model()


class AnalyticsAndHistoricalLedgerPhase6Tests(TestCase):
    def setUp(self):
        self.trainer_user = User.objects.create_user(
            email="coach.phase6@am.test",
            password="Password123!",
            first_name="Jorge",
            last_name="Coach",
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        self.other_trainer_user = User.objects.create_user(
            email="other.coach6@am.test",
            password="Password123!",
            first_name="Otro",
            last_name="Coach",
        )
        self.other_trainer = TrainerProfile.objects.create(user=self.other_trainer_user)

        self.athlete_user = User.objects.create_user(
            email="fighter.phase6@am.test",
            password="Password123!",
            first_name="Carlos",
            last_name="MMA",
        )
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user,
            assigned_trainer=self.trainer_user,
            sport="mma",
            weight=77.0,
            height=178.0,
        )

        # Ejercicios
        self.ex_iso_a = Exercise.objects.create(
            code="ISO_A_P6",
            name="Isopush Sentadilla en Pines",
            category="fuerza",
            movement_pattern="dominante_rodilla",
            session_block="B4_Principal",
        )
        self.ex_squat = Exercise.objects.create(
            code="SQ_MAIN_P6",
            name="Sentadilla Trasera Barra Alta",
            category="fuerza",
            movement_pattern="dominante_rodilla",
            session_block="B4_Principal",
            regression_option_a=self.ex_iso_a,
        )
        self.ex_press = Exercise.objects.create(
            code="BP_MAIN_P6",
            name="Press Militar de Pie",
            category="fuerza",
            movement_pattern="empuje_vertical",
            session_block="B4_Accesorio",
        )

        # Macrociclo y Bloque 1
        self.macrocycle = Macrocycle.objects.create(
            name="Macrociclo Fase 6",
            trainer=self.trainer,
            athlete=self.athlete,
            is_active=True,
        )
        self.macrocycle.initialize_four_blocks(weeks_per_block=4, sessions_per_week=3)
        self.block1 = self.macrocycle.blocks.get(block_number=1)
        self.block1.set_published(True)

        self.plan_w1 = WorkoutPlan.objects.create(
            name="Bloque 1 · Semana 1 · Día 1",
            trainer=self.trainer,
            athlete=self.athlete,
            macrocycle_block=self.block1,
            week_number=1,
            day_number=1,
            target_date=timezone.now().date(),
            is_completed=True,
        )
        self.pe_squat = PlannedExercise.objects.create(
            workout_plan=self.plan_w1,
            exercise=self.ex_squat,
            session_block="B4_Principal",
            order=1,
            sets="3",
            reps="5",
            rir="2",
            rpe="8",
            load="120 kg",
        )
        self.pe_press = PlannedExercise.objects.create(
            workout_plan=self.plan_w1,
            exercise=self.ex_press,
            session_block="B4_Accesorio",
            order=2,
            sets="3",
            reps="8",
            rir="3",
            rpe="7",
            load="50 kg",
        )

        # Sesión con Semáforo Nivel 2 (Esquema_Fatiga)
        self.session_w1 = WorkoutSession.objects.create(
            workout_plan=self.plan_w1,
            athlete=self.athlete,
            readiness_level=2,
            duration_minutes=60,
            session_rpe=7.5,
        )

        # Ejercicio 1: ejecutado con Opción A (Isopush) y 2 series registradas
        self.logged_squat = LoggedExercise.objects.create(
            workout_session=self.session_w1,
            planned_exercise=self.pe_squat,
            pain_status="option_a",
            substituted_exercise=self.ex_iso_a,
        )
        self.set1 = LoggedSet.objects.create(
            logged_exercise=self.logged_squat,
            set_number=1,
            weight_kg=100.0,
            reps=5,
            rpe=7.5,
        )
        self.set2 = LoggedSet.objects.create(
            logged_exercise=self.logged_squat,
            set_number=2,
            weight_kg=105.0,
            reps=5,
            rpe=8.0,
        )

        # Ejercicio 2: OMITIDO_POR_LESION (0 series)
        self.logged_press = LoggedExercise.objects.create(
            workout_session=self.session_w1,
            planned_exercise=self.pe_press,
            pain_status="omitted_injury",
        )

    def test_historical_ledger_tracks_substitutions_omissions_tonnage_and_1rm(self):
        """
        `build_am_historical_ledger` devuelve las series con su tonelaje, 1RM Brzycki,
        ejercicio sustituido (`Isopush Sentadilla en Pines`) y fila explícita `OMITIDO_POR_LESION`.
        """
        ledger = build_am_historical_ledger(self.athlete)
        self.assertEqual(len(ledger), 3)  # 2 series de sentadilla + 1 fila de omisión por lesión

        squat_rows = [r for r in ledger if r["prescribed_exercise"] == self.ex_squat.name]
        self.assertEqual(len(squat_rows), 2)
        self.assertEqual(squat_rows[0]["executed_exercise"], self.ex_iso_a.name)
        self.assertEqual(squat_rows[0]["pain_status"], "option_a")
        self.assertEqual(squat_rows[0]["readiness_level"], 2)
        self.assertEqual(squat_rows[0]["readiness_scheme"], "Esquema_Fatiga")
        self.assertEqual(squat_rows[0]["tonnage_kg"], 500.0)
        self.assertGreater(squat_rows[1]["est_1rm_kg"], 115.0)

        omitted_rows = [r for r in ledger if r["pain_status"] == "omitted_injury"]
        self.assertEqual(len(omitted_rows), 1)
        self.assertEqual(omitted_rows[0]["executed_exercise"], "OMITIDO_POR_LESION")
        self.assertEqual(omitted_rows[0]["set_number"], 0)

    def test_visual_dashboard_aggregates_kpis_readiness_and_pain_telemetry(self):
        """
        `build_am_visual_dashboard` calcula ACWR, tonelaje total, sRPE medio,
        conteos del Semáforo de Disposición, incidentes articulares y adherencia de bloques.
        """
        dashboard = build_am_visual_dashboard(self.athlete)
        # Tonelaje = (100*5) + (105*5) = 1025.0 kg
        self.assertEqual(dashboard["metrics"]["total_volume_kg"], 1025.0)
        # sRPE = 60 min * 7.5 = 450.0 UA
        self.assertEqual(dashboard["avg_srpe"], 450.0)
        self.assertEqual(dashboard["readiness_counts"]["yellow"], 1)
        self.assertEqual(dashboard["pain_counts"]["option_a"], 1)
        self.assertEqual(dashboard["pain_counts"]["omitted_injury"], 1)
        self.assertEqual(dashboard["pain_Swap_total"], 2)
        self.assertEqual(len(dashboard["weekly_series"]), 1)
        self.assertEqual(dashboard["weekly_series"][0]["tonnage_kg"], 1025.0)
        self.assertEqual(len(dashboard["macrocycle_adherence"]), 4)

    def test_dashboard_and_csv_export_views_and_rbac_security(self):
        """
        Tanto el entrenador asignado como el propio atleta pueden ver el `Dashboard_Visual`
        y descargar el CSV de `Registro_Historico`, pero un entrenador ajeno recibe 404.
        """
        dash_url = reverse("training:am_visual_dashboard", kwargs={"pk": self.athlete.pk})
        csv_url = reverse("training:export_am_historical_csv", kwargs={"pk": self.athlete.pk})

        # 1. Entrenador asignado -> 200 OK
        self.client.force_login(self.trainer_user)
        res_trainer = self.client.get(dash_url)
        self.assertEqual(res_trainer.status_code, 200)
        self.assertContains(res_trainer, "1025")
        self.assertContains(res_trainer, "Isopush Sentadilla en Pines")
        self.assertContains(res_trainer, "OMITIDO")

        res_csv = self.client.get(csv_url)
        self.assertEqual(res_csv.status_code, 200)
        self.assertIn("text/csv", res_csv["Content-Type"])
        csv_text = res_csv.content.decode("utf-8-sig")
        self.assertIn("Isopush Sentadilla en Pines", csv_text)
        self.assertIn("OMITIDO_POR_LESION", csv_text)

        # 2. Propio atleta -> 200 OK vía atajo my_am_visual_dashboard
        self.client.force_login(self.athlete_user)
        res_athlete = self.client.get(reverse("training:my_am_visual_dashboard"))
        self.assertEqual(res_athlete.status_code, 200)
        self.assertContains(res_athlete, "Registro_Historico")

        # 3. Entrenador ajeno -> 404
        self.client.force_login(self.other_trainer_user)
        self.assertEqual(self.client.get(dash_url).status_code, 404)
        self.assertEqual(self.client.get(csv_url).status_code, 404)

    def test_ml_pipeline_autoregulation_feedback_on_pain_and_low_readiness(self):
        """
        El predictor ML (`predict_next_load`) detecta si la serie previa tuvo molestia articular
        (`option_a`) o Semáforo Nivel <= 2 y aplica descarga protectora, mientras que
        `build_supervised_dataset` atribuye las series al ejercicio realmente ejecutado (`active_exercise`).
        """
        prev_sets = [self.set1, self.set2]
        pred = predict_next_load(self.athlete, self.ex_squat, prev_sets)
        # Último peso fue 105.0 kg con pain_status='option_a' -> descarga protectora (-8% -> 96.6 kg)
        self.assertLess(pred["suggested_weight_kg"], 105.0)
        self.assertIn("Autoregulación AM", pred["recommendation_note"])

        rows, targets = build_supervised_dataset()
        self.assertEqual(len(rows), 2)
        self.assertEqual(targets, [100.0, 105.0])
