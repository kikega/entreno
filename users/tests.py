from django.test import TestCase
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

