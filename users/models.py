from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
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
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='athlete_profile', verbose_name=_('usuario'))
    weight = models.DecimalField(_('peso (kg)'), max_digits=5, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(_('altura (cm)'), max_digits=5, decimal_places=2, null=True, blank=True)
    assigned_trainer = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_athletes', verbose_name=_('entrenador asignado'))
    trainer_confirmed = models.BooleanField(_('entrenador confirmado'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('perfil de deportista')
        verbose_name_plural = _('perfiles de deportista')

    def __str__(self):
        return f"Deportista: {self.user.email}"
