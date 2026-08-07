from django.db import models
from django.utils.translation import gettext_lazy as _
from training.analytics import is_rm_based_exercise
from users.models import TrainerProfile, AthleteProfile

class Exercise(models.Model):
    """
    Representa un ejercicio individual en el catálogo del sistema, incluyendo su categoría,
    patrón de movimiento biomecánico, etiquetas deportivas y creador.
    """

    CATEGORY_CHOICES = [
        ('fuerza', 'Fuerza'),
        ('potencia', 'Potencia'),
        ('movilidad', 'Movilidad'),
        ('velocidad', 'Velocidad'),
        ('pliometria', 'Pliometría'),
        ('tecnica', 'Técnica'),
        ('tactica', 'Táctica'),
        ('otro', 'Otro'),
    ]

    MOVEMENT_CHOICES = [
        ('empuje_horizontal', 'Empuje Horizontal (Banca, Flexiones)'),
        ('empuje_vertical', 'Empuje Vertical (Press Militar)'),
        ('traccion_horizontal', 'Tracción Horizontal (Remo)'),
        ('traccion_vertical', 'Tracción Vertical (Dominadas)'),
        ('dominante_cadera', 'Dominante de Cadera (Peso Muerto, Hip Thrust)'),
        ('dominante_rodilla', 'Dominante de Rodilla (Sentadilla, Zancadas)'),
        ('potencia_olimpica', 'Potencia Olímpica (Snatch, Clean, Jerk)'),
        ('metabolico', 'Condición Metabólica (Sled, Carrera, Ergómetro)'),
        ('isometria_agarre', 'Agarre / Tracción Específica (BJJ/MMA Grip)'),
        ('core_rotacional', 'Core / Anti-Rotación (Landmine, Paloff)'),
        ('otro', 'Otro'),
    ]

    name = models.CharField(_('nombre'), max_length=200)
    category = models.CharField(_('categoría'), max_length=50, choices=CATEGORY_CHOICES, default='otro')
    movement_pattern = models.CharField(_('patrón de movimiento'), max_length=50, choices=MOVEMENT_CHOICES, default='otro')
    sport_tags = models.JSONField(_('etiquetas de deportes'), default=list, blank=True)
    description = models.TextField(_('descripción'), blank=True)
    video_url = models.URLField(_('enlace de video'), blank=True, null=True)
    created_by = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='created_exercises', verbose_name=_('creado por'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('ejercicio')
        verbose_name_plural = _('ejercicios')

    def __str__(self):
        """Devuelve el nombre representativo del ejercicio."""
        return self.name


class ExerciseDisciplineFit(models.Model):
    """
    Encaje entre un ejercicio y una disciplina deportiva. Permite evaluar del
    1 al FIT_CHOICES qué tipo de ejercicio encaja mejor en cada deporte, de
    modo que el generador pueda ampliar las recomendaciones más allá de una
    lista cerrada de ejercicios.
    """
    FIT_CHOICES = [
        (1, _('Ajuste bajo')),
        (2, _('Ajuste medio-bajo')),
        (3, _('Ajuste medio')),
        (4, _('Ajuste alto')),
        (5, _('Ajuste máximo')),
    ]

    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='discipline_fits', verbose_name=_('ejercicio'))
    sport = models.CharField(_('deporte'), max_length=50, choices=AthleteProfile.SPORT_CHOICES)
    fit = models.PositiveSmallIntegerField(_('ajuste (1-5)'), choices=FIT_CHOICES, default=3)

    class Meta:
        verbose_name = _('encaje ejercicio-deporte')
        verbose_name_plural = _('encajes ejercicio-deporte')
        unique_together = ('exercise', 'sport')
        ordering = ['-fit', 'exercise']

    def __str__(self):
        return f"{self.exercise.name} → {self.get_sport_display()} (fit {self.fit})"


class DisciplineTemplate(models.Model):
    """
    Plantilla de plan por disciplina. El sistema provee plantillas globales
    (is_default=True, created_by=None); un entrenador puede 'copiarlas' y
    editarlas a su cuenta para tener su propia versión sin pisar a otros.
    """
    name = models.CharField(_('nombre'), max_length=200)
    sport = models.CharField(_('deporte'), max_length=50, choices=AthleteProfile.SPORT_CHOICES)
    focus = models.CharField(_('foco'), max_length=200, blank=True)
    is_default = models.BooleanField(_('plantilla del sistema'), default=False)
    is_active = models.BooleanField(_('activa'), default=True)
    created_by = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='discipline_templates', verbose_name=_('creada por'))
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copies', verbose_name=_('plantilla origen'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('plantilla por disciplina')
        verbose_name_plural = _('plantillas por disciplina')
        ordering = ['sport', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_sport_display()})"


