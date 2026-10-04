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
