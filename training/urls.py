from django.urls import path
from . import views

app_name = 'training'

urlpatterns = [
    # Dashboards (compatibilidad: redirigen al espacio unificado con su pestaña)
    path('trainer/', views.dashboard_redirect, {'tab': 'trainer'}, name='trainer_dashboard'),
    path('athlete/', views.dashboard_redirect, {'tab': 'athlete'}, name='athlete_dashboard'),
    
    # Workout Plans
    path('plan/new/', views.WorkoutPlanCreateView.as_view(), name='plan_create'),
    path('plan/<int:pk>/', views.WorkoutPlanDetailView.as_view(), name='plan_detail'),
    path('plan/<int:pk>/live/', views.LiveWorkoutView.as_view(), name='live_workout'),
    path('plan/<int:plan_id>/add-exercise/', views.add_planned_exercise, name='add_exercise'),
    path('plan/<int:plan_id>/complete/', views.complete_workout, name='complete_workout'),
    
    # HTMX Set Logging, Start/Finish Exercise & Smart Plan Generator
    path('planned/<int:planned_id>/log-set/', views.log_set_htmx, name='log_set_htmx'),
    path('planned/<int:planned_id>/start/', views.start_exercise, name='start_exercise'),
    path('planned/<int:planned_id>/finish/', views.finish_exercise, name='finish_exercise'),
    path('athlete/<int:athlete_id>/generate-smart-plan/', views.generate_smart_plan, name='generate_smart_plan'),
    
    # Athlete Profile & Sistema AM Triage
    path('triage/me/', views.AthleteMMATriageView.as_view(), name='athlete_mma_triage'),
    path('active-block/', views.AthleteActiveBlockView.as_view(), name='athlete_active_block'),
    path('athlete/<int:pk>/', views.AthleteDetailView.as_view(), name='athlete_detail'),
    path('athlete/<int:pk>/triage/', views.TrainerMMATriageReviewView.as_view(), name='trainer_mma_triage'),
    path('athlete/<int:athlete_id>/macrocycle/init/', views.macrocycle_init, name='macrocycle_init'),
    path('macrocycle/<int:pk>/', views.TrainerMacrocycleControlView.as_view(), name='macrocycle_control'),
    path('block/<int:block_id>/toggle-publish/', views.toggle_block_publication, name='block_toggle_publish'),
    path('block/<int:block_id>/update/', views.update_macrocycle_block, name='block_update'),
    path('block/<int:block_id>/prescribe-exercise/', views.prescribe_block_exercise, name='block_prescribe_exercise'),
    path('athlete/<int:pk>/edit/', views.TrainerAthleteProfileUpdateView.as_view(), name='trainer_athlete_edit'),
    path('athlete/<int:pk>/delete/', views.TrainerAthleteDeleteView.as_view(), name='trainer_athlete_delete'),
    path('notifications/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),

    # Exercise Catalog (CRUD entrenador)
    path('exercises/', views.ExerciseListView.as_view(), name='exercise_list'),
    path('exercises/new/', views.ExerciseCreateView.as_view(), name='exercise_create'),
    path('exercises/<int:pk>/edit/', views.ExerciseUpdateView.as_view(), name='exercise_edit'),
    path('exercises/<int:pk>/delete/', views.ExerciseDeleteView.as_view(), name='exercise_delete'),
    path('exercises/<int:pk>/detail-modal/', views.exercise_detail_modal_view, name='exercise_detail_modal'),
]