class TemplateExercise(models.Model):
    """
    Ejercicio prescrito dentro de una plantilla por disciplina. Referencia al
    catálogo real de Exercises, de modo que un ejercicio puede reutilizarse en
    varias disciplinas y el generador puede sugerir más desde el catálogo.
    """
    template = models.ForeignKey(DisciplineTemplate, on_delete=models.CASCADE, related_name='items', verbose_name=_('plantilla'))
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='template_slots', verbose_name=_('ejercicio'))
    order = models.PositiveIntegerField(_('orden'), default=0)
    sets = models.CharField(_('series'), max_length=50, blank=True)
    reps = models.CharField(_('repeticiones'), max_length=50, blank=True)
    load = models.CharField(_('carga'), max_length=50, blank=True)
    rpe = models.CharField(_('RPE'), max_length=50, blank=True)
    rest = models.CharField(_('descanso'), max_length=50, blank=True)
    notes = models.TextField(_('indicaciones'), blank=True)

    class Meta:
        verbose_name = _('ejercicio de plantilla')
        verbose_name_plural = _('ejercicios de plantilla')
        ordering = ['template', 'order']

    def __str__(self):
        return f"{self.exercise.name} ({self.template})"


class WorkoutPlan(models.Model):
    """
    Plan de entrenamiento prescriptivo asignado por un entrenador a un deportista
    para una fecha u objetivo específico.
    """

    name = models.CharField(_('nombre del plan'), max_length=200, blank=True)
    trainer = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, related_name='created_plans', verbose_name=_('entrenador'))
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='assigned_plans', verbose_name=_('deportista'))
    sport = models.CharField(_('deporte en enfoque'), max_length=50, choices=AthleteProfile.SPORT_CHOICES, default='otro')
    target_date = models.DateField(_('fecha programada'))
    is_completed = models.BooleanField(_('completado'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('plan de entrenamiento')
        verbose_name_plural = _('planes de entrenamiento')

    def __str__(self):
        """Devuelve una cadena descriptiva con el nombre del plan, email del deportista y fecha programada."""
        return f"{self.name or 'Plan'} - {self.athlete.user.email} ({self.target_date})"


class PlannedExercise(models.Model):
    """
    Ejercicio prescrito dentro de un plan de entrenamiento concreto, especificando orden,
    series, repeticiones, carga objetivo, RPE, RIR, tempo y descanso.
    """

    workout_plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name='planned_exercises', verbose_name=_('plan de entrenamiento'))
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name='planned_in', verbose_name=_('ejercicio'))
    order = models.PositiveIntegerField(_('orden'), default=0)
    sets = models.CharField(_('series'), max_length=50, blank=True)
    reps = models.CharField(_('repeticiones'), max_length=50, blank=True)
    load = models.CharField(_('carga'), max_length=50, blank=True)
    rpe = models.CharField(_('RPE'), max_length=50, blank=True)
    rir = models.CharField(_('RIR'), max_length=50, blank=True)
    tempo = models.CharField(_('tempo'), max_length=50, blank=True)
    focus = models.CharField(_('foco'), max_length=100, blank=True)
    rest = models.CharField(_('descanso'), max_length=50, blank=True)
    notes = models.TextField(_('indicaciones'), blank=True)

    class Meta:
        verbose_name = _('ejercicio planificado')
        verbose_name_plural = _('ejercicios planificados')
        ordering = ['order']

    def __str__(self):
        """Devuelve el nombre del ejercicio y el plan de entrenamiento al que pertenece."""
        return f"{self.exercise.name} ({self.workout_plan})"


