from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import UpdateView, TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone

from training.views import build_athlete_context, build_trainer_context

from .models import CustomUser, TrainerProfile, AthleteProfile, AthleteProgressLog
from .forms import CustomAuthenticationForm, AthleteProfileForm, AthleteProgressLogForm, TrainerUserForm


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

    def post(self, request, *args, **kwargs):
        return create_trainer_profile(request)


class BecomeAthleteView(LoginRequiredMixin, TemplateView):
    """
    Confirmación para que un entrenador active su perfil de deportista
    y gestione también sus entrenamientos personales.
    """
    template_name = 'users/become_athlete.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_athlete:
            return redirect(f"{reverse_lazy('home')}?tab=athlete")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return create_athlete_profile(request)


@login_required
@require_POST
def create_athlete_profile(request):
    """Activa el perfil de deportista del usuario actual."""
    if not request.user.is_athlete:
        AthleteProfile.objects.create(user=request.user)
        messages.success(request, "Perfil de deportista activado. Completa tus datos físicos para empezar.")
    return redirect('users:profile_edit')


@login_required
@require_POST
def create_trainer_profile(request):
    """Activa el perfil de entrenador del usuario actual."""
    if not request.user.is_trainer:
        TrainerProfile.objects.create(user=request.user)
        messages.success(request, "Perfil de entrenador activado. Ya puedes gestionar deportistas, planes y ejercicios.")
    return redirect(f"{reverse_lazy('home')}?tab=trainer")


@login_required
@require_POST
def create_dual_profile(request):
    """Activa simultáneamente el perfil de deportista y de entrenador (perfil dual completo)."""
    if not request.user.is_trainer:
        TrainerProfile.objects.create(user=request.user)
    if not request.user.is_athlete:
        AthleteProfile.objects.create(user=request.user)
    messages.success(
        request,
        "¡Perfil Dual activado! Ahora tienes acceso completo como Entrenador y como Deportista."
    )
    return redirect('home')


@login_required
@require_POST
def remove_trainer_profile(request):
    """Permite a un usuario con perfil dual desactivar su faceta de entrenador."""
    if not request.user.is_trainer:
        messages.info(request, "No dispones de perfil de entrenador activo.")
        return redirect('users:profile_edit')
    if not request.user.is_athlete:
        messages.error(request, "No puedes desactivar el rol de entrenador sin tener activo el de deportista.")
        return redirect('users:profile_edit')

    request.user.trainer_profile.delete()
    messages.success(request, "Perfil de entrenador desactivado. Tu cuenta ahora opera exclusivamente en modo Deportista.")
    return redirect(f"{reverse_lazy('home')}?tab=athlete")


@login_required
@require_POST
def remove_athlete_profile(request):
    """Permite a un usuario con perfil dual desactivar su faceta de deportista."""
    if not request.user.is_athlete:
        messages.info(request, "No dispones de perfil de deportista activo.")
        return redirect('users:profile_edit')
    if not request.user.is_trainer:
        messages.error(request, "No puedes desactivar el rol de deportista sin tener activo el de entrenador.")
        return redirect('users:profile_edit')

    request.user.athlete_profile.delete()
    messages.success(request, "Perfil de deportista desactivado. Tu cuenta ahora opera exclusivamente en modo Entrenador.")
    return redirect(f"{reverse_lazy('home')}?tab=trainer")


class ProfileEditView(LoginRequiredMixin, View):
    """
    Vista unificada de gestión de perfil y roles. Permite actualizar datos personales,
    composición física (si dispone de perfil deportista) y activar/desactivar roles.
    """
    template_name = 'users/athlete_profile_form.html'

    def get(self, request, *args, **kwargs):
        user = request.user
        if user.is_athlete:
            form = AthleteProfileForm(instance=user.athlete_profile)
        else:
            form = TrainerUserForm(instance=user)
        return render(request, self.template_name, {
            'form': form,
            'is_athlete_profile': user.is_athlete,
        })

    def post(self, request, *args, **kwargs):
        user = request.user
        if user.is_athlete:
            form = AthleteProfileForm(request.POST, instance=user.athlete_profile)
            if form.is_valid():
                form.save()
                profile = user.athlete_profile
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
                messages.success(request, "Perfil y datos físicos actualizados con éxito.")
                return redirect('users:profile_edit')
        else:
            form = TrainerUserForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                messages.success(request, "Datos personales actualizados con éxito.")
                return redirect('users:profile_edit')

        return render(request, self.template_name, {
            'form': form,
            'is_athlete_profile': user.is_athlete,
        })


# Alias de retrocompatibilidad
AthleteProfileUpdateView = ProfileEditView


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
