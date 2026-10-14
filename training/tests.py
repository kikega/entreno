from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from users.models import TrainerProfile, AthleteProfile
from training.models import (
    Exercise, WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise, LoggedSet,
)

User = get_user_model()


class TrainingWorkflowAndSecurityTests(TestCase):
    """
    Pruebas integrales de permisos, vistas y flujos de entrenamiento (WorkoutPlan, LiveWorkout, HTMX).
    """

    def setUp(self):
        # 1. Entrenador principal
        self.trainer_user = User.objects.create_user(
            email='carlos.trainer@test.com', password='Password123!',
            first_name='Carlos', last_name='Trainer',
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        # 2. Entrenador secundario (ajeno)
        self.other_trainer_user = User.objects.create_user(
            email='other.trainer@test.com', password='Password123!',
            first_name='Other', last_name='Trainer',
        )
        self.other_trainer = TrainerProfile.objects.create(user=self.other_trainer_user)

        # 3. Deportista asignado
        self.athlete_user = User.objects.create_user(
            email='alex.athlete@test.com', password='Password123!',
            first_name='Alex', last_name='Athlete',
        )
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user,
            weight=75.0,
            height=175.0,
            sport='crossfit',
            assigned_trainer=self.trainer_user,
            trainer_confirmed=True,
        )

        # 4. Deportista ajeno
        self.other_athlete_user = User.objects.create_user(
            email='other.athlete@test.com', password='Password123!',
            first_name='Other', last_name='Athlete',
        )
        self.other_athlete = AthleteProfile.objects.create(
            user=self.other_athlete_user,
            weight=80.0,
            height=180.0,
            sport='crossfit',
        )

        # 5. Ejercicio y Plan
        self.exercise = Exercise.objects.create(
            name='Press de Banca',
            category='fuerza',
            movement_pattern='empuje_horizontal',
            created_by=self.trainer,
        )

        self.plan = WorkoutPlan.objects.create(
            name='Fuerza Pecho',
            trainer=self.trainer,
            athlete=self.athlete,
            sport='crossfit',
            target_date=date.today() + timedelta(days=1),
            is_completed=False,
        )

        self.planned_ex = PlannedExercise.objects.create(
            workout_plan=self.plan,
            exercise=self.exercise,
            order=1,
            sets='4',
            reps='8',
            load='80 kg',
            rpe='8.0',
        )

    def test_plan_detail_access_control(self):
        """El entrenador del plan y el deportista asignado pueden acceder; terceros reciben 404."""
        # Entrenador asignado
        self.client.force_login(self.trainer_user)
        res = self.client.get(reverse('training:plan_detail', kwargs={'pk': self.plan.pk}))
        self.assertEqual(res.status_code, 200)

        # Deportista asignado
        self.client.force_login(self.athlete_user)
        res = self.client.get(reverse('training:plan_detail', kwargs={'pk': self.plan.pk}))
        self.assertEqual(res.status_code, 200)

        # Otro entrenador no puede ver el plan
        self.client.force_login(self.other_trainer_user)
        res = self.client.get(reverse('training:plan_detail', kwargs={'pk': self.plan.pk}))
        self.assertEqual(res.status_code, 404)

        # Otro deportista no puede ver el plan
        self.client.force_login(self.other_athlete_user)
        res = self.client.get(reverse('training:plan_detail', kwargs={'pk': self.plan.pk}))
        self.assertEqual(res.status_code, 404)

    def test_live_workout_access_control(self):
        """Solo el deportista asignado puede acceder a su sesión en vivo."""
        self.client.force_login(self.athlete_user)
        res = self.client.get(reverse('training:live_workout', kwargs={'pk': self.plan.pk}))
        self.assertEqual(res.status_code, 200)

        # Otro deportista es redirigido con error
        self.client.force_login(self.other_athlete_user)
        res = self.client.get(reverse('training:live_workout', kwargs={'pk': self.plan.pk}))
        self.assertEqual(res.status_code, 302)

    def test_add_planned_exercise_security(self):
        """add_planned_exercise rechaza accesos anónimos o de entrenadores ajenos."""
        url = reverse('training:add_exercise', kwargs={'plan_id': self.plan.pk})
        post_data = {
            'exercise': self.exercise.pk,
            'order': 2,
            'sets': '3',
            'reps': '10',
            'load': '60 kg',
        }

        # Anónimo -> redirige a login (302)
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        # Entrenador ajeno -> 403 No autorizado
        self.client.force_login(self.other_trainer_user)
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 403)

        # Entrenador propietario -> 200 OK y añade el ejercicio
        self.client.force_login(self.trainer_user)
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.plan.planned_exercises.count(), 2)

    def test_complete_workout_flow(self):
        """El deportista completa el entrenamiento y se registran métricas y RPE de sesión."""
        self.client.force_login(self.athlete_user)
        url = reverse('training:complete_workout', kwargs={'plan_id': self.plan.pk})

        res = self.client.post(url, {
            'duration_minutes': 55,
            'calories_burned': 420,
            'avg_heart_rate': 142,
            'session_rpe': '8.5',
            'notes': 'Buenas sensaciones.',
        })
        self.assertEqual(res.status_code, 302)

        self.plan.refresh_from_db()
        self.assertTrue(self.plan.is_completed)

        session = self.plan.session
        self.assertEqual(session.duration_minutes, 55)
        self.assertEqual(session.calories_burned, 420)
        self.assertEqual(session.avg_heart_rate, 142)
        self.assertEqual(float(session.session_rpe), 8.5)
        self.assertEqual(session.notes, 'Buenas sensaciones.')

    def test_log_set_htmx(self):
        """El deportista registra series individuales con HTMX y se actualizan los agregados."""
        self.client.force_login(self.athlete_user)
        url = reverse('training:log_set_htmx', kwargs={'planned_id': self.planned_ex.pk})

        res = self.client.post(url, {
            'weight_kg': '82.5',
            'reps': '8',
            'rpe': '8.5',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Serie 1')
        self.assertContains(res, '82.5 kg')

        logged_ex = LoggedExercise.objects.get(planned_exercise=self.planned_ex)
        self.assertEqual(logged_ex.sets.count(), 1)
        logged_set = logged_ex.sets.first()
        self.assertEqual(float(logged_set.weight_kg), 82.5)
        self.assertEqual(logged_set.reps, 8)
        self.assertGreater(logged_set.est_1rm, 82.5)

    def test_exercise_crud_and_delete_protection(self):
        """Un ejercicio usado en un plan no puede ser eliminado accidentalmente."""
        self.client.force_login(self.trainer_user)

        # Intentar eliminar ejercicio que está en self.plan -> debe bloquear y redirigir con error
        delete_url = reverse('training:exercise_delete', kwargs={'pk': self.exercise.pk})
        res = self.client.post(delete_url)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Exercise.objects.filter(pk=self.exercise.pk).exists())

        # Crear ejercicio no usado y eliminarlo -> tiene éxito
        unused = Exercise.objects.create(
            name='Dominadas Neutras',
            category='fuerza',
            movement_pattern='traccion_vertical',
            created_by=self.trainer,
        )
        res = self.client.post(reverse('training:exercise_delete', kwargs={'pk': unused.pk}))
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Exercise.objects.filter(pk=unused.pk).exists())

    def test_exercise_catalog_visible_to_all_trainers_and_dual_users(self):
        """Todos los entrenadores y usuarios duales pueden ver todos los ejercicios independientemente del creador."""
        # 1. Ejercicio del entrenador principal (self.exercise ya existe)
        # 2. Ejercicio creado por otro entrenador
        ex_other = Exercise.objects.create(
            name='Sentadilla Frontal',
            category='fuerza',
            movement_pattern='dominante_rodilla',
            created_by=self.other_trainer,
        )
        # 3. Ejercicio global del sistema (sin creador)
        ex_system = Exercise.objects.create(
            name='Remo con Barra Global',
            category='fuerza',
            movement_pattern='traccion_horizontal',
            created_by=None,
        )

        # 4. Usuario dual (deportista y entrenador)
        dual_user = User.objects.create_user(
            email='dual.user@test.com', password='Password123!',
            first_name='Dual', last_name='User',
        )
        TrainerProfile.objects.create(user=dual_user)
        AthleteProfile.objects.create(user=dual_user, sport='mma')

        # Comprobar acceso del entrenador principal
        self.client.force_login(self.trainer_user)
        res_trainer = self.client.get(reverse('training:exercise_list'))
        self.assertEqual(res_trainer.status_code, 200)
        self.assertEqual(res_trainer.context['total_exercises'], Exercise.objects.count())

        # Búsqueda específica: el entrenador principal ve el ejercicio creado por otro entrenador
        res_search_other = self.client.get(reverse('training:exercise_list') + f'?q={ex_other.name}')
        self.assertContains(res_search_other, ex_other.name)
        # Y también el ejercicio global del sistema
        res_search_sys = self.client.get(reverse('training:exercise_list') + f'?q={ex_system.name}')
        self.assertContains(res_search_sys, ex_system.name)

        # Comprobar acceso del otro entrenador: ve el ejercicio del entrenador principal y el del sistema
        self.client.force_login(self.other_trainer_user)
        res_other = self.client.get(reverse('training:exercise_list'))
        self.assertEqual(res_other.status_code, 200)
        self.assertEqual(res_other.context['total_exercises'], Exercise.objects.count())

        res_search_trainer1 = self.client.get(reverse('training:exercise_list') + f'?q={self.exercise.name}')
        self.assertContains(res_search_trainer1, self.exercise.name)
        self.assertContains(res_search_trainer1, 'Disponible en tus planes')

        # Comprobar acceso del usuario dual: ve todos los ejercicios
        self.client.force_login(dual_user)
        res_dual = self.client.get(reverse('training:exercise_list'))
        self.assertEqual(res_dual.status_code, 200)
        self.assertEqual(res_dual.context['total_exercises'], Exercise.objects.count())

        res_dual_search = self.client.get(reverse('training:exercise_list') + f'?q={self.exercise.name}')
        self.assertContains(res_dual_search, self.exercise.name)

        # Un usuario únicamente deportista no puede acceder al catálogo
        self.client.force_login(self.athlete_user)
        res_athlete = self.client.get(reverse('training:exercise_list'))
        self.assertEqual(res_athlete.status_code, 302)

    def test_exercise_can_only_be_modified_or_deleted_by_creator(self):
        """Un ejercicio solo puede ser modificado o eliminado por el entrenador que lo creó."""
        ex_trainer1 = self.exercise  # Creado por self.trainer
        ex_trainer2 = Exercise.objects.create(
            name='Peso Muerto Rumano',
            category='fuerza',
            movement_pattern='dominante_cadera',
            created_by=self.other_trainer,
        )
        ex_system = Exercise.objects.create(
            name='Fondos en Paralelas',
            category='fuerza',
            movement_pattern='empuje_vertical',
            created_by=None,
        )

        # Entrenador 2 intenta editar el ejercicio de Entrenador 1 -> 404
        self.client.force_login(self.other_trainer_user)
        res_edit = self.client.get(reverse('training:exercise_edit', kwargs={'pk': ex_trainer1.pk}))
        self.assertEqual(res_edit.status_code, 404)

        # Entrenador 2 intenta eliminar el ejercicio de Entrenador 1 -> 404
        res_del = self.client.post(reverse('training:exercise_delete', kwargs={'pk': ex_trainer1.pk}))
        self.assertEqual(res_del.status_code, 404)

        # Entrenador 1 intenta editar el ejercicio de Entrenador 2 -> 404
        self.client.force_login(self.trainer_user)
        res_edit2 = self.client.get(reverse('training:exercise_edit', kwargs={'pk': ex_trainer2.pk}))
        self.assertEqual(res_edit2.status_code, 404)

        # Ningún entrenador puede modificar el ejercicio global del sistema -> 404
        res_edit_sys = self.client.get(reverse('training:exercise_edit', kwargs={'pk': ex_system.pk}))
        self.assertEqual(res_edit_sys.status_code, 404)

        # Entrenador 2 sí puede editar su propio ejercicio
        self.client.force_login(self.other_trainer_user)
        res_edit_own = self.client.get(reverse('training:exercise_edit', kwargs={'pk': ex_trainer2.pk}))
        self.assertEqual(res_edit_own.status_code, 200)

    def test_any_trainer_and_dual_user_can_use_any_exercise_in_plan(self):
        """Cualquier entrenador o usuario dual puede incluir cualquier ejercicio (propio, ajeno o del sistema) en sus planes."""
        ex_trainer1 = self.exercise  # Creado por trainer 1
        ex_system = Exercise.objects.create(
            name='Kettlebell Swing',
            category='potencia',
            movement_pattern='dominante_cadera',
            created_by=None,
        )

        # Plan del entrenador 2 para other_athlete
        plan_trainer2 = WorkoutPlan.objects.create(
            name='Plan Entrenador 2',
            trainer=self.other_trainer,
            athlete=self.other_athlete,
            sport='crossfit',
            target_date=date.today() + timedelta(days=2),
        )

        self.client.force_login(self.other_trainer_user)

        # Añadir ejercicio creado por entrenador 1 al plan de entrenador 2
        url = reverse('training:add_exercise', kwargs={'plan_id': plan_trainer2.pk})
        res1 = self.client.post(url, {
            'exercise': ex_trainer1.pk,
            'order': 1,
            'sets': '4',
            'reps': '10',
            'load': '70 kg',
        })
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(plan_trainer2.planned_exercises.filter(exercise=ex_trainer1).exists())

        # Añadir ejercicio del sistema al plan de entrenador 2
        res2 = self.client.post(url, {
            'exercise': ex_system.pk,
            'order': 2,
            'sets': '3',
            'reps': '15',
            'load': '24 kg',
        })
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(plan_trainer2.planned_exercises.filter(exercise=ex_system).exists())

    def test_dual_user_planning_for_self_has_full_exercise_access(self):
        """Un usuario dual puede planificar para sí mismo y tiene acceso completo para añadir ejercicios al plan."""
        dual_user = User.objects.create_user(
            email='mario.dual@test.com', password='Password123!',
            first_name='Mario', last_name='Dual',
        )
        dual_trainer = TrainerProfile.objects.create(user=dual_user)
        dual_athlete = AthleteProfile.objects.create(user=dual_user, sport='bjj')

        # Plan de entrenamiento del usuario dual para sí mismo
        dual_plan = WorkoutPlan.objects.create(
            name='Mi Autoplanificación BJJ',
            trainer=dual_trainer,
            athlete=dual_athlete,
            sport='bjj',
            target_date=date.today() + timedelta(days=1),
        )

        self.client.force_login(dual_user)

        # Acceso a la vista de detalle del plan: can_manage_plan es True y el botón/modal de añadir ejercicio está activo
        detail_res = self.client.get(reverse('training:plan_detail', kwargs={'pk': dual_plan.pk}))
        self.assertEqual(detail_res.status_code, 200)
        self.assertTrue(detail_res.context['can_manage_plan'])
        self.assertTrue(detail_res.context['is_plan_owner'])
        self.assertContains(detail_res, 'Añadir Ejercicio')
        self.assertContains(detail_res, 'addExerciseModal')

        # Añadir al plan un ejercicio creado por otro entrenador
        add_url = reverse('training:add_exercise', kwargs={'plan_id': dual_plan.pk})
        add_res = self.client.post(add_url, {
            'exercise': self.exercise.pk,  # Creado por self.trainer
            'order': 1,
            'sets': '3',
            'reps': '8',
            'load': '50 kg',
        })
        self.assertEqual(add_res.status_code, 200)
        self.assertTrue(dual_plan.planned_exercises.filter(exercise=self.exercise).exists())

