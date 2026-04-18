from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from .forms import CustomAuthenticationForm

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
    Si tiene ambos roles, por ahora lo envia al de entrenador,
    o podriamos renderizar una vista de seleccion.
    """
    user = request.user
    
    is_trainer = hasattr(user, 'trainer_profile')
    is_athlete = hasattr(user, 'athlete_profile')

    if is_trainer and is_athlete:
        # Si tiene ambos, mostramos selector o enviamos a uno por defecto
        # Para el prototipo, enviamos a un selector sencillo
        return render(request, 'users/role_selector.html')
    elif is_trainer:
        return redirect('training:trainer_dashboard')
    elif is_athlete:
        return redirect('training:athlete_dashboard')
    else:
        # Usuario sin rol asignado
        return render(request, 'users/no_role.html')
