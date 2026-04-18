from django.urls import path
from . import views

app_name = 'training'

urlpatterns = [
    # Dashboards
    path('trainer/', views.TrainerDashboardView.as_view(), name='trainer_dashboard'),
    path('athlete/', views.AthleteDashboardView.as_view(), name='athlete_dashboard'),
    
    # Workout Plans
    path('plan/new/', views.WorkoutPlanCreateView.as_view(), name='plan_create'),
    path('plan/<int:pk>/', views.WorkoutPlanDetailView.as_view(), name='plan_detail'),
    path('plan/<int:plan_id>/add-exercise/', views.add_planned_exercise, name='add_exercise'),
    
    # Athlete Profile
    path('athlete/<int:pk>/', views.AthleteDetailView.as_view(), name='athlete_detail'),
]
