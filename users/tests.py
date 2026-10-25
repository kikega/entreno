import io
import shutil
import tempfile
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CustomUser, AthleteProfile, TrainerProfile


class HomeArchitectureTests(TestCase):
    """Verifica el espacio unificado: capacidades sin selector de rol."""

    def _user(self, email):
        return CustomUser.objects.create_user(email=email, password='test12345')

    def test_home_requires_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/users/login/', response.url)

    def test_user_without_profile_goes_to_onboarding(self):
        self.client.force_login(self._user('nobody@test.com'))
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('users:onboarding'))

        page = self.client.get(reverse('users:onboarding'))
        self.assertContains(page, '¿Cómo vas a usar EntrenoPro?')

    def test_athlete_sees_athlete_context_without_selector(self):
        user = self._user('athlete@test.com')
        AthleteProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'athlete')
        self.assertNotContains(response, 'Cambiar de rol')
        self.assertNotContains(response, 'Seleccionar Rol')

    def test_trainer_sees_trainer_context(self):
        user = self._user('trainer@test.com')
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'trainer')

    def test_dual_user_default_tab_is_athlete_and_can_switch(self):
        user = self._user('dual@test.com')
        AthleteProfile.objects.create(user=user)
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['active_tab'], 'athlete')  # default

        response = self.client.get(reverse('home') + '?tab=trainer')
        self.assertEqual(response.context['active_tab'], 'trainer')
        self.assertContains(response, 'Deportistas')

    def test_legacy_dashboard_urls_redirect_to_home(self):
        user = self._user('legacy@test.com')
        AthleteProfile.objects.create(user=user)
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.get(reverse('training:athlete_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('?tab=athlete', response.url)

        response = self.client.get(reverse('training:trainer_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('?tab=trainer', response.url)

    def test_onboarding_creates_profiles_self_service(self):
        user = self._user('selfservice@test.com')
        self.client.force_login(user)

        response = self.client.post(reverse('users:create_athlete_profile'))
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_athlete)

        response = self.client.post(reverse('users:create_trainer_profile'))
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_trainer)


class RoleManagementTests(TestCase):
    """Pruebas de definición, conmutación y gestión de roles (Deportista, Entrenador y Dual)."""

    def _user(self, email):
        return CustomUser.objects.create_user(email=email, password='test12345')

    def test_user_role_properties(self):
        user = self._user('roleprops@test.com')
        self.assertEqual(user.role_label, 'Sin perfil')
        self.assertIn('Sin perfil activo', user.role_description)

        athlete_prof = AthleteProfile.objects.create(user=user)
        user.refresh_from_db()
        self.assertEqual(user.role_label, 'Deportista')
        self.assertIn('Perfil Deportista', user.role_description)

        TrainerProfile.objects.create(user=user)
        user.refresh_from_db()
        self.assertEqual(user.role_label, 'Entrenador y Deportista')
        self.assertIn('Perfil Dual', user.role_description)

        athlete_prof.delete()
        user.refresh_from_db()
        self.assertEqual(user.role_label, 'Entrenador')
        self.assertIn('Perfil Entrenador', user.role_description)

    def test_onboarding_creates_dual_profile(self):
        user = self._user('dual_onboard@test.com')
        self.client.force_login(user)

        response = self.client.post(reverse('users:create_dual_profile'))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.is_athlete)
        self.assertTrue(user.is_trainer)
        self.assertTrue(user.is_dual)

    def test_become_athlete_view(self):
        user = self._user('trainer_to_dual@test.com')
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        # GET vista explicativa
        response = self.client.get(reverse('users:become_athlete'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Activar perfil de deportista')

        # POST activación
        response = self.client.post(reverse('users:become_athlete'))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.is_athlete)
        self.assertTrue(user.is_dual)

    def test_remove_trainer_profile_when_dual(self):
        user = self._user('remove_trainer@test.com')
        AthleteProfile.objects.create(user=user)
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.post(reverse('users:remove_trainer_profile'))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertFalse(user.is_trainer)
        self.assertTrue(user.is_athlete)

    def test_cannot_remove_trainer_profile_if_only_role(self):
        user = self._user('only_trainer@test.com')
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.post(reverse('users:remove_trainer_profile'))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.is_trainer)

    def test_remove_athlete_profile_when_dual(self):
        user = self._user('remove_athlete@test.com')
        AthleteProfile.objects.create(user=user)
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.post(reverse('users:remove_athlete_profile'))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertFalse(user.is_athlete)
        self.assertTrue(user.is_trainer)

    def test_cannot_remove_athlete_profile_if_only_role(self):
        user = self._user('only_athlete@test.com')
        AthleteProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.post(reverse('users:remove_athlete_profile'))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.is_athlete)

    def test_profile_edit_view_trainer_only(self):
        user = self._user('pure_trainer@test.com')
        TrainerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.get(reverse('users:profile_edit'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mi Perfil y Gestión de Roles')
        self.assertContains(response, 'Rol actual: Entrenador')

        # Actualizar datos personales
        response = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Vicente',
            'last_name': 'Del Bosque',
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Vicente')
        self.assertEqual(user.last_name, 'Del Bosque')

    def test_profile_edit_view_athlete(self):
        user = self._user('athlete_editor@test.com')
        profile = AthleteProfile.objects.create(user=user, weight=70.0, height=175.0)
        self.client.force_login(user)

        response = self.client.get(reverse('users:profile_edit'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rol actual: Deportista')

        # Actualizar datos
        response = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Pau',
            'last_name': 'Gasol',
            'sport': 'crossfit',
            'experience_level': 'intermedio',
            'training_goal': 'hipertrofia',
            'weight': 82.5,
            'height': 185.0,
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(user.first_name, 'Pau')
        self.assertEqual(float(profile.weight), 82.5)


class PasswordChangeTests(TestCase):
    """Pruebas del flujo de cambio de contraseña desde el perfil de usuario."""

    def setUp(self):
        self.initial_password = 'Password123!'
        self.user = CustomUser.objects.create_user(
            email='testpwd@entreno.pro',
            password=self.initial_password,
            first_name='Carlos',
            last_name='Sainz'
        )
        AthleteProfile.objects.create(user=self.user)

    def test_password_change_requires_login(self):
        """Los usuarios no autenticados son redirigidos al inicio de sesión."""
        response = self.client.get(reverse('users:password_change'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_profile_contains_password_change_link_and_section(self):
        """La página de perfil muestra el acceso y la sección de cambio de contraseña."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('users:profile_edit'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('users:password_change'))
        self.assertContains(response, 'Seguridad y Acceso')
        self.assertContains(response, 'Cambiar contraseña')

    def test_password_change_page_loads_with_form(self):
        """La vista de cambio de contraseña carga correctamente con los campos requeridos."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('users:password_change'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cambiar Contraseña')
        self.assertContains(response, 'Contraseña actual')
        self.assertContains(response, 'Nueva contraseña')
        self.assertContains(response, 'Confirmar nueva contraseña')
        self.assertContains(response, reverse('users:profile_edit'))

    def test_password_change_success(self):
        """Cambio exitoso de contraseña: se actualiza el hash, se mantiene la sesión y redirige al perfil."""
        self.client.force_login(self.user)
        new_password = 'NuevaPasswordSegura2026!'

        response = self.client.post(reverse('users:password_change'), {
            'old_password': self.initial_password,
            'new_password1': new_password,
            'new_password2': new_password,
        }, follow=True)

        self.assertRedirects(response, reverse('users:profile_edit'))

        # Verificar que la contraseña ha cambiado en la base de datos
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(self.user.check_password(self.initial_password))

        # Verificar que la sesión sigue activa (usuario autenticado)
        self.assertTrue('_auth_user_id' in self.client.session)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.id)

        # Verificar que la redirección muestra el mensaje de confirmación
        self.assertContains(response, "Tu contraseña ha sido actualizada con éxito.")

    def test_password_change_fails_with_incorrect_old_password(self):
        """Falla si la contraseña actual no coincide."""
        self.client.force_login(self.user)
        response = self.client.post(reverse('users:password_change'), {
            'old_password': 'ContrasenaErronea123',
            'new_password1': 'NuevaValida999!',
            'new_password2': 'NuevaValida999!',
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.initial_password))

    def test_password_change_fails_when_passwords_do_not_match(self):
        """Falla si la nueva contraseña y su confirmación no coinciden."""
        self.client.force_login(self.user)
        response = self.client.post(reverse('users:password_change'), {
            'old_password': self.initial_password,
            'new_password1': 'NuevaPassword123!',
            'new_password2': 'PasswordDiferente456!',
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.initial_password))

    def test_password_change_fails_if_too_short(self):
        """Falla si la nueva contraseña no cumple los requisitos de longitud mínima."""
        self.client.force_login(self.user)
        response = self.client.post(reverse('users:password_change'), {
            'old_password': self.initial_password,
            'new_password1': 'abc',
            'new_password2': 'abc',
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.initial_password))

    def test_password_change_done_page(self):
        """La vista de confirmación carga correctamente."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('users:password_change_done'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¡Contraseña actualizada!')


TEMP_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class ProfilePictureTests(TestCase):
    """Pruebas para la subida, visualización y eliminación de la fotografía de perfil de usuario."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def _create_image(self, name='avatar.jpg'):
        file = io.BytesIO()
        img = Image.new('RGB', (100, 100), color=(37, 99, 235))
        img.save(file, 'jpeg')
        file.seek(0)
        return SimpleUploadedFile(name, file.read(), content_type='image/jpeg')

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='fotousuario@entreno.pro',
            password='testPassword123!',
            first_name='Laura',
            last_name='García'
        )
        self.athlete_profile = AthleteProfile.objects.create(
            user=self.user,
            sport='crossfit',
            experience_level='avanzado',
            training_goal='potencia_explosiva'
        )

    def test_default_avatar_shows_user_icon_placeholder(self):
        """Si el usuario no tiene foto, se muestra el icono de usuario por defecto y no la imagen."""
        self.client.force_login(self.user)
        self.assertFalse(self.user.has_profile_picture)

        response = self.client.get(reverse('users:profile_edit'))
        self.assertEqual(response.status_code, 200)
        # Contiene el contenedor de placeholder de usuario
        self.assertContains(response, 'id="avatar-placeholder"')
        self.assertContains(response, 'Sin foto')

        # También en el menú base / barra lateral
        home_resp = self.client.get(reverse('home'))
        self.assertEqual(home_resp.status_code, 200)
        self.assertContains(home_resp, 'title="Usuario"')

    def test_athlete_can_upload_profile_picture(self):
        """Un deportista puede subir una fotografía desde su perfil."""
        self.client.force_login(self.user)
        image = self._create_image('laura.jpg')

        response = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Laura',
            'last_name': 'García',
            'sport': 'crossfit',
            'experience_level': 'avanzado',
            'training_goal': 'potencia_explosiva',
            'profile_picture': image,
        })
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.has_profile_picture)
        self.assertIn('laura', self.user.profile_picture.name)

        # La página de perfil ahora debe renderizar la URL de la imagen
        profile_resp = self.client.get(reverse('users:profile_edit'))
        self.assertContains(profile_resp, self.user.profile_picture.url)

    def test_athlete_can_delete_profile_picture(self):
        """Un deportista puede eliminar su fotografía y volver al icono de usuario por defecto."""
        self.user.profile_picture = self._create_image('a_borrar.jpg')
        self.user.save()
        self.assertTrue(self.user.has_profile_picture)

        self.client.force_login(self.user)
        response = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Laura',
            'last_name': 'García',
            'sport': 'crossfit',
            'experience_level': 'avanzado',
            'training_goal': 'potencia_explosiva',
            'delete_profile_picture': '1',
        })
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertFalse(self.user.has_profile_picture)
        self.assertFalse(bool(self.user.profile_picture))

    def test_trainer_can_upload_and_delete_profile_picture(self):
        """Un usuario entrenador sin perfil deportista también puede subir y eliminar su fotografía."""
        trainer = CustomUser.objects.create_user(
            email='entrenador@entreno.pro',
            password='testPassword123!',
            first_name='Sergio',
            last_name='Ramos'
        )
        TrainerProfile.objects.create(user=trainer)

        self.client.force_login(trainer)

        # Subida
        image = self._create_image('sergio.jpg')
        response = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Sergio',
            'last_name': 'Ramos',
            'profile_picture': image,
        })
        self.assertEqual(response.status_code, 302)

        trainer.refresh_from_db()
        self.assertTrue(trainer.has_profile_picture)
        self.assertIn('sergio', trainer.profile_picture.name)

        # Borrado
        del_response = self.client.post(reverse('users:profile_edit'), {
            'first_name': 'Sergio',
            'last_name': 'Ramos',
            'delete_profile_picture': '1',
        })
        self.assertEqual(del_response.status_code, 302)

        trainer.refresh_from_db()
        self.assertFalse(trainer.has_profile_picture)



