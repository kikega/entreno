from datetime import date, timedelta
from typing import Dict, Any, Optional

from users.models import AthleteProfile, TrainerProfile
from training.models import (
    Exercise, WorkoutPlan, PlannedExercise, LoggedSet,
    DisciplineTemplate, TemplateExercise, ExerciseDisciplineFit,
)
from training.ml.predict import predict_next_load


class SportTemplateEngine:
    """
    Motor de selección de plantillas por disciplina gestionadas en BD.
    Aporta la capa estructural (qué ejercicios, sets, reps, descanso) y permite
    ampliar las recomendaciones desde el catálogo de ejercicios marcado con un
    nivel de encaje (fit) para cada deporte. La capa de carga/RPE la resuelve ML.
    """

    @staticmethod
    def get_default_template(sport: str) -> Optional[DisciplineTemplate]:
        """Devuelve la plantilla global activa del deporte o None si no existe."""
        return DisciplineTemplate.objects.filter(
            sport=sport, is_default=True, is_active=True
        ).first()

    @staticmethod
    def get_trainer_template(sport: str, trainer_profile) -> Optional[DisciplineTemplate]:
        """Devuelve la copia activa del entrenador para el deporte, si existe."""
        if trainer_profile is None:
            return None
        return DisciplineTemplate.objects.filter(
            sport=sport, created_by=trainer_profile, is_active=True
        ).first()

    @classmethod
    def resolve_template(cls, sport: str, trainer_profile=None) -> Optional[DisciplineTemplate]:
        """
        Prioriza la copia del entrenador; si no hay, usa la plantilla global.
        Devuelve None si ninguna está disponible.
        """
        return (
            cls.get_trainer_template(sport, trainer_profile)
            or cls.get_default_template(sport)
        )

    @classmethod
    def clone_to_trainer(cls, template: DisciplineTemplate, trainer_profile) -> DisciplineTemplate:
        """
        Crea una copia editable de una plantilla global para un entrenador,
        de modo que sus cambios no afecten a otros ni a la del sistema.
        """
        copy = DisciplineTemplate.objects.create(
            name=template.name,
            sport=template.sport,
            focus=template.focus,
            is_default=False,
            is_active=True,
            created_by=trainer_profile,
            parent=template,
        )
        for item in template.items.all():
            TemplateExercise.objects.create(
                template=copy,
                exercise=item.exercise,
                order=item.order,
                sets=item.sets,
                reps=item.reps,
                load=item.load,
                rpe=item.rpe,
                rest=item.rest,
                notes=item.notes,
            )
        return copy

    @staticmethod
    def suggest_more_exercises(sport: str, template=None, limit: int = 5):
        """
        Sugiere ejercicios del catálogo que encajan con la disciplina, ordenados
        por mayor ajuste (fit). Excluye los ya presentes en la plantilla.
        """
        qs = Exercise.objects.filter(
            discipline_fits__sport=sport,
            discipline_fits__fit__gte=3,
        )
        if template is not None:
            existing = template.items.values_list('exercise_id', flat=True)
            qs = qs.exclude(pk__in=existing)
        return list(qs.order_by('-discipline_fits__fit', 'name')[:limit])


class SmartPlanGenerator:
    """
    Genera una propuesta completa de WorkoutPlan a partir de la plantilla del
    deporte del atleta (gestionable en BD) y las sugerencias de carga del
    predictor ML.

    El resultado es un borrador: el entrenador lo revisa y ajusta antes de
    confirmarlo con el deportista.
    """

    @classmethod
    def generate_plan_for_athlete(cls, trainer_profile: TrainerProfile, athlete_profile: AthleteProfile, target_date: Optional[date] = None) -> WorkoutPlan:
        """
        Crea un nuevo WorkoutPlan estructurado en la BD con ejercicios sugeridos
        según el deporte del atleta y cargas sugeridas por el predictor.
        """
        if target_date is None:
            target_date = date.today() + timedelta(days=1)

        sport = athlete_profile.sport
        template = SportTemplateEngine.resolve_template(sport, trainer_profile)
        if template is None:
            raise ValueError(
                f"No hay una plantilla de plan configurada para el deporte '{sport}'."
            )

        # 1. Crear el objeto WorkoutPlan
        plan = WorkoutPlan.objects.create(
            name=f"{template.name} - {athlete_profile.user.first_name or 'Deportista'}",
            trainer=trainer_profile,
            athlete=athlete_profile,
            sport=sport,
            target_date=target_date,
            is_completed=False
        )

        predictor = predict_next_load

        # 2. Asignar los ejercicios de la plantilla
        for order, item in enumerate(template.items.all(), start=1):
            exercise_obj = item.exercise

            # Buscar historial previo en LoggedSet para este deportista y ejercicio
            previous_sets = list(LoggedSet.objects.filter(
                logged_exercise__workout_session__athlete=athlete_profile,
                logged_exercise__planned_exercise__exercise=exercise_obj
            ).order_by('completed_at')[:10])

            progression = predictor(athlete_profile, exercise_obj, previous_sets)

            suggested_load = item.load
            if progression['suggested_weight_kg'] > 0:
                suggested_load = f"{progression['suggested_weight_kg']} kg"

            notes_full = (
                f"{item.notes or ''}\n"
                f"💡 Sugerencia ({progression['source']}): "
                f"{progression['recommendation_note']}"
            )

            PlannedExercise.objects.create(
                workout_plan=plan,
                exercise=exercise_obj,
                order=order,
                sets=item.sets,
                reps=item.reps,
                load=suggested_load,
                rpe=str(progression['suggested_rpe']),
                rest=item.rest,
                focus=template.focus,
                notes=notes_full
            )

        return plan