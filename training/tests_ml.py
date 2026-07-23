from django.test import TestCase
from django.contrib.auth import get_user_model
from users.models import TrainerProfile, AthleteProfile
from training.models import WorkoutPlan, Exercise, LoggedExercise, LoggedSet, WorkoutSession
from training.analytics import calculate_1rm_brzycki, calculate_srpe, calculate_acwr
from training.ml_engine import SportTemplateEngine, LoadProgressionPredictor, SmartPlanGenerator

User = get_user_model()


class AnalyticsAndMLTestCase(TestCase):

    def setUp(self):
        self.trainer_user = User.objects.create_user(
            email='entrenador_ml@test.com',
            password='Password123!',
            first_name='Carlos',
            last_name='Trainer'
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        self.athlete_user = User.objects.create_user(
            email='deportista_mma@test.com',
            password='Password123!',
            first_name='Alex',
            last_name='Fighter'
        )
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user,
            weight=77.0,
            height=178.0,
            sport='mma',
            experience_level='avanzado',
            training_goal='potencia_explosiva',
            assigned_trainer=self.trainer_user,
            trainer_confirmed=True
        )

    def test_brzycki_formula(self):
        val_1rm = calculate_1rm_brzycki(100.0, 5)
        self.assertGreater(val_1rm, 110.0)
        self.assertLess(val_1rm, 115.0)

    def test_srpe_calculation(self):
        srpe = calculate_srpe(60, 8.5)
        self.assertEqual(srpe, 510.0)

    def test_acwr_calculation(self):
        acwr = calculate_acwr(self.athlete)
        self.assertIn('acwr_ratio', acwr)
        self.assertIn('risk_status', acwr)

    def test_sport_template_engine(self):
        for sport in ['mma', 'karate', 'bjj', 'crossfit', 'hyrox', 'weight_loss']:
            tpl = SportTemplateEngine.get_template(sport)
            self.assertIn('name', tpl)
            self.assertGreaterEqual(len(tpl['exercises']), 4)

    def test_smart_plan_generator(self):
        plan = SmartPlanGenerator.generate_plan_for_athlete(self.trainer, self.athlete)
        self.assertIsInstance(plan, WorkoutPlan)
        self.assertEqual(plan.sport, 'mma')
        self.assertGreaterEqual(plan.planned_exercises.count(), 5)

    def test_logged_set_creation(self):
        plan = SmartPlanGenerator.generate_plan_for_athlete(self.trainer, self.athlete)
        planned_ex = plan.planned_exercises.first()

        session = WorkoutSession.objects.create(
            workout_plan=plan,
            athlete=self.athlete,
            duration_minutes=60,
            session_rpe=8.0
        )

        logged_ex = LoggedExercise.objects.create(
            workout_session=session,
            planned_exercise=planned_ex
        )

        set1 = LoggedSet.objects.create(
            logged_exercise=logged_ex,
            set_number=1,
            reps=5,
            weight_kg=80.0,
            rpe=8.5
        )

        self.assertEqual(float(set1.weight_kg), 80.0)
        self.assertEqual(set1.reps, 5)
        self.assertEqual(logged_ex.sets.count(), 1)
