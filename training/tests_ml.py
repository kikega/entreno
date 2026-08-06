import os
import shutil
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.contrib.auth import get_user_model

from users.models import TrainerProfile, AthleteProfile
from training.models import WorkoutPlan, LoggedExercise, LoggedSet, WorkoutSession
from training.analytics import calculate_1rm_brzycki, calculate_srpe, calculate_acwr
from training.ml_engine import SportTemplateEngine, SmartPlanGenerator
from training.ml.build_dataset import build_supervised_dataset, MIN_SAMPLES_FOR_TRAINING
from training.ml.model import train_model
from training.ml.predict import (
    predict_next_load,
    predict_with_model,
    build_prediction_features,
)

User = get_user_model()


class AnalyticsAndMLTestCase(TestCase):
    """Pruebas unitarias e integración para la analítica (1RM, sRPE, ACWR) y el
    motor de sugerencias de ML (dataset, entrenamiento, predicción y cold start)."""

    def setUp(self):
        self.trainer_user = User.objects.create_user(
            email='entrenador_ml@test.com', password='Password123!',
            first_name='Carlos', last_name='Trainer',
        )
        self.trainer = TrainerProfile.objects.create(user=self.trainer_user)

        self.athlete_user = User.objects.create_user(
            email='deportista_mma@test.com', password='Password123!',
            first_name='Alex', last_name='Fighter',
        )
        self.athlete = AthleteProfile.objects.create(
            user=self.athlete_user, weight=77.0, height=178.0, sport='mma',
            experience_level='avanzado', training_goal='potencia_explosiva',
            assigned_trainer=self.trainer_user, trainer_confirmed=True,
        )

        self._tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)

    def _seed_sets(self, weights):
        """Genera un plan con una sesión y una serie progresiva por peso."""
        plan = SmartPlanGenerator.generate_plan_for_athlete(self.trainer, self.athlete)
        session = WorkoutSession.objects.create(
            workout_plan=plan, athlete=self.athlete,
            duration_minutes=60, session_rpe=8.0,
        )
        logged = LoggedExercise.objects.create(
            workout_session=session, planned_exercise=plan.planned_exercises.first(),
        )
        for i, w in enumerate(weights, start=1):
            LoggedSet.objects.create(
                logged_exercise=logged, set_number=i, reps=10, weight_kg=w, rpe=8.0,
            )
        return plan

    def test_brzycki_formula(self):
        val_1rm = calculate_1rm_brzycki(100.0, 5)
        self.assertGreater(val_1rm, 110.0)
        self.assertLess(val_1rm, 115.0)

    def test_srpe_calculation(self):
        self.assertEqual(calculate_srpe(60, 8.5), 510.0)

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
        # En cold start el predictor cae a reglas y cada ejercicio lleva la fuente.
        for pe in plan.planned_exercises.all():
            self.assertIn('reglas', pe.notes)

    def test_predict_cold_start_falls_back_to_rules(self):
        plan = self._seed_sets([80.0, 82.0, 84.0])
        exercise = plan.planned_exercises.first().exercise
        previous = list(LoggedSet.objects.filter(
            logged_exercise__planned_exercise__exercise=exercise,
        ).order_by('completed_at'))
        suggestion = predict_next_load(self.athlete, exercise, previous)
        self.assertEqual(suggestion['source'], 'reglas')
        self.assertGreater(suggestion['suggested_weight_kg'], 0)
        self.assertIn('suggested_reps', suggestion)
        self.assertIn('recommendation_note', suggestion)

    def test_build_dataset_and_model_pipeline(self):
        plan = self._seed_sets([60.0, 62.5, 65.0, 67.5, 70.0, 72.5, 75.0])
        rows, targets = build_supervised_dataset()
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(len(rows), len(targets))

        exercise = plan.planned_exercises.first().exercise
        model_path = os.path.join(self._tmpdir, 'model.joblib')
        _, metrics = train_model(rows, targets, model_path=model_path)
        self.assertIn('val_mae', metrics)
        self.assertIn('n_samples', metrics)

        previous = list(LoggedSet.objects.filter(
            logged_exercise__workout_session__athlete=self.athlete,
            logged_exercise__planned_exercise__exercise=exercise,
        ).order_by('completed_at'))
        features = build_prediction_features(self.athlete, exercise, previous)
        prediction = predict_with_model(features, model_path=model_path)
        self.assertIsNotNone(prediction)
        self.assertGreater(prediction, 0)

    def test_train_command_insufficient_data(self):
        rows, _ = build_supervised_dataset()
        if len(rows) >= MIN_SAMPLES_FOR_TRAINING:
            self.skipTest('El dataset de prueba ya supera el mínimo de muestras')
        with self.assertRaises(CommandError):
            call_command('train_plan_model')