from datetime import date, timedelta
import io
import shutil
import tempfile
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from users.models import TrainerProfile, AthleteProfile
from training.models import (
    Exercise, WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise, LoggedSet,
)

User = get_user_model()
TEMP_MEDIA_ROOT = tempfile.mkdtemp()


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


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class TrainerAthleteManagementIsolationTests(TestCase):
    """
    Verifica que el entrenador desde «Mis deportistas» pueda editar cualquier dato de un deportista
    y eliminarlo, manteniendo la foto y el perfil del entrenador completamente aislados de los del deportista.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def _create_image(self, name='foto.jpg', color=(37, 99, 235)):
        file = io.BytesIO()
        img = Image.new('RGB', (80, 80), color=color)
        img.save(file, 'jpeg')
        file.seek(0)
        return SimpleUploadedFile(name, file.read(), content_type='image/jpeg')

    def setUp(self):
        self.trainer_user = User.objects.create_user(
            email='coach.isolated@test.com',
            password='Password123!',
            first_name='Entrenador',
            last_name='Principal',
            profile_picture=self._create_image('trainer_secret_photo.jpg'),
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        self.other_trainer_user = User.objects.create_user(
            email='other.coach@test.com',
            password='Password123!',
            first_name='Otro',
            last_name='Coach',
        )
        self.other_trainer = TrainerProfile.objects.create(user=self.other_trainer_user)

        self.athlete_user = User.objects.create_user(
            email='deportista.alumno@test.com',
            password='Password123!',
            first_name='Lucía',
            last_name='Gómez',
        )
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user,
            sport='mma',
            experience_level='principiante',
            training_goal='potencia_explosiva',
            weight=62.0,
            height=168.0,
            fat_percentage=18.5,
            lean_mass_percentage=76.0,
            assigned_trainer=self.trainer_user,
            trainer_confirmed=True,
        )

    def test_mis_deportistas_shows_edit_and_delete_actions(self):
        """En «Mis deportistas» se muestran los botones directos para editar y eliminar cada deportista."""
        self.client.force_login(self.trainer_user)
        res = self.client.get(reverse('home') + '?tab=trainer')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, reverse('training:trainer_athlete_edit', kwargs={'pk': self.athlete.pk}))
        self.assertContains(res, reverse('training:trainer_athlete_delete', kwargs={'pk': self.athlete.pk}))

    def test_trainer_photo_is_isolated_from_athlete_edit_view(self):
        """La vista de edición del deportista NO mezcla la foto del entrenador en el formulario del deportista."""
        self.client.force_login(self.trainer_user)
        edit_url = reverse('training:trainer_athlete_edit', kwargs={'pk': self.athlete.pk})
        res = self.client.get(edit_url)
        self.assertEqual(res.status_code, 200)

        # El formulario de edición del deportista debe mostrar 'Sin foto' (porque el deportista no tiene foto)
        # y el preview #avatar-preview-img debe tener src="" vacío, nunca la foto del entrenador
        self.assertContains(res, 'id="avatar-preview-img"\n                                 src=""')
        self.assertContains(res, 'Subir fotografía')
        # Y debe mostrar todos los campos deportivos aunque el entrenador NO sea deportista (is_athlete=False)
        self.assertContains(res, 'name="sport"')
        self.assertContains(res, 'name="experience_level"')
        self.assertContains(res, 'name="training_goal"')
        self.assertContains(res, 'name="weight"')
        self.assertContains(res, 'name="height"')
        self.assertContains(res, 'name="email"')

    def test_trainer_can_edit_any_athlete_data_and_photo_isolated(self):
        """El entrenador puede cambiar cualquier dato del deportista (incluidos correo y foto) sin alterar su propia cuenta."""
        self.client.force_login(self.trainer_user)
        edit_url = reverse('training:trainer_athlete_edit', kwargs={'pk': self.athlete.pk})
        athlete_photo = self._create_image('lucia_avatar.jpg', color=(16, 185, 129))
        trainer_original_photo = self.trainer_user.profile_picture.name

        res = self.client.post(edit_url, {
            'first_name': 'Lucía María',
            'last_name': 'Gómez Pérez',
            'email': 'lucia.nueva@test.com',
            'sport': 'hyrox',
            'experience_level': 'avanzado',
            'training_goal': 'resistencia_muscular',
            'weight': '64.50',
            'height': '169.00',
            'fat_percentage': '16.20',
            'lean_mass_percentage': '78.40',
            'profile_picture': athlete_photo,
        })
        self.assertRedirects(res, reverse('training:athlete_detail', kwargs={'pk': self.athlete.pk}))

        self.athlete.refresh_from_db()
        self.athlete_user.refresh_from_db()
        self.trainer_user.refresh_from_db()

        self.assertEqual(self.athlete_user.first_name, 'Lucía María')
        self.assertEqual(self.athlete_user.last_name, 'Gómez Pérez')
        self.assertEqual(self.athlete_user.email, 'lucia.nueva@test.com')
        self.assertEqual(self.athlete.sport, 'hyrox')
        self.assertEqual(self.athlete.experience_level, 'avanzado')
        self.assertEqual(self.athlete.training_goal, 'resistencia_muscular')
        self.assertEqual(float(self.athlete.weight), 64.5)
        self.assertEqual(float(self.athlete.height), 169.0)
        self.assertEqual(float(self.athlete.fat_percentage), 16.2)
        self.assertEqual(float(self.athlete.lean_mass_percentage), 78.4)
        self.assertTrue(self.athlete_user.has_profile_picture)
        self.assertIn('lucia_avatar', self.athlete_user.profile_picture.name)

        # La foto y datos del entrenador permanecen intactos
        self.assertEqual(self.trainer_user.profile_picture.name, trainer_original_photo)
        self.assertEqual(self.trainer_user.first_name, 'Entrenador')

        # Si el entrenador borra la foto del deportista, solo se borra la del deportista
        self.client.post(edit_url, {
            'first_name': 'Lucía María',
            'last_name': 'Gómez Pérez',
            'email': 'lucia.nueva@test.com',
            'sport': 'hyrox',
            'experience_level': 'avanzado',
            'training_goal': 'resistencia_muscular',
            'weight': '64.50',
            'height': '169.00',
            'delete_profile_picture': '1',
        })
        self.athlete_user.refresh_from_db()
        self.trainer_user.refresh_from_db()
        self.assertFalse(self.athlete_user.has_profile_picture)
        self.assertTrue(self.trainer_user.has_profile_picture)

    def test_trainer_unassigns_athlete_without_deleting_from_db(self):
        """
        El entrenador desasigna al deportista de su gestión sin eliminarlo de la base de datos.
        El usuario y su perfil deportivo siguen existiendo y pueden asignarse a otro entrenador
        o activar el rol dual de entrenador y deportista.
        """
        unassign_url = reverse('training:trainer_athlete_delete', kwargs={'pk': self.athlete.pk})

        # Otro entrenador no puede ver ni desasignar al deportista ajeno
        self.client.force_login(self.other_trainer_user)
        self.assertEqual(self.client.get(unassign_url).status_code, 404)
        self.assertEqual(self.client.post(unassign_url).status_code, 404)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.assigned_trainer, self.trainer_user)

        # El entrenador asignado ve la pantalla de confirmación y desasigna al deportista
        self.client.force_login(self.trainer_user)
        confirm_res = self.client.get(unassign_url)
        self.assertEqual(confirm_res.status_code, 200)
        self.assertContains(confirm_res, 'Lucía Gómez')
        self.assertContains(confirm_res, 'Desasignar Deportista')

        post_res = self.client.post(unassign_url)
        self.assertRedirects(post_res, reverse('training:trainer_dashboard'), fetch_redirect_response=False)

        # El deportista y su usuario SIGUEN existiendo en la base de datos, pero sin entrenador asignado
        self.assertTrue(AthleteProfile.objects.filter(pk=self.athlete.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.athlete_user.pk).exists())
        self.athlete.refresh_from_db()
        self.assertIsNone(self.athlete.assigned_trainer)
        self.assertFalse(self.athlete.trainer_confirmed)

        # El deportista ya no aparece en «Mis deportistas» del primer entrenador
        trainer_home = self.client.get(reverse('home') + '?tab=trainer')
        self.assertEqual(trainer_home.context['total_athletes'], 0)

        # Caso A: El deportista puede asignarse a otro entrenador desde su propio perfil
        self.client.force_login(self.athlete_user)
        assign_res = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Lucía',
            'last_name': 'Gómez',
            'sport': 'mma',
            'experience_level': 'principiante',
            'training_goal': 'potencia_explosiva',
            'assigned_trainer': self.other_trainer_user.pk,
        })
        self.assertEqual(assign_res.status_code, 302)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.assigned_trainer, self.other_trainer_user)

        # Caso B: El deportista también puede asumir el rol de entrenador y deportista (perfil dual)
        become_res = self.client.post(reverse('users:create_trainer_profile'))
        self.assertEqual(become_res.status_code, 302)
        self.athlete_user.refresh_from_db()
        self.assertTrue(self.athlete_user.is_dual)


