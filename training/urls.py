from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required

app_name = 'training'

# Por ahora usaremos TemplateViews envueltas en login_required
# Más adelante crearemos las vistas reales en views.py
urlpatterns = [
    path('trainer/', login_required(TemplateView.as_view(template_name='training/trainer_dashboard.html')), name='trainer_dashboard'),
    path('athlete/', login_required(TemplateView.as_view(template_name='training/athlete_dashboard.html')), name='athlete_dashboard'),
]
