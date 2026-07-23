from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from .managers import CustomUserManager

class CustomUser(AbstractUser):
    username = None
    email = models.EmailField(_('correo electrónico'), unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    class Meta:
        verbose_name = _('usuario')
        verbose_name_plural = _('usuarios')

    def __str__(self):
        return self.email

class TrainerProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='trainer_profile', verbose_name=_('usuario'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('perfil de entrenador')
        verbose_name_plural = _('perfiles de entrenador')

    def __str__(self):
        return f"Entrenador: {self.user.email}"

class AthleteProfile(models.Model):
    SPORT_CHOICES = [
        ('mma', 'MMA (Artes Marciales Mixtas)'),
        ('karate', 'Karate'),
        ('bjj', 'Jiu-Jitsu Brasileño (BJJ)'),
        ('crossfit', 'CrossFit'),
        ('hyrox', 'Hyrox'),
        ('weight_loss', 'Pérdida de Peso / Acondicionamiento'),
        ('otro', 'Otro'),
    ]

    EXPERIENCE_CHOICES = [
        ('principiante', 'Principiante'),
        ('intermedio', 'Intermedio'),
        ('avanzado', 'Avanzado'),
        ('elite', 'Élite / Competición'),
    ]

    GOAL_CHOICES = [
        ('fuerza_maxima', 'Fuerza Máxima'),
        ('potencia_explosiva', 'Potencia Explosiva'),
        ('resistencia_muscular', 'Resistencia Muscular'),
        ('hipertrofia', 'Hipertrofia'),
        ('perdida_grasa', 'Pérdida de Grasa / Déficit'),
        ('acondicionamiento_combate', 'Capacidad Acondicionamiento de Combate'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='athlete_profile', verbose_name=_('usuario'))
    weight = models.DecimalField(_('peso (kg)'), max_digits=5, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(_('altura (cm)'), max_digits=5, decimal_places=2, null=True, blank=True)
    fat_percentage = models.DecimalField(_('porcentaje masa grasa (%)'), max_digits=5, decimal_places=2, null=True, blank=True)
    lean_mass_percentage = models.DecimalField(_('porcentaje masa magra (%)'), max_digits=5, decimal_places=2, null=True, blank=True)
    sport = models.CharField(_('deporte principal'), max_length=50, choices=SPORT_CHOICES, default='otro')
    experience_level = models.CharField(_('nivel de experiencia'), max_length=50, choices=EXPERIENCE_CHOICES, default='intermedio')
    training_goal = models.CharField(_('objetivo principal'), max_length=50, choices=GOAL_CHOICES, default='potencia_explosiva')
    assigned_trainer = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_athletes', verbose_name=_('entrenador asignado'))
    trainer_confirmed = models.BooleanField(_('entrenador confirmado'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('perfil de deportista')
        verbose_name_plural = _('perfiles de deportista')

    def __str__(self):
        return f"Deportista: {self.user.email}"

class AthleteProgressLog(models.Model):
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name='progress_logs', verbose_name=_('deportista'))
    date = models.DateField(_('fecha'), default=timezone.now)
    weight = models.DecimalField(_('peso (kg)'), max_digits=5, decimal_places=2)
    fat_percentage = models.DecimalField(_('porcentaje masa grasa (%)'), max_digits=5, decimal_places=2, null=True, blank=True)
    lean_mass_percentage = models.DecimalField(_('porcentaje masa magra (%)'), max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = _('registro de progreso')
        verbose_name_plural = _('registros de progreso')
        ordering = ['-date']
        unique_together = ('athlete', 'date')

    def __str__(self):
        return f"{self.athlete.user.email} - {self.date}: {self.weight} kg"
