from datetime import date, timedelta
from typing import Dict, Any, Optional

from users.models import AthleteProfile, TrainerProfile
from training.models import Exercise, WorkoutPlan, PlannedExercise, LoggedSet
from training.ml.predict import predict_next_load


class SportTemplateEngine:
    """
    Motor de plantillas y selección de ejercicios basados en la ciencia del deporte
    para los deportes especificados: MMA, Karate, BJJ, CrossFit, Hyrox y Pérdida de Peso.
    """

    SPORT_TEMPLATES = {
        'mma': {
            'name': 'Plan de Potencia y Acondicionamiento MMA',
            'focus': 'Potencia Explosiva, Core Rotacional y Capacidad Láctica',
            'exercises': [
                {'name': 'Cargada de Fuerza (Power Clean)', 'category': 'potencia', 'movement_pattern': 'potencia_olimpica', 'sets': '4', 'reps': '3-5', 'load': '75-85%', 'rpe': '8.0', 'rest': '120s', 'notes': 'Foco en triple extensión explosiva de cadera para derribos.'},
                {'name': 'Sentadilla Trasera', 'category': 'fuerza', 'movement_pattern': 'dominante_rodilla', 'sets': '4', 'reps': '5', 'load': '80%', 'rpe': '8.5', 'rest': '120s', 'notes': 'Fuerza base de piernas.'},
                {'name': 'Dominadas neutras con agarre pesado', 'category': 'fuerza', 'movement_pattern': 'traccion_vertical', 'sets': '4', 'reps': '6-8', 'load': '75%', 'rpe': '8.0', 'rest': '90s', 'notes': 'Tracción específica para grappling y clinch.'},
                {'name': 'Press Landmine Rotacional', 'category': 'potencia', 'movement_pattern': 'core_rotacional', 'sets': '3', 'reps': '8/lado', 'load': 'RPE 8', 'rpe': '8.0', 'rest': '60s', 'notes': 'Transferencia directa al golpeo de puño (rotación de tronco).'},
                {'name': 'Empuje de Trineo (Sled Push Sprint)', 'category': 'pliometria', 'movement_pattern': 'metabolico', 'sets': '5', 'reps': '20m', 'load': 'Máxima velocidad', 'rpe': '9.0', 'rest': '60s', 'notes': 'Resistencia anaeróbica aláctica/láctica.'},
            ]
        },
        'karate': {
            'name': 'Plan de Velocidad Reaccional y Kime Karate',
            'focus': 'Velocidad de Reacción, Potencia Plantar y Movilidad de Cadera',
            'exercises': [
                {'name': 'Saltos Pleométricos a Cajón (Box Jumps)', 'category': 'pliometria', 'movement_pattern': 'dominante_rodilla', 'sets': '4', 'reps': '5', 'load': 'Peso corporal', 'rpe': '7.5', 'rest': '90s', 'notes': 'Máxima reactividad plantar para desplazamientos rápidos.'},
                {'name': 'Push Press Explosivo', 'category': 'potencia', 'movement_pattern': 'empuje_vertical', 'sets': '4', 'reps': '4-6', 'load': '70%', 'rpe': '8.0', 'rest': '90s', 'notes': 'Transferencia de fuerza desde pies a puño.'},
                {'name': 'Zancadas Búlgaras Explosivas', 'category': 'fuerza', 'movement_pattern': 'dominante_rodilla', 'sets': '3', 'reps': '6/pierna', 'load': '65%', 'rpe': '8.0', 'rest': '90s', 'notes': 'Estabilidad unipedal para patadas.'},
                {'name': 'Remo Horizontal con Mancuerna', 'category': 'fuerza', 'movement_pattern': 'traccion_horizontal', 'sets': '4', 'reps': '8', 'load': '75%', 'rpe': '8.0', 'rest': '60s', 'notes': 'Retracción escapular para recogida rápida de golpeo (hikite).'},
                {'name': 'Rotaciones de Cadera con Goma / Polea', 'category': 'movilidad', 'movement_pattern': 'core_rotacional', 'sets': '3', 'reps': '12/lado', 'load': 'Resistencia media', 'rpe': '7.0', 'rest': '45s', 'notes': 'Movilidad y velocidad de cadera en ataques.'},
            ]
        },
        'bjj': {
            'name': 'Plan de Fuerza e Isometría para Jiu-Jitsu (BJJ)',
            'focus': 'Fuerza de Agarre (Grip Strength), Tracción y Resistencia de Core',
            'exercises': [
                {'name': 'Peso Muerto Rumano (RDL)', 'category': 'fuerza', 'movement_pattern': 'dominante_cadera', 'sets': '4', 'reps': '6-8', 'load': '75%', 'rpe': '8.0', 'rest': '120s', 'notes': 'Cadena posterior fuerte para puentes y guardia.'},
                {'name': 'Dominadas colgado con Toalla (Grip Pull-ups)', 'category': 'fuerza', 'movement_pattern': 'isometria_agarre', 'sets': '4', 'reps': '6-8', 'load': 'Peso corporal', 'rpe': '8.5', 'rest': '90s', 'notes': 'Fortalecimiento de flexores de dedos y agarre de solapa (Gi).'},
                {'name': 'Sentadilla Zercher', 'category': 'fuerza', 'movement_pattern': 'dominante_rodilla', 'sets': '3', 'reps': '6', 'load': '70%', 'rpe': '8.0', 'rest': '120s', 'notes': 'Resistencia de presión frontal y postura en raspe/paso de guardia.'},
                {'name': 'Remo Pendlay con Barra', 'category': 'fuerza', 'movement_pattern': 'traccion_horizontal', 'sets': '4', 'reps': '6', 'load': '80%', 'rpe': '8.5', 'rest': '90s', 'notes': 'Tracción explosiva para desequilibrio (kuzushi).'},
                {'name': 'Paseo del Granjero (Farmers Walk)', 'category': 'fuerza', 'movement_pattern': 'isometria_agarre', 'sets': '4', 'reps': '40m', 'load': 'Carga pesada', 'rpe': '8.5', 'rest': '90s', 'notes': 'Resistencia global e isométrica de antebrazos.'},
            ]
        },
        'crossfit': {
            'name': 'Plan WOD Multimodal CrossFit',
            'focus': 'Capacidad de Trabajo Alta Intensidad, Halterofilia y Gimnásticos',
            'exercises': [
                {'name': 'Arrancada de Potencia (Power Snatch)', 'category': 'potencia', 'movement_pattern': 'potencia_olimpica', 'sets': '5', 'reps': '3', 'load': '75%', 'rpe': '8.0', 'rest': '90s', 'notes': 'Eficiencia técnica y potencia.'},
                {'name': 'Thrusters (Sentadilla + Press)', 'category': 'potencia', 'movement_pattern': 'empuje_vertical', 'sets': '4', 'reps': '8-10', 'load': '65%', 'rpe': '8.5', 'rest': '90s', 'notes': 'Combinación cuerpo completo alta demanda metabólica.'},
                {'name': 'Dominadas en Mariposa / Kipping (Chest-to-bar)', 'category': 'tecnica', 'movement_pattern': 'traccion_vertical', 'sets': '4', 'reps': '10-12', 'load': 'Peso corporal', 'rpe': '8.0', 'rest': '60s', 'notes': 'Eficiencia gimnástica en volumen.'},
                {'name': 'Kettlebell Swings Rusos', 'category': 'potencia', 'movement_pattern': 'dominante_cadera', 'sets': '4', 'reps': '15', 'load': '24kg/16kg', 'rpe': '8.0', 'rest': '60s', 'notes': 'Potencia de cadera intermitente.'},
                {'name': 'Intervalos Remo Ergómetro', 'category': 'velocidad', 'movement_pattern': 'metabolico', 'sets': '5', 'reps': '500m', 'load': 'Ritmo 2K -2s', 'rpe': '9.0', 'rest': '90s', 'notes': 'Capacidad cardiorrespiratoria VO2Max.'},
            ]
        },
        'hyrox': {
            'name': 'Plan Específico Hyrox Competición',
            'focus': 'Fuerza-Resistencia Intermitente, Empuje de Trineo y Carrera',
            'exercises': [
                {'name': 'Sled Push (Empuje de Trineo Pesado)', 'category': 'fuerza', 'movement_pattern': 'metabolico', 'sets': '4', 'reps': '50m', 'load': 'Carga Hyrox', 'rpe': '8.5', 'rest': '90s', 'notes': 'Simulación de estación Hyrox Sled Push.'},
                {'name': 'Wall Balls Target', 'category': 'potencia', 'movement_pattern': 'empuje_vertical', 'sets': '4', 'reps': '20', 'load': '9kg/6kg', 'rpe': '8.5', 'rest': '60s', 'notes': 'Profundidad de sentadilla y lanzamiento diana.'},
                {'name': 'Zancadas Caminadas con Saco (Sandbag Lunge)', 'category': 'fuerza', 'movement_pattern': 'dominante_rodilla', 'sets': '4', 'reps': '30m', 'load': '20kg/10kg', 'rpe': '8.5', 'rest': '60s', 'notes': 'Tolerancia al lactato en cuádriceps.'},
                {'name': 'SkiErg Intervalos', 'category': 'velocidad', 'movement_pattern': 'metabolico', 'sets': '4', 'reps': '500m', 'load': 'Ritmo 1:50/1000m', 'rpe': '8.5', 'rest': '60s', 'notes': 'Resistencia de tren superior e intercostales.'},
                {'name': 'Burpee Broad Jumps (Salto de Longitud)', 'category': 'pliometria', 'movement_pattern': 'potencia_olimpica', 'sets': '3', 'reps': '15m', 'load': 'Peso corporal', 'rpe': '9.0', 'rest': '90s', 'notes': 'Potencia bajo fatiga extrema.'},
            ]
        },
        'weight_loss': {
            'name': 'Plan Metabólico y Preservación de Masa Magra',
            'focus': 'Gasto Calórico Elevado, Circuitos HIIPA y Protección Muscular',
            'exercises': [
                {'name': 'Goblet Squat con Mancuerna', 'category': 'fuerza', 'movement_pattern': 'dominante_rodilla', 'sets': '4', 'reps': '12', 'load': 'Moderado', 'rpe': '7.5', 'rest': '45s', 'notes': 'Activación de grandes grupos musculares.'},
                {'name': 'Push-Ups (Flexiones) o Press Banca Inclinado', 'category': 'fuerza', 'movement_pattern': 'empuje_horizontal', 'sets': '4', 'reps': '10-12', 'load': 'Autocarga / Moderado', 'rpe': '7.5', 'rest': '45s', 'notes': 'Mantenimiento de masa muscular en déficit.'},
                {'name': 'Kettlebell Swings Metabólicos', 'category': 'potencia', 'movement_pattern': 'dominante_cadera', 'sets': '4', 'reps': '20', 'load': '16kg/12kg', 'rpe': '8.0', 'rest': '30s', 'notes': 'Aumento del consumo de oxígeno post-ejercicio (EPOC).'},
                {'name': 'Remo con Polea Baja', 'category': 'fuerza', 'movement_pattern': 'traccion_horizontal', 'sets': '4', 'reps': '12', 'load': 'Moderado', 'rpe': '7.5', 'rest': '45s', 'notes': 'Postura y balance de tren superior.'},
                {'name': 'Circuito Cardiorrespiratorio (Air Bike / Saltos Comba)', 'category': 'velocidad', 'movement_pattern': 'metabolico', 'sets': '4', 'reps': '45s ON / 15s OFF', 'load': 'Alta intensidad', 'rpe': '8.5', 'rest': '60s entre rondas', 'notes': 'Maximización de quemado de grasa.'},
            ]
        }
    }

    @classmethod
    def get_template(cls, sport: str) -> Dict[str, Any]:
        """
        Retorna la plantilla específica para el deporte o una por defecto.
        """
        return cls.SPORT_TEMPLATES.get(sport, cls.SPORT_TEMPLATES['mma'])