class WorkoutSession(models.Model):
    """
    Registro real de una sesión de entrenamiento completada por el deportista,
    almacenando duración, calorías, frecuencia cardíaca media, RPE global y notas.
    """

    workout_plan = models.OneToOneField(WorkoutPlan, on_delete=models.CASCADE, related_name='session', verbose_name=_('plan de entrenamiento'))
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='sessions', verbose_name=_('deportista'))
    date_completed = models.DateTimeField(_('fecha completado'), auto_now_add=True)
    started_at = models.DateTimeField(_('hora de inicio'), null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(_('duración (minutos)'), null=True, blank=True)
    calories_burned = models.PositiveIntegerField(_('calorías consumidas'), null=True, blank=True)
    avg_heart_rate = models.PositiveIntegerField(_('frecuencia cardíaca media'), null=True, blank=True)
    session_rpe = models.DecimalField(_('RPE global de la sesión (1-10)'), max_digits=3, decimal_places=1, null=True, blank=True)
    notes = models.TextField(_('notas del deportista'), blank=True)

    class Meta:
        verbose_name = _('sesión de entrenamiento')
        verbose_name_plural = _('sesiones de entrenamiento')

    def __str__(self):
        """Devuelve la identificación de la sesión vinculada a su plan de entrenamiento."""
        return f"Sesión: {self.workout_plan}"


class LoggedExercise(models.Model):
    """
    Agrupador de series ejecutadas en una sesión de entrenamiento para un ejercicio planificado.
    """

    workout_session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name='logged_exercises', verbose_name=_('sesión de entrenamiento'))
    planned_exercise = models.ForeignKey(PlannedExercise, on_delete=models.CASCADE, related_name='logs', verbose_name=_('ejercicio planificado'))
    actual_sets = models.CharField(_('series reales'), max_length=50, blank=True)
    actual_reps = models.CharField(_('repeticiones reales'), max_length=50, blank=True)
    actual_load = models.CharField(_('carga real'), max_length=50, blank=True)
    actual_rpe = models.CharField(_('RPE real'), max_length=50, blank=True)
    notes = models.TextField(_('notas'), blank=True)

    # Temporización del ejercicio en el modo en vivo
    started_at = models.DateTimeField(_('hora de inicio'), null=True, blank=True)
    finished_at = models.DateTimeField(_('hora de finalización'), null=True, blank=True)

    class Meta:
        verbose_name = _('ejercicio registrado')
        verbose_name_plural = _('ejercicios registrados')

    @property
    def is_in_progress(self):
        return self.started_at is not None and self.finished_at is None

    @property
    def is_started(self):
        return self.started_at is not None

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            return int(delta.total_seconds())
        return 0

    @property
    def is_rm_exercise(self):
        return is_rm_based_exercise(self.planned_exercise)

    @property
    def best_1rm(self):
        """Mejor 1RM estimado entre las series registradas de este ejercicio en esta sesión."""
        best = 0.0
        for s in self.sets.all():
            est = s.est_1rm
            if est and est > best:
                best = est
        return round(best, 1) if best else 0.0

    def __str__(self):
        """Devuelve una representación del ejercicio registrado."""
        return f"Log: {self.planned_exercise.exercise.name}"


class LoggedSet(models.Model):
    """
    Registro individual de una serie ejecutada, guardando repeticiones reales,
    peso (kg), RPE individual y fecha/hora de finalización.
    """

    logged_exercise = models.ForeignKey(LoggedExercise, on_delete=models.CASCADE, related_name='sets', verbose_name=_('ejercicio registrado'))
    set_number = models.PositiveIntegerField(_('número de serie'), default=1)
    reps = models.PositiveIntegerField(_('repeticiones reales'), default=0)
    weight_kg = models.DecimalField(_('peso real (kg)'), max_digits=6, decimal_places=2, default=0.0)
    rpe = models.DecimalField(_('RPE'), max_digits=3, decimal_places=1, null=True, blank=True)
    completed_at = models.DateTimeField(_('hora completada'), auto_now_add=True)

    class Meta:
        verbose_name = _('serie registrada')
        verbose_name_plural = _('series registradas')
        ordering = ['set_number']

    @property
    def est_1rm(self):
        from .analytics import estimate_1rm
        return estimate_1rm(self.weight_kg, self.reps)

    @property
    def pct_1rm(self):
        from .analytics import pct_of_1rm
        return pct_of_1rm(self.weight_kg, self.est_1rm)

    def __str__(self):
        """Devuelve la descripción del número de serie, peso, repeticiones y RPE."""
        return f"Serie {self.set_number}: {self.weight_kg}kg x {self.reps} (RPE {self.rpe})"

