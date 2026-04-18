from django.db import models
from django.utils.translation import gettext_lazy as _
from users.models import TrainerProfile, AthleteProfile

class Exercise(models.Model):
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

    name = models.CharField(_('nombre'), max_length=200)
    category = models.CharField(_('categoría'), max_length=50, choices=CATEGORY_CHOICES, default='otro')
    description = models.TextField(_('descripción'), blank=True)
    video_url = models.URLField(_('enlace de video'), blank=True)
    created_by = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, related_name='created_exercises', verbose_name=_('creado por'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('ejercicio')
        verbose_name_plural = _('ejercicios')

    def __str__(self):
        return self.name

class WorkoutPlan(models.Model):
    name = models.CharField(_('nombre del plan'), max_length=200, blank=True)
    trainer = models.ForeignKey(TrainerProfile, on_delete=models.CASCADE, related_name='created_plans', verbose_name=_('entrenador'))
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='assigned_plans', verbose_name=_('deportista'))
    target_date = models.DateField(_('fecha programada'))
    is_completed = models.BooleanField(_('completado'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('plan de entrenamiento')
        verbose_name_plural = _('planes de entrenamiento')

    def __str__(self):
        return f"{self.name or 'Plan'} - {self.athlete.user.email} ({self.target_date})"

class PlannedExercise(models.Model):
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
        return f"{self.exercise.name} ({self.workout_plan})"

class WorkoutSession(models.Model):
    workout_plan = models.OneToOneField(WorkoutPlan, on_delete=models.CASCADE, related_name='session', verbose_name=_('plan de entrenamiento'))
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='sessions', verbose_name=_('deportista'))
    date_completed = models.DateTimeField(_('fecha completado'), auto_now_add=True)
    duration_minutes = models.PositiveIntegerField(_('duración (minutos)'), null=True, blank=True)
    calories_burned = models.PositiveIntegerField(_('calorías consumidas'), null=True, blank=True)
    avg_heart_rate = models.PositiveIntegerField(_('frecuencia cardíaca media'), null=True, blank=True)
    notes = models.TextField(_('notas del deportista'), blank=True)

    class Meta:
        verbose_name = _('sesión de entrenamiento')
        verbose_name_plural = _('sesiones de entrenamiento')

    def __str__(self):
        return f"Sesión: {self.workout_plan}"

class LoggedExercise(models.Model):
    workout_session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name='logged_exercises', verbose_name=_('sesión de entrenamiento'))
    planned_exercise = models.ForeignKey(PlannedExercise, on_delete=models.CASCADE, related_name='logs', verbose_name=_('ejercicio planificado'))
    actual_sets = models.CharField(_('series reales'), max_length=50, blank=True)
    actual_reps = models.CharField(_('repeticiones reales'), max_length=50, blank=True)
    actual_load = models.CharField(_('carga real'), max_length=50, blank=True)
    actual_rpe = models.CharField(_('RPE real'), max_length=50, blank=True)
    notes = models.TextField(_('notas'), blank=True)

    class Meta:
        verbose_name = _('ejercicio registrado')
        verbose_name_plural = _('ejercicios registrados')

    def __str__(self):
        return f"Log: {self.planned_exercise.exercise.name}"