class SmartPlanGenerator:
    """
    Genera una propuesta completa de WorkoutPlan a partir de la plantilla del
    deporte del atleta y las sugerencias de carga del predictor ML.

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
        template = SportTemplateEngine.get_template(sport)

        # 1. Crear el objeto WorkoutPlan
        plan = WorkoutPlan.objects.create(
            name=f"{template['name']} - {athlete_profile.user.first_name or 'Deportista'}",
            trainer=trainer_profile,
            athlete=athlete_profile,
            sport=sport,
            target_date=target_date,
            is_completed=False
        )

        predictor = predict_next_load

        # 2. Asignar los ejercicios de la plantilla
        for order, ex_data in enumerate(template['exercises'], start=1):
            # Buscar o crear el ejercicio correspondiente en el sistema
            exercise_obj, _ = Exercise.objects.get_or_create(
                name=ex_data['name'],
                created_by=trainer_profile,
                defaults={
                    'category': ex_data['category'],
                    'movement_pattern': ex_data['movement_pattern'],
                    'sport_tags': [sport],
                    'description': ex_data['notes']
                }
            )

            # Buscar historial previo en LoggedSet para este deportista y ejercicio
            previous_sets = list(LoggedSet.objects.filter(
                logged_exercise__workout_session__athlete=athlete_profile,
                logged_exercise__planned_exercise__exercise=exercise_obj
            ).order_by('completed_at')[:10])

            progression = predictor(athlete_profile, exercise_obj, previous_sets)

            suggested_load = ex_data['load']
            if progression['suggested_weight_kg'] > 0:
                suggested_load = f"{progression['suggested_weight_kg']} kg"

            notes_full = (
                f"{ex_data['notes']}\n"
                f"💡 Sugerencia ({progression['source']}): "
                f"{progression['recommendation_note']}"
            )

            PlannedExercise.objects.create(
                workout_plan=plan,
                exercise=exercise_obj,
                order=order,
                sets=ex_data['sets'],
                reps=ex_data['reps'],
                load=suggested_load,
                rpe=str(progression['suggested_rpe']),
                rest=ex_data['rest'],
                focus=template['focus'],
                notes=notes_full
            )

        return plan
