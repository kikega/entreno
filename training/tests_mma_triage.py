from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from training.models import MMATriageProfile, TrainerNotification
from users.models import AthleteProfile, AthleteProgressLog, TrainerProfile

User = get_user_model()


def athlete_payload(**overrides):
    data = {
        'fasting_weight_kg': '78.0',
        'target_weight_category_kg': '70.3',
        'tactical_style': 'mma_hibrido',
        'next_fight_date': (date.today() + timedelta(weeks=10)).isoformat(),
        'weigh_in_rule': 'profesional_24h',
        'body_composition_goal': 'corte_peso',
        'strength_experience': 'intermedio',
        'olympic_lifts_relation': 'domina_motivado',
        'knows_rm_marks': 'on',
        'rm_format': '3rm',
        'back_squat_rm_kg': '110',
        'bench_press_rm_kg': '100',
        'strict_pullup_external_load_kg': '10',
        'wingate_modality': 'airbike_w',
        'wingate_sprint_1': '700',
        'wingate_sprint_2': '520',
        'isa_angle': '',
        'available_days_per_week': '3',
        'available_equipment': ['Rack', 'Balones medicinales LIGEROS (<= 6 kg)'],
        'tatami_weekly_volume': 'alta',
        'hard_sparring_days': ['martes', 'jueves'],
        'occupational_activity': 'sedentario',
        'current_joint_pain_zones': ['Hombros'],
        'accepted_terms_of_service': 'on',
        'accepted_privacy_policy': 'on',
        'accepted_medical_waiver': 'on',
    }
    data.update(overrides)
    return data


