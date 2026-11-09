from datetime import date
from django.test import TestCase
from django.urls import reverse
from users.models import CustomUser, AthleteProfile, TrainerProfile, AthleteProgressLog


class HomeRenderTmp(TestCase):
    def test_render_both_tabs(self):
        coach = CustomUser.objects.create_user(email='c@t.com', password='x', first_name='Ana', last_name='Coach')
        TrainerProfile.objects.create(user=coach)
        u = CustomUser.objects.create_user(email='d@t.com', password='x', first_name='Kike', last_name='Dual')
        p = AthleteProfile.objects.create(user=u, weight=80, height=180, fat_percentage=15, lean_mass_percentage=80,
                                          assigned_trainer=coach, sport='mma')
        TrainerProfile.objects.create(user=u)
        AthleteProfile.objects.create(user=CustomUser.objects.create_user(email='a@t.com', password='x'), assigned_trainer=u)
        AthleteProgressLog.objects.create(athlete=p, date=date.today(), weight=80, fat_percentage=15)
        self.client.force_login(u)
        r = self.client.get(reverse('home') + '?tab=athlete')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ana Coach')
        self.assertContains(r, 'evolutionChart')
        r2 = self.client.get(reverse('home') + '?tab=trainer')
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, 'Distribución de Carga')
        self.assertEqual(sum(r2.context['acwr_distribution'].values()), 1)
