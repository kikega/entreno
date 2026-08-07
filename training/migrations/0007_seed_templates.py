"""Siembra las plantillas por disciplina y el catálogo de ejercicios de las
antiguas SPORT_TEMPLATES en la BD como plantillas globales (is_default=True,
created_by=None). Se conservan los mismos ejercicios como catálogo del sistema
y se registra su encaje (fit) por disciplina."""

from django.db import migrations

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
            {'name': 'Intervalos Remo Ergómetro', 'category': 'velocidad', 'movement_pattern': 'metabolico', 'sets': '5', 'reps': '500m', 'load': 'Ritmo 2K -2s', 'rpe': '9.0', 'rest': '90s', 'notes': 'Capacidad cardirrespiratoria VO2Max.'},
        ],
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
        ],
    },
    'weight_loss': {
        'name': 'Plan Metabólico y Preservación de Masa Magra',
        'focus': 'Gasto Calórico Elevado, Circuitos HIIPA y Protección Muscular',
        'exercises': [
            {'name': 'Goblet Squat con Mancuerna', 'category': 'fuerza', 'movement_pattern': 'dominante_rodilla', 'sets': '4', 'reps': '12', 'load': 'Moderado', 'rpe': '7.5', 'rest': '45s', 'notes': 'Activación de grandes grupos musculares.'},
            {'name': 'Push-Ups (Flexiones) o Press Banca Inclinado', 'category': 'fuerza', 'movement_pattern': 'empuje_horizontal', 'sets': '4', 'reps': '10-12', 'load': 'Autocarga / Moderado', 'rpe': '7.5', 'rest': '45s', 'notes': 'Mantenimiento de masa muscular en déficit.'},
            {'name': 'Kettlebell Swings Metabólicos', 'category': 'potencia', 'movement_pattern': 'dominante_cadera', 'sets': '4', 'reps': '20', 'load': '16kg/12kg', 'rpe': '8.0', 'rest': '30s', 'notes': 'Aumento del consumo de oxígeno post-ejercicio (EPOC).'},
            {'name': 'Remo con Polea Baja', 'category': 'fuerza', 'movement_pattern': 'traccion_horizontal', 'sets': '4', 'reps': '12', 'load': 'Moderado', 'rpe': '7.5', 'rest': '45s', 'notes': 'Postura y balance del tren superior.'},
            {'name': 'Circuito Cardirrespiratorio (Air Bike / Saltos Comba)', 'category': 'velocidad', 'movement_pattern': 'metabolico', 'sets': '4', 'reps': '45s ON / 15s OFF', 'load': 'Alta intensidad', 'rpe': '8.5', 'rest': '60s entre rondas', 'notes': 'Maximización de la quema de grasa.'},
        ],
    },
}

# Ajuste (fit) del ejercicio propio dentro de su disciplina.
FIT_BY_SPORT = {sport: 5 for sport in SPORT_TEMPLATES}


def seed_templates(apps, schema_editor):
    Exercise = apps.get_model('training', 'Exercise')
    DisciplineTemplate = apps.get_model('training', 'DisciplineTemplate')
    TemplateExercise = apps.get_model('training', 'TemplateExercise')
    ExerciseDisciplineFit = apps.get_model('training', 'ExerciseDisciplineFit')

    for sport, tpl in SPORT_TEMPLATES.items():
        template = DisciplineTemplate.objects.create(
            name=tpl['name'],
            sport=sport,
            focus=tpl['focus'],
            is_default=True,
            is_active=True,
            created_by=None,
        )
        for order, ex in enumerate(tpl['exercises'], start=1):
            exercise, _ = Exercise.objects.get_or_create(
                name=ex['name'],
                defaults={
                    'category': ex['category'],
                    'movement_pattern': ex['movement_pattern'],
                    'sport_tags': [sport],
                    'description': ex['notes'],
                    'created_by': None,
                },
            )
            TemplateExercise.objects.create(
                template=template,
                exercise=exercise,
                order=order,
                sets=ex.get('sets', ''),
                reps=ex.get('reps', ''),
                rpe=ex.get('rpe', ''),
                rest=ex.get('rest', ''),
                notes=ex.get('notes', ''),
            )
            ExerciseDisciplineFit.objects.update_or_create(
                exercise=exercise,
                sport=sport,
                defaults={'fit': FIT_BY_SPORT[sport]},
            )


def unseed_templates(apps, schema_editor):
    DisciplineTemplate = apps.get_model('training', 'DisciplineTemplate')
    DisciplineTemplate.objects.filter(is_default=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('training', '0006_alter_exercise_created_by_disciplinetemplate_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]