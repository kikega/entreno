from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import UpdateView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone

from training.models import TrainerProfile
from training.views import build_athlete_context, build_trainer_context

from .models import AthleteProfile, AthleteProgressLog
from .forms import CustomAuthenticationForm, AthleteProfileForm, AthleteProgressLogForm


class CustomLoginView(LoginView):
    """
    Vista personalizada de inicio de sesión utilizando la dirección de correo electrónico como credencial.
    """
    template_name = 'users/login.html'
    authentication_form = CustomAuthenticationForm
    redirect_authenticated_user = True


class CustomLogoutView(LogoutView):
    """
    Vista personalizada para cerrar la sesión activa del usuario y redirigirlo al inicio de sesión.
    """
    next_page = 'users:login'


class HomeView(LoginRequiredMixin, TemplateView):
    """
    Espacio de trabajo unificado. Sustituye al antiguo selector de rol:
    el usuario accede a una única página con pestañas de contexto
    (su entrenamiento personal y la gestión de sus deportistas) según
    las capacidades de su cuenta, sin cambiar de modo global.
    """
    template_name = 'home.html'

    def dispatch(self, request, *args, **kwargs):
        """Deriva a onboarding a los usuarios que aún no tienen ningún perfil."""
        if request.user.is_authenticated and not (request.user.is_athlete or request.user.is_trainer):
            return redirect('users:onboarding')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Carga los datos del contexto (pestaña) solicitado y válido para el usuario."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        requested_tab = self.request.GET.get('tab')

        if requested_tab == 'trainer' and user.is_trainer:
            active_tab = 'trainer'
        elif requested_tab == 'athlete' and user.is_athlete:
            active_tab = 'athlete'
        else:
            # Por defecto priorizamos el contexto personal si existe
            active_tab = 'athlete' if user.is_athlete else 'trainer'

        context['active_tab'] = active_tab
        if active_tab == 'athlete':
            context.update(build_athlete_context(user))
        else:
            context.update(build_trainer_context(user))
        return context


class OnboardingView(LoginRequiredMixin, TemplateView):
    """
    Pantalla de alta para usuarios sin ningún perfil: permite activar
    el perfil de deportista o de entrenador por sí mismos.
    """
    template_name = 'users/onboarding.html'

    def dispatch(self, request, *args, **kwargs):
        """Los usuarios que ya disponen de algún perfil van directo al espacio de trabajo."""
        if request.user.is_authenticated and (request.user.is_athlete or request.user.is_trainer):
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)


class BecomeTrainerView(LoginRequiredMixin, TemplateView):
    """
    Confirmación para que cualquier usuario (por ejemplo, un deportista que
    también entrena a otros) active su perfil de entrenador.
    """
    template_name = 'users/become_trainer.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_trainer:
            return redirect(f"{reverse_lazy('home')}?tab=trainer")
        return super().dispatch(request, *args, **kwargs)


@login_required
@require_POST
def create_athlete_profile(request):
    """Activa el perfil de deportista del usuario actual."""
    if not request.user.is_athlete:
        AthleteProfile.objects.create(user=request.user)
        messages.success(request, "Perfil de deportista creado. Completa tus datos físicos para empezar.")
    return redirect('users:profile_edit')


@login_required
@require_POST
def create_trainer_profile(request):
    """Activa el perfil de entrenador del usuario actual."""
    if not request.user.is_trainer:
        TrainerProfile.objects.create(user=request.user)
        messages.success(request, "Perfil de entrenador activado. Ya puedes gestionar deportistas, planes y ejercicios.")
    return redirect(f"{reverse_lazy('home')}?tab=trainer")


class AthleteProfileUpdateView(LoginRequiredMixin, UpdateView):
    """
    Vista para que los deportistas editen su perfil personal, datos antropométricos y objetivos de entrenamiento.
    """
    model = AthleteProfile
    form_class = AthleteProfileForm
    template_name = 'users/athlete_profile_form.html'
    success_url = reverse_lazy('home')

    def get_object(self, queryset=None):
        """Retorna el perfil de atleta perteneciente al usuario actualmente autenticado."""
        return self.request.user.athlete_profile

    def form_valid(self, form):
        """Guarda los cambios del perfil y genera o actualiza un registro de progreso para el día de hoy."""
        response = super().form_valid(form)
        profile = self.object
        today = timezone.now().date()
        if profile.weight is not None:
            AthleteProgressLog.objects.update_or_create(
                athlete=profile,
                date=today,
                defaults={
                    'weight': profile.weight,
                    'fat_percentage': profile.fat_percentage,
                    'lean_mass_percentage': profile.lean_mass_percentage
                }
            )
        messages.success(self.request, "Perfil y datos físicos actualizados con éxito.")
        return response


@login_required
@require_POST
def log_progress(request):
    """
    Endpoint para registrar el progreso antropométrico diario de un deportista (peso, % grasa, % masa magra).
    Soporta peticiones estándar y fragmentos HTMX.
    """
    profile = get_object_or_404(AthleteProfile, user=request.user)

    form = AthleteProgressLogForm(request.POST)
    if form.is_valid():
        log = form.save(commit=False)
        log.athlete = profile

        # update_or_create to avoid duplicate for same date
        log_obj, created = AthleteProgressLog.objects.update_or_create(
            athlete=profile,
            date=log.date,
            defaults={
                'weight': log.weight,
                'fat_percentage': log.fat_percentage,
                'lean_mass_percentage': log.lean_mass_percentage
            }
        )

        # Also update current profile stats if it's the latest date
        latest_log = AthleteProgressLog.objects.filter(athlete=profile).order_by('-date').first()
        if latest_log and latest_log.date == log_obj.date:
            profile.weight = log_obj.weight
            profile.fat_percentage = log_obj.fat_percentage
            profile.lean_mass_percentage = log_obj.lean_mass_percentage
            profile.save()

        if request.headers.get('HX-Request'):
            return HttpResponse(status=204, headers={'HX-Refresh': 'true'})

        messages.success(request, "Medición registrada con éxito.")
        return redirect(f"{reverse_lazy('home')}?tab=athlete")
    else:
        if request.headers.get('HX-Request'):
            return HttpResponse("Error en los datos del formulario", status=400)
        messages.error(request, "Error al registrar la medición.")
        return redirect(f"{reverse_lazy('home')}?tab=athlete")
