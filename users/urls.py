from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('onboarding/', views.OnboardingView.as_view(), name='onboarding'),
    path('become-trainer/', views.BecomeTrainerView.as_view(), name='become_trainer'),
    path('become-athlete/', views.BecomeAthleteView.as_view(), name='become_athlete'),
    path('profiles/athlete/create/', views.create_athlete_profile, name='create_athlete_profile'),
    path('profiles/trainer/create/', views.create_trainer_profile, name='create_trainer_profile'),
    path('profiles/dual/create/', views.create_dual_profile, name='create_dual_profile'),
    path('profiles/athlete/remove/', views.remove_athlete_profile, name='remove_athlete_profile'),
    path('profiles/trainer/remove/', views.remove_trainer_profile, name='remove_trainer_profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('password_change/', views.CustomPasswordChangeView.as_view(), name='password_change'),
    path('password_change/done/', views.CustomPasswordChangeDoneView.as_view(), name='password_change_done'),
    path('progress/log/', views.log_progress, name='log_progress'),

    # Password Reset URLs
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset_form.html',
        email_template_name='users/password_reset_email.html',
        success_url=reverse_lazy('users:password_reset_done')
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html',
        success_url=reverse_lazy('users:password_reset_complete')
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_complete.html'
    ), name='password_reset_complete'),
]
