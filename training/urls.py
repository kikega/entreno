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
    path('plan/<int:pk>/live/', views.LiveWorkoutView.as_view(), name='live_workout'),
    path('plan/<int:plan_id>/add-exercise/', views.add_planned_exercise, name='add_exercise'),
    path('plan/<int:plan_id>/complete/', views.complete_workout, name='complete_workout'),
    
    # HTMX Set Logging & Smart Plan Generator
    path('planned/<int:planned_id>/log-set/', views.log_set_htmx, name='log_set_htmx'),
    path('athlete/<int:athlete_id>/generate-smart-plan/', views.generate_smart_plan, name='generate_smart_plan'),
    
    # Athlete Profile
    path('athlete/<int:pk>/', views.AthleteDetailView.as_view(), name='athlete_detail'),
    path('athlete/<int:pk>/edit/', views.TrainerAthleteProfileUpdateView.as_view(), name='trainer_athlete_edit'),
]
