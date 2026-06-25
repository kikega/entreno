from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone

from .models import AthleteProfile, AthleteProgressLog
from .forms import CustomAuthenticationForm, AthleteProfileForm, AthleteProgressLogForm

class CustomLoginView(LoginView):
    template_name = 'users/login.html'
    authentication_form = CustomAuthenticationForm
    redirect_authenticated_user = True

class CustomLogoutView(LogoutView):
    next_page = 'users:login'

@login_required
def dashboard_router(request):
    """
    Redirige al usuario al dashboard que le corresponde.
    Si tiene ambos roles, guarda la selección en la sesión.
    """
    user = request.user
    
    is_trainer = hasattr(user, 'trainer_profile')
    is_athlete = hasattr(user, 'athlete_profile')

    # Si se solicita explícitamente cambiar de rol
    if request.GET.get('switch') == 'true':
        if 'active_role' in request.session:
            del request.session['active_role']
        if is_trainer and is_athlete:
            return render(request, 'users/role_selector.html')

    # Comprobamos si ya hay un rol activo en la sesión
    active_role = request.session.get('active_role')
    if active_role == 'trainer' and is_trainer:
        return redirect('training:trainer_dashboard')
    elif active_role == 'athlete' and is_athlete:
        return redirect('training:athlete_dashboard')

    # Si no hay rol activo, decidimos según los perfiles disponibles
    if is_trainer and is_athlete:
        return render(request, 'users/role_selector.html')
    elif is_trainer:
        request.session['active_role'] = 'trainer'
        return redirect('training:trainer_dashboard')
    elif is_athlete:
        request.session['active_role'] = 'athlete'
        return redirect('training:athlete_dashboard')
    else:
        # Usuario sin rol asignado
        return render(request, 'users/no_role.html')

class AthleteProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = AthleteProfile
    form_class = AthleteProfileForm
    template_name = 'users/athlete_profile_form.html'
    success_url = reverse_lazy('training:athlete_dashboard')

    def get_object(self, queryset=None):
        return self.request.user.athlete_profile

    def form_valid(self, form):
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
        return redirect('training:athlete_dashboard')
    else:
        if request.headers.get('HX-Request'):
            return HttpResponse("Error en los datos del formulario", status=400)
        messages.error(request, "Error al registrar la medición.")
        return redirect('training:athlete_dashboard')
