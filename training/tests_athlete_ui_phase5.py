"""
Tests de Integración de la Fase 5 — Sistema AM (Jorge Alcaraz Montenegro):
  1. Semáforo de Disposición Diaria (Niveles 1 a 5):
     - Preconfigurado por defecto en Nivel 4 (Verde · Esquema_Normal).
     - Nivel 2 (Amarillo · Esquema_Fatiga): +1 serie en B1_Movilidad, B2/B3 a fluidez submáxima RPE 6,
       -1 serie y -1 RPE en accesorios B4, B5_Cardio a Zona 2 regenerativa + alerta al entrenador.
     - Nivel 1 (Rojo · Esquema_Regenerativo): suprime al 100 % B2_Velocidad y B3_Potencia (bloqueando series),
       convierte B4 en bombeo regenerativo RIR 5-6 y B5_Cardio en Zona 2 sin impacto + alerta al entrenador.
  2. Árbol Autónomo de Sustitución por Dolor Articular (`⚠️ Molestia`):
     - Transición normal -> option_a (Isométrica) -> option_b (Cambio de Vector) -> omitted_injury (`OMITIDO_POR_LESION`),
       actualizando ejercicio activo y vídeo en tiempo real, bloqueando series en `omitted_injury` y notificando al entrenador.
  3. Bloqueo Visual y Funcional de Series en Descarga/Tapering:
     - Celdas `⬛` bloqueadas cuando la semana tiene menos series que el máximo del bloque (o recorte por Nivel 2)
       y rechazo HTTP 400 en `log_set_htmx` al intentar registrar series extras.
  4. Edición Rápida con Autocompletado XLOOKUP del Entrenador (`BD_Local_Ejercicios`):
     - Previsualización XLOOKUP de vídeo + regresiones A/B y sustitución no destructiva en semanas pendientes.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from training.models import (
    AthleteProfile,
    Exercise,
    LoggedExercise,
    LoggedSet,
    Macrocycle,
    PlannedExercise,
    TrainerNotification,
    TrainerProfile,
    WorkoutPlan,
    WorkoutSession,
)

User = get_user_model()


class AthleteUIPhase5Tests(TestCase):
    def setUp(self):
        self.trainer_user = User.objects.create_user(
            email="coach.phase5@am.test",
            password="Password123!",
            first_name="Jorge",
            last_name="Alcaraz",
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        self.athlete_user = User.objects.create_user(
            email="fighter.phase5@am.test",
            password="Password123!",
            first_name="Ilia",
            last_name="Fighter",
        )
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user,
            assigned_trainer=self.trainer_user,
            sport="mma",
            weight=77.0,
        )

        # Ejercicios con Árbol de Regresión (Opción A Isométrica y Opción B Vector)
        self.ex_opt_a = Exercise.objects.create(
            code="REG_ISO_01",
            name="Isopush Press Banca en Pines",
            category="fuerza",
            session_block="B4_Principal",
            video_url="https://youtube.com/watch?v=optA111",
        )
        self.ex_opt_b = Exercise.objects.create(
            code="REG_VEC_01",
            name="Floor Press con Mancuernas Agarre Neutro",
            category="fuerza",
            session_block="B4_Principal",
            video_url="https://youtube.com/watch?v=optB222",
        )
        self.ex_b1 = Exercise.objects.create(
            code="B1_MOV_01",
            name="Movilidad Torácica 90/90",
            category="movilidad",
            session_block="B1_Movilidad",
            video_url="https://youtube.com/watch?v=b1mov",
        )
        self.ex_b2 = Exercise.objects.create(
            code="B2_VEL_01",
            name="Sprint Lanzado 15m",
            category="velocidad",
            session_block="B2_Velocidad",
        )
        self.ex_b3 = Exercise.objects.create(
            code="B3_POT_01",
            name="Lanzamiento Balón Medicinal Rotacional",
            category="potencia",
            session_block="B3_Potencia",
        )
        self.ex_b4_main = Exercise.objects.create(
            code="B4_PRI_01",
            name="Press Banca Barra Olímpica",
            category="fuerza",
            session_block="B4_Principal",
            video_url="https://youtube.com/watch?v=main000",
            regression_option_a=self.ex_opt_a,
            regression_option_b=self.ex_opt_b,
        )
        self.ex_b4_acc = Exercise.objects.create(
            code="B4_ACC_01",
            name="Remo con Mancuerna Unilateral",
            category="fuerza",
            session_block="B4_Accesorio",
        )
        self.ex_b5 = Exercise.objects.create(
            code="B5_CAR_01",
            name="AirBike RSA 10x10s",
            category="resistencia",
            session_block="B5_Cardio",
        )

        # Macrociclo y Bloque publicado con Semana 3 (Pico: 4 series) y Semana 4 (Descarga: 2 series)
        self.macrocycle = Macrocycle.objects.create(
            name="Macrociclo Fase 5",
            trainer=self.trainer,
            athlete=self.athlete,
            is_active=True,
        )
        self.macrocycle.initialize_four_blocks(weeks_per_block=4, sessions_per_week=3)
        self.block1 = self.macrocycle.blocks.get(block_number=1)
        self.block1.set_published(True)

        self.plan_w3 = WorkoutPlan.objects.create(
            name="Bloque 1 · Semana 3 · Día 1",
            trainer=self.trainer,
            athlete=self.athlete,
            macrocycle_block=self.block1,
            week_number=3,
            day_number=1,
            target_date=timezone.now().date(),
        )
        self.plan_w4 = WorkoutPlan.objects.create(
            name="Bloque 1 · Semana 4 (Descarga) · Día 1",
            trainer=self.trainer,
            athlete=self.athlete,
            macrocycle_block=self.block1,
            week_number=4,
            day_number=1,
            target_date=timezone.now().date(),
        )

        # Ejercicios en Semana 3 (4 series en B4_Principal)
        self.pe_w3_b1 = PlannedExercise.objects.create(
            workout_plan=self.plan_w3,
            exercise=self.ex_b1,
            session_block="B1_Movilidad",
            order=1,
            sets="2",
            reps="8",
            rpe="5",
        )
        self.pe_w3_b2 = PlannedExercise.objects.create(
            workout_plan=self.plan_w3,
            exercise=self.ex_b2,
            session_block="B2_Velocidad",
            order=2,
            sets="3",
            reps="3",
            rpe="8.5",
        )
        self.pe_w3_b3 = PlannedExercise.objects.create(
            workout_plan=self.plan_w3,
            exercise=self.ex_b3,
            session_block="B3_Potencia",
            order=3,
            sets="4",
            reps="5",
            rpe="8.5",
        )
        self.pe_w3_b4_main = PlannedExercise.objects.create(
            workout_plan=self.plan_w3,
            exercise=self.ex_b4_main,
            session_block="B4_Principal",
            order=4,
            sets="4",
            reps="5",
            rir="2",
            rpe="8",
            load="90 kg",
        )
        self.pe_w3_b4_acc = PlannedExercise.objects.create(
            workout_plan=self.plan_w3,
            exercise=self.ex_b4_acc,
            session_block="B4_Accesorio",
            order=5,
            sets="3",
            reps="10",
            rir="2",
            rpe="8",
            load="32 kg",
        )
        self.pe_w3_b5 = PlannedExercise.objects.create(
            workout_plan=self.plan_w3,
            exercise=self.ex_b5,
            session_block="B5_Cardio",
            order=6,
            sets="10",
            reps="10s sprint / 50s suave",
            rpe="9",
        )

        # Ejercicio en Semana 4 (Descarga: 2 series frente a las 4 de Semana 3 -> 2 series bloqueadas ⬛)
        self.pe_w4_b4_main = PlannedExercise.objects.create(
            workout_plan=self.plan_w4,
            exercise=self.ex_b4_main,
            session_block="B4_Principal",
            order=4,
            sets="2",
            reps="5",
            rir="3",
            rpe="7",
            load="80 kg",
        )

    def test_default_readiness_level_is_4_green_normal_scheme(self):
        """La sesión nace preconfigurada en Nivel 4 (Verde · Esquema_Normal) sin fricción."""
        self.client.force_login(self.athlete_user)
        res = self.client.get(reverse("training:live_workout", kwargs={"pk": self.plan_w3.pk}))
        self.assertEqual(res.status_code, 200)
        session = WorkoutSession.objects.get(workout_plan=self.plan_w3)
        self.assertEqual(session.readiness_level, 4)
        self.assertEqual(session.readiness_scheme, "Esquema_Normal")
        self.assertContains(res, "Semáforo de Disposición Diaria")

    def test_readiness_level_2_fatigue_adapts_blocks_and_notifies_trainer(self):
        """
        Nivel 2 (Amarillo — Fatiga Moderada) conmuta a Esquema_Fatiga:
          - Amplía B1_Movilidad (+1 serie: 2 -> 3)
          - Pasa B2_Velocidad y B3_Potencia a fluidez técnica submáxima (RPE 6)
          - Recorta 1 serie en B4_Accesorio (3 -> 2, bloqueando la 3ª) y baja RPE (-1 punto)
          - Conmuta B5_Cardio a Zona 2 continua regenerativa
          - Crea alerta TrainerNotification(event_type='low_readiness')
        """
        self.client.force_login(self.athlete_user)
        res = self.client.post(
            reverse("training:update_session_readiness", kwargs={"plan_id": self.plan_w3.pk}),
            {"readiness_level": "2"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Esquema_Fatiga")

        live_items = {item["planned"].id: item for item in res.context["live_items"]}
        # B1: +1 serie (2 -> 3)
        self.assertEqual(live_items[self.pe_w3_b1.id]["target_sets_count"], 3)
        # B2 & B3: RPE 6 fluidez submáxima
        self.assertEqual(live_items[self.pe_w3_b2.id]["adjusted"]["rpe"], "6")
        self.assertEqual(live_items[self.pe_w3_b3.id]["adjusted"]["rpe"], "6")
        # B4 Accesorio: recorta 1 serie (3 -> 2) y bloquea la serie 3
        self.assertEqual(live_items[self.pe_w3_b4_acc.id]["target_sets_count"], 2)
        self.assertIn(3, live_items[self.pe_w3_b4_acc.id]["locked_set_numbers"])
        self.assertEqual(live_items[self.pe_w3_b4_acc.id]["adjusted"]["rpe"], "7")
        # B5 Cardio: Zona 2 regenerativa
        self.assertIn("Zona 2", live_items[self.pe_w3_b5.id]["adjusted"]["load"])

        self.assertTrue(
            TrainerNotification.objects.filter(
                trainer=self.trainer,
                athlete=self.athlete,
                event_type="low_readiness",
            ).exists()
        )

    def test_readiness_level_1_collapse_suppresses_b2_b3_and_pumps_b4(self):
        """
        Nivel 1 (Rojo — Colapso Sistémico) conmuta a Esquema_Regenerativo:
          - Suprime al 100 % B2_Velocidad y B3_Potencia (0 series, bloqueo de log_set_htmx)
          - Convierte B4 en bombeo regenerativo RIR 5-6 (RPE 4.5)
          - Sustituye B5_Cardio por Zona 2 sin impacto
        """
        self.client.force_login(self.athlete_user)
        res = self.client.post(
            reverse("training:update_session_readiness", kwargs={"plan_id": self.plan_w3.pk}),
            {"readiness_level": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Esquema_Regenerativo")
        self.assertContains(res, "BLOQUE SUPRIMIDO HOY")

        live_items = {item["planned"].id: item for item in res.context["live_items"]}
        self.assertTrue(live_items[self.pe_w3_b2.id]["adjusted"]["is_suppressed"])
        self.assertEqual(live_items[self.pe_w3_b2.id]["target_sets_count"], 0)
        self.assertTrue(live_items[self.pe_w3_b3.id]["adjusted"]["is_suppressed"])
        self.assertEqual(live_items[self.pe_w3_b3.id]["target_sets_count"], 0)
        self.assertEqual(live_items[self.pe_w3_b4_main.id]["adjusted"]["rir"], "5-6")

        # Intentar registrar serie en B2 suprimido debe devolver 400
        res_log = self.client.post(
            reverse("training:log_set_htmx", kwargs={"planned_id": self.pe_w3_b2.pk}),
            {"weight_kg": "0", "reps": "3", "rpe": "8"},
        )
        self.assertEqual(res_log.status_code, 400)
        self.assertEqual(LoggedSet.objects.count(), 0)

    def test_autonomous_pain_tree_progression_and_injury_omission_alert(self):
        """
        El botón `⚠️ Molestia articular` recorre autónomamente:
          normal -> option_a (Isopush + vídeo A) -> option_b (Vector + vídeo B) -> omitted_injury (`OMITIDO_POR_LESION`),
        bloqueando el registro de series y enviando notificación `injury_omitted` al entrenador.
        """
        self.client.force_login(self.athlete_user)
        pain_url = reverse("training:trigger_pain_tree", kwargs={"planned_id": self.pe_w3_b4_main.pk})

        # 1ª pulsación -> Opción A (Regresión Isométrica)
        res_a = self.client.post(pain_url, {"action": "advance"})
        self.assertEqual(res_a.status_code, 200)
        logged = LoggedExercise.objects.get(planned_exercise=self.pe_w3_b4_main)
        self.assertEqual(logged.pain_status, "option_a")
        self.assertEqual(logged.active_exercise, self.ex_opt_a)
        self.assertEqual(logged.active_video_url, "https://youtube.com/watch?v=optA111")
        self.assertContains(res_a, self.ex_opt_a.name)
        self.assertContains(res_a, "https://youtube.com/watch?v=optA111")

        # 2ª pulsación -> Opción B (Cambio de Vector Mecánico)
        res_b = self.client.post(pain_url, {"action": "advance"})
        self.assertEqual(res_b.status_code, 200)
        logged.refresh_from_db()
        self.assertEqual(logged.pain_status, "option_b")
        self.assertEqual(logged.active_exercise, self.ex_opt_b)
        self.assertEqual(logged.active_video_url, "https://youtube.com/watch?v=optB222")
        self.assertContains(res_b, self.ex_opt_b.name)

        # 3ª pulsación -> OMITIDO_POR_LESION + alerta al entrenador
        res_omit = self.client.post(pain_url, {"action": "advance"})
        self.assertEqual(res_omit.status_code, 200)
        logged.refresh_from_db()
        self.assertEqual(logged.pain_status, "omitted_injury")
        self.assertTrue(logged.is_omitted_by_injury)
        self.assertContains(res_omit, "OMITIDO_POR_LESION")

        self.assertTrue(
            TrainerNotification.objects.filter(
                trainer=self.trainer,
                athlete=self.athlete,
                event_type="injury_omitted",
            ).exists()
        )

        # Intentar registrar serie en ejercicio omitido por lesión -> HTTP 400
        res_log = self.client.post(
            reverse("training:log_set_htmx", kwargs={"planned_id": self.pe_w3_b4_main.pk}),
            {"weight_kg": "80", "reps": "5", "rpe": "8"},
        )
        self.assertEqual(res_log.status_code, 400)

    def test_deload_set_locking_visual_and_backend_enforcement(self):
        """
        En Semana 4 (Descarga: 2 series prescritas frente al máximo de 4 en Semana 3),
        las Series 3 y 4 aparecen bloqueadas (`⬛`) y `log_set_htmx` rechaza la 3ª serie con HTTP 400.
        """
        self.client.force_login(self.athlete_user)
        res_live = self.client.get(reverse("training:live_workout", kwargs={"pk": self.plan_w4.pk}))
        self.assertEqual(res_live.status_code, 200)
        item = res_live.context["live_items"][0]
        self.assertEqual(item["target_sets_count"], 2)
        self.assertEqual(item["block_max_sets"], 4)
        self.assertEqual(item["locked_set_numbers"], [3, 4])
        self.assertContains(res_live, "⬛ Serie 3")
        self.assertContains(res_live, "⬛ Serie 4")

        log_url = reverse("training:log_set_htmx", kwargs={"planned_id": self.pe_w4_b4_main.pk})
        # Serie 1 y Serie 2 permitidas
        self.assertEqual(
            self.client.post(log_url, {"weight_kg": "80", "reps": "5", "rpe": "7"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(log_url, {"weight_kg": "80", "reps": "5", "rpe": "7"}).status_code,
            200,
        )
        # Serie 3 bloqueada por protección de descarga (HTTP 400)
        res_s3 = self.client.post(log_url, {"weight_kg": "80", "reps": "5", "rpe": "7"})
        self.assertEqual(res_s3.status_code, 400)
        self.assertEqual(LoggedSet.objects.filter(logged_exercise__planned_exercise=self.pe_w4_b4_main).count(), 2)

    def test_trainer_xlookup_meta_and_non_destructive_quick_swap(self):
        """
        El entrenador consulta `exercise_xlookup_meta` para previsualizar vídeo + Opción A/B
        y ejecuta `block_quick_swap_exercise`, sustituyendo el ejercicio solo en semanas sin marcas registradas.
        """
        new_ex = Exercise.objects.create(
            code="B4_PRI_99",
            name="Press Banca con Mancuernas Pesadas",
            category="fuerza",
            session_block="B4_Principal",
            video_url="https://youtube.com/watch?v=new999",
            regression_option_a=self.ex_opt_a,
            regression_option_b=self.ex_opt_b,
        )

        # Registrar 1 serie real en Semana 3 para verificar que Semana 3 queda protegida
        session_w3 = WorkoutSession.objects.create(workout_plan=self.plan_w3, athlete=self.athlete)
        logged_w3 = LoggedExercise.objects.create(workout_session=session_w3, planned_exercise=self.pe_w3_b4_main)
        LoggedSet.objects.create(logged_exercise=logged_w3, set_number=1, weight_kg=90, reps=5, rpe=8)

        self.client.force_login(self.trainer_user)

        # 1. Previsualización XLOOKUP
        res_meta = self.client.get(
            reverse("training:exercise_xlookup_meta"),
            {"q": "[B4_PRI_99] Press Banca con Mancuernas Pesadas"},
        )
        self.assertEqual(res_meta.status_code, 200)
        self.assertContains(res_meta, "https://youtube.com/watch?v=new999")
        self.assertContains(res_meta, self.ex_opt_a.name)
        self.assertContains(res_meta, self.ex_opt_b.name)

        # 2. Sustitución rápida XLOOKUP en el bloque
        res_swap = self.client.post(
            reverse("training:block_quick_swap_exercise", kwargs={"block_id": self.block1.pk}),
            {
                "day_number": "1",
                "order": "4",
                "old_exercise_id": str(self.ex_b4_main.pk),
                "new_exercise_query": "[B4_PRI_99] Press Banca con Mancuernas Pesadas",
            },
        )
        self.assertEqual(res_swap.status_code, 302)

        # Semana 3 tenía una serie registrada -> conserva el ejercicio original
        self.pe_w3_b4_main.refresh_from_db()
        self.assertEqual(self.pe_w3_b4_main.exercise, self.ex_b4_main)

        # Semana 4 estaba pendiente -> se actualiza al nuevo ejercicio con su árbol A/B
        self.pe_w4_b4_main.refresh_from_db()
        self.assertEqual(self.pe_w4_b4_main.exercise, new_ex)