class MMATriagePhase2Tests(TestCase):
    """Fase 2: Ficha Única de Triage, Reset on Submit, blindaje privado y Cerrojo Manual."""

    def setUp(self):
        self.trainer_user = User.objects.create_user(email='jorge@test.com', password='Password123!', first_name='Jorge')
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)
        self.other_trainer_user = User.objects.create_user(email='otro@test.com', password='Password123!')
        TrainerProfile.objects.create(user=self.other_trainer_user)

        self.athlete_user = User.objects.create_user(email='fighter@test.com', password='Password123!', first_name='Ilia')
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user, sport='mma',
            assigned_trainer=self.trainer_user, trainer_confirmed=True,
        )
        self.athlete_url = reverse('training:athlete_mma_triage')
        self.trainer_url = reverse('training:trainer_mma_triage', kwargs={'pk': self.athlete.pk})

    def test_athlete_submission_triggers_reset_on_submit(self):
        """El envío del atleta guarda datos, sincroniza peso, crea alerta + email y pone PENDIENTE."""
        self.client.force_login(self.athlete_user)
        self.assertEqual(self.client.get(self.athlete_url).status_code, 200)

        res = self.client.post(self.athlete_url, athlete_payload())
        self.assertEqual(res.status_code, 302)

        triage = MMATriageProfile.objects.get(athlete=self.athlete)
        self.assertEqual(triage.review_status, 'pendiente_revision')
        self.assertFalse(triage.approved_for_generation)
        self.assertIsNotNone(triage.legal_accepted_at)
        self.assertEqual(triage.hard_sparring_days, ['martes', 'jueves'])
        self.assertTrue(triage.has_light_medball)

        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.weight, Decimal('78.00'))
        self.assertTrue(AthleteProgressLog.objects.filter(athlete=self.athlete).exists())

        notif = TrainerNotification.objects.get(trainer=self.trainer, athlete=self.athlete)
        self.assertIn('ha actualizado su ficha', notif.message)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.trainer_user.email, mail.outbox[0].to)

    def test_athlete_cannot_overwrite_private_trainer_columns(self):
        """Aunque el atleta inyecte campos privados en el POST, se ignoran y el cerrojo se resetea."""
        triage = MMATriageProfile.objects.create(
            athlete=self.athlete,
            hard_overrides_locks=['activar_candado_excentrico'],
            biomechanical_vetoes=['veto_carga_axial_espinal'],
            private_clinical_notes='Hernia L5-S1',
            approved_for_generation=True,
            review_status='aprobado',
            isa_angle='ancho',
        )
        self.client.force_login(self.athlete_user)
        payload = athlete_payload(
            isa_angle='ancho',
            hard_overrides_locks=['abrir_candado_olimpico'],
            biomechanical_vetoes=[],
            private_clinical_notes='hackeado',
            approved_for_generation='on',
        )
        self.client.post(self.athlete_url, payload)
        triage.refresh_from_db()
        self.assertEqual(triage.hard_overrides_locks, ['activar_candado_excentrico'])
        self.assertEqual(triage.biomechanical_vetoes, ['veto_carga_axial_espinal'])
        self.assertEqual(triage.private_clinical_notes, 'Hernia L5-S1')
        self.assertFalse(triage.approved_for_generation)
        self.assertEqual(triage.review_status, 'pendiente_revision')

    def test_private_notes_never_rendered_to_athlete(self):
        MMATriageProfile.objects.create(athlete=self.athlete, private_clinical_notes='SECRETO_CLINICO_XYZ')
        self.client.force_login(self.athlete_user)
        res = self.client.get(self.athlete_url)
        self.assertNotContains(res, 'SECRETO_CLINICO_XYZ')
        self.assertNotContains(res, 'APROBAR_Y_GENERAR_IA')

    def test_legal_checkboxes_are_mandatory(self):
        self.client.force_login(self.athlete_user)
        payload = athlete_payload()
        payload.pop('accepted_medical_waiver')
        res = self.client.post(self.athlete_url, payload)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(
            MMATriageProfile.objects.filter(athlete=self.athlete, review_status='pendiente_revision').exists()
        )

    def test_trainer_approves_and_locks(self):
        """El entrenador completa ISA, vetos y activa el cerrojo; las alertas pasan a leídas."""
        self.client.force_login(self.athlete_user)
        self.client.post(self.athlete_url, athlete_payload())

        self.client.force_login(self.trainer_user)
        self.assertEqual(self.client.get(self.trainer_url).status_code, 200)
        res = self.client.post(self.trainer_url, {
            'fasting_weight_kg': '78.0',
            'target_weight_category_kg': '70.3',
            'isa_angle': 'estrecho',
            'knows_rm_marks': 'on',
            'rm_format': '3rm',
            'back_squat_rm_kg': '110',
            'bench_press_rm_kg': '100',
            'strict_pullup_external_load_kg': '10',
            'wingate_modality': 'airbike_w',
            'wingate_sprint_1': '700',
            'wingate_sprint_2': '520',
            'current_joint_pain_zones': ['Hombros'],
            'accepted_terms_of_service': 'on',
            'accepted_privacy_policy': 'on',
            'accepted_medical_waiver': 'on',
            'hard_overrides_locks': ['activar_candado_empuje'],
            'biomechanical_vetoes': ['veto_empuje_vertical_overhead'],
            'private_clinical_notes': 'Pinzamiento subacromial derecho.',
            'approved_for_generation': 'on',
        })
        self.assertEqual(res.status_code, 302)
        triage = MMATriageProfile.objects.get(athlete=self.athlete)
        self.assertEqual(triage.review_status, 'aprobado')
        self.assertTrue(triage.approved_for_generation)
        self.assertEqual(triage.isa_angle, 'estrecho')
        self.assertEqual(triage.reviewed_by, self.trainer)
        self.assertFalse(TrainerNotification.objects.filter(trainer=self.trainer, is_read=False).exists())

        # Una nueva edición del atleta vuelve a bloquear el cerrojo (Reset on Submit)
        self.client.force_login(self.athlete_user)
        self.client.post(self.athlete_url, athlete_payload(isa_angle='estrecho', fasting_weight_kg='76.5'))
        triage.refresh_from_db()
        self.assertFalse(triage.approved_for_generation)
        self.assertEqual(triage.review_status, 'pendiente_revision')
        self.assertEqual(triage.private_clinical_notes, 'Pinzamiento subacromial derecho.')

    def test_trainer_cannot_approve_without_legal_or_with_conflicting_locks(self):
        self.client.force_login(self.trainer_user)
        res = self.client.post(self.trainer_url, {
            'hard_overrides_locks': ['abrir_candado_olimpico', 'cerrar_candado_olimpico'],
            'approved_for_generation': 'on',
        })
        self.assertEqual(res.status_code, 200)
        triage = MMATriageProfile.objects.get(athlete=self.athlete)
        self.assertFalse(triage.approved_for_generation)

    def test_foreign_trainer_has_no_access(self):
        self.client.force_login(self.other_trainer_user)
        self.assertEqual(self.client.get(self.trainer_url).status_code, 404)

    def test_derived_metrics(self):
        triage = MMATriageProfile(
            athlete=self.athlete,
            fasting_weight_kg=Decimal('80'), target_weight_category_kg=Decimal('70.3'),
            knows_rm_marks=True, rm_format='3rm',
            back_squat_rm_kg=Decimal('120'), bench_press_rm_kg=Decimal('110'),
            strict_pullup_external_load_kg=Decimal('0'),
            wingate_sprint_1=Decimal('700'), wingate_sprint_2=Decimal('525'),
            next_fight_date=date.today() + timedelta(weeks=10),
        )
        self.assertEqual(triage.squat_e1rm_kg, 132.0)
        self.assertEqual(triage.squat_bw_ratio, 1.65)
        self.assertEqual(triage.push_pull_ratio, round(121.0 / 88.0, 2))  # > 1.15 → candado empuje
        self.assertEqual(triage.wingate_drop_pct, 25.0)
        self.assertEqual(triage.weight_cut_kg, 9.7)
        self.assertTrue(triage.computed_phase_label.startswith('Pre-Training Camp'))

    def test_trainer_dashboard_shows_alerts(self):
        self.client.force_login(self.athlete_user)
        self.client.post(self.athlete_url, athlete_payload())
        self.client.force_login(self.trainer_user)
        res = self.client.get(reverse('home') + '?tab=trainer')
        self.assertContains(res, 'ha actualizado su ficha')
        notif = TrainerNotification.objects.get()
        res = self.client.post(reverse('training:mark_notification_read', kwargs={'notification_id': notif.pk}))
        self.assertEqual(res.status_code, 302)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
