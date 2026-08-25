from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('onboarding/', views.OnboardingView.as_view(), name='onboarding'),
    path('become-trainer/', views.BecomeTrainerView.as_view(), name='become_trainer'),
    path('profiles/athlete/create/', views.create_athlete_profile, name='create_athlete_profile'),
    path('profiles/trainer/create/', views.create_trainer_profile, name='create_trainer_profile'),
    path('profile/edit/', views.AthleteProfileUpdateView.as_view(), name='profile_edit'),
    path('progress/log/', views.log_progress, name='log_progress'),

    # Password Reset URLs
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset_form.html',
        email_template_name='users/password_reset_email.html',
        success_url='/users/password_reset/done/'
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html',
        success_url='/users/reset/done/'
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_complete.html'
    ), name='password_reset_complete'),
]
