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
