from django.views.generic import TemplateView, CreateView, DetailView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

import json
from collections import defaultdict
from datetime import datetime

from users.models import AthleteProfile
from users.forms import AthleteProgressLogForm, AthleteProfileForm
from .models import WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise, LoggedSet
from .forms import WorkoutPlanForm, PlannedExerciseForm, WorkoutSessionForm
from .analytics import calculate_acwr, get_athlete_sport_metrics
from .ml_engine import SmartPlanGenerator


class TrainerDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'training/trainer_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not hasattr(request.user, 'trainer_profile'):
            return redirect('users:dashboard_router')
        request.session['active_role'] = 'trainer'
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if hasattr(self.request.user, 'trainer_profile'):
            trainer = self.request.user.trainer_profile
            athletes = AthleteProfile.objects.filter(assigned_trainer=self.request.user)

            athletes_metrics = []
            for athlete in athletes:
                metrics = get_athlete_sport_metrics(athlete)
                athletes_metrics.append({
                    'athlete': athlete,
                    'metrics': metrics
                })

            context['athletes'] = athletes
            context['athletes_metrics'] = athletes_metrics
            context['total_athletes'] = athletes.count()
            context['total_plans'] = trainer.created_plans.count()
            context['total_exercises'] = trainer.created_exercises.count()
        return context


class AthleteDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'training/athlete_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not hasattr(request.user, 'athlete_profile'):
            return redirect('users:dashboard_router')
        request.session['active_role'] = 'athlete'
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.request.user.athlete_profile

        # Stats & Sport metrics
        context['metrics'] = get_athlete_sport_metrics(profile)
        context['total_completed_workouts'] = profile.sessions.count()
        context['next_plan'] = profile.assigned_plans.filter(is_completed=False).order_by('target_date').first()
        context['trainer'] = profile.assigned_trainer

        # Form
        context['log_form'] = AthleteProgressLogForm()

        # Chart Data preparation
        logs = profile.progress_logs.all().order_by('date')
        sessions = profile.sessions.all().order_by('date_completed')

        date_data = defaultdict(lambda: {'weight': None, 'fat': None, 'lean': None, 'duration': 0, 'calories': 0})

        for log in logs:
            d_str = log.date.strftime('%Y-%m-%d')
            date_data[d_str]['weight'] = float(log.weight)
            if log.fat_percentage is not None:
                date_data[d_str]['fat'] = float(log.fat_percentage)
            if log.lean_mass_percentage is not None:
                date_data[d_str]['lean'] = float(log.lean_mass_percentage)

        for session in sessions:
            d_str = session.date_completed.date().strftime('%Y-%m-%d')
            date_data[d_str]['duration'] += session.duration_minutes or 0
            date_data[d_str]['calories'] += session.calories_burned or 0

        sorted_dates = sorted(date_data.keys())

        display_labels = []
        months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        for d_str in sorted_dates:
            dt = datetime.strptime(d_str, '%Y-%m-%d')
            display_labels.append(f"{dt.day} {months[dt.month-1]}")

        weights = [date_data[d]['weight'] for d in sorted_dates]
        fats = [date_data[d]['fat'] for d in sorted_dates]
        leans = [date_data[d]['lean'] for d in sorted_dates]
        durations = [date_data[d]['duration'] for d in sorted_dates]
        calories = [date_data[d]['calories'] for d in sorted_dates]

        context['chart_labels'] = json.dumps(display_labels)
        context['chart_weights'] = json.dumps(weights)
        context['chart_fats'] = json.dumps(fats)
        context['chart_leans'] = json.dumps(leans)
        context['chart_durations'] = json.dumps(durations)
        context['chart_calories'] = json.dumps(calories)

        # Pass profile and recent logs for display
        context['profile'] = profile
        context['recent_logs'] = logs.order_by('-date')[:5]

        return context


class WorkoutPlanCreateView(LoginRequiredMixin, CreateView):
    model = WorkoutPlan
    form_class = WorkoutPlanForm
    template_name = 'training/workout_plan_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self.request.user, 'trainer_profile'):
            kwargs['trainer'] = self.request.user.trainer_profile
        return kwargs

    def form_valid(self, form):
        form.instance.trainer = self.request.user.trainer_profile
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('training:plan_detail', kwargs={'pk': self.object.pk})


class WorkoutPlanDetailView(LoginRequiredMixin, DetailView):
    model = WorkoutPlan
    template_name = 'training/workout_plan_detail.html'
    context_object_name = 'plan'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exercise_form'] = PlannedExerciseForm()

        if hasattr(self.request.user, 'athlete_profile'):
            context['session_form'] = WorkoutSessionForm()

        if self.object.is_completed:
            context['workout_session'] = getattr(self.object, 'session', None)

        return context


class LiveWorkoutView(LoginRequiredMixin, DetailView):
    model = WorkoutPlan
    template_name = 'training/live_workout.html'
    context_object_name = 'plan'

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        # Verificar permisos del deportista
        if hasattr(request.user, 'athlete_profile') and obj.athlete != request.user.athlete_profile:
            messages.error(request, "No tienes acceso a este entrenamiento.")
            return redirect('training:athlete_dashboard')
        return super().dispatch(request, *args, **kwargs)


@login_required
@require_POST
def log_set_htmx(request, planned_id):
    """
    Endpoint HTMX para registrar una serie individual en el modo de entrenamiento activo.
    """
    planned_exercise = get_object_or_404(PlannedExercise, pk=planned_id)
    plan = planned_exercise.workout_plan

    # Validar permisos
    if not hasattr(request.user, 'athlete_profile') or plan.athlete != request.user.athlete_profile:
        return HttpResponse("No autorizado", status=403)

    weight_kg = float(request.POST.get('weight_kg', 0.0))
    reps = int(request.POST.get('reps', 0))
    rpe = float(request.POST.get('rpe', 8.0))

    # Obtener o crear WorkoutSession
    session, _ = WorkoutSession.objects.get_or_create(
        workout_plan=plan,
        athlete=plan.athlete
    )

    # Obtener o crear LoggedExercise
    logged_ex, _ = LoggedExercise.objects.get_or_create(
        workout_session=session,
        planned_exercise=planned_exercise
    )

    # Crear LoggedSet
    current_set_count = logged_ex.sets.count() + 1
    logged_set = LoggedSet.objects.create(
        logged_exercise=logged_ex,
        set_number=current_set_count,
        reps=reps,
        weight_kg=weight_kg,
        rpe=rpe
    )

    # Renderizar fragmento de HTML para la nueva serie
    html = f"""
    <div class="flex justify-between items-center bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 animate-fade-in">
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded-md font-bold">Serie {logged_set.set_number}</span>
            <span>{logged_set.weight_kg} kg × {logged_set.reps} reps</span>
        </div>
        <div class="flex items-center gap-2 text-slate-500">
            <span>RPE {logged_set.rpe}</span>
            <span class="text-emerald-500 font-bold">✓</span>
        </div>
    </div>
    """
    return HttpResponse(html)


@login_required
@require_POST
def generate_smart_plan(request, athlete_id):
    """
    Endpoint para generar un plan de entrenamiento optimizado por deporte con ML Copilot.
    """
    if not hasattr(request.user, 'trainer_profile'):
        messages.error(request, "Solo los entrenadores pueden generar planes asistidos.")
        return redirect('users:dashboard_router')

    athlete = get_object_or_404(AthleteProfile, pk=athlete_id, assigned_trainer=request.user)

    plan = SmartPlanGenerator.generate_plan_for_athlete(
        trainer_profile=request.user.trainer_profile,
        athlete_profile=athlete
    )

    messages.success(request, f"✨ ¡Plan '{plan.name}' generado con éxito usando ML Copilot para {athlete.get_sport_display()}!")
    return redirect('training:plan_detail', pk=plan.pk)


@login_required
@require_POST
def complete_workout(request, plan_id):
    """
    Registra el entrenamiento como completado y guarda la sesión física asociada.
    """
    plan = get_object_or_404(WorkoutPlan, pk=plan_id)

    if not hasattr(request.user, 'athlete_profile') or plan.athlete != request.user.athlete_profile:
        messages.error(request, "No tienes permiso para completar este entrenamiento.")
        return redirect('training:athlete_dashboard')

    form = WorkoutSessionForm(request.POST)
    session_rpe = request.POST.get('session_rpe')

    if form.is_valid():
        session, _ = WorkoutSession.objects.get_or_create(
            workout_plan=plan,
            athlete=request.user.athlete_profile
        )
        session.duration_minutes = form.cleaned_data.get('duration_minutes')
        session.calories_burned = form.cleaned_data.get('calories_burned')
        session.avg_heart_rate = form.cleaned_data.get('avg_heart_rate')
        if session_rpe:
            session.session_rpe = float(session_rpe)
        session.notes = form.cleaned_data.get('notes')
        session.save()

        # Marcar plan como completado
        plan.is_completed = True
        plan.save()

        messages.success(request, f"¡Entrenamiento '{plan.name}' completado con éxito! Gran trabajo.")
    else:
        messages.error(request, "Error al registrar la sesión de entrenamiento. Por favor verifica los datos.")

    return redirect('training:athlete_dashboard')


def add_planned_exercise(request, plan_id):
    """
    Vista diseñada para manejar peticiones POST de HTMX para añadir ejercicios a un plan.
    """
    if request.method == 'POST':
        plan = get_object_or_404(WorkoutPlan, pk=plan_id)
        form = PlannedExerciseForm(request.POST)
        if form.is_valid():
            planned_exercise = form.save(commit=False)
            planned_exercise.workout_plan = plan
            planned_exercise.save()
            return render(request, 'training/partials/exercise_row.html', {'exercise': planned_exercise})
        else:
            return HttpResponse("Error en formulario", status=400)
    return HttpResponse(status=405)


class AthleteDetailView(LoginRequiredMixin, DetailView):
    model = AthleteProfile
    template_name = 'training/athlete_detail.html'
    context_object_name = 'athlete'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plans'] = self.object.assigned_plans.all().order_by('-target_date')
        context['metrics'] = get_athlete_sport_metrics(self.object)
        return context


class TrainerAthleteProfileUpdateView(LoginRequiredMixin, UpdateView):
    """
    Permite al entrenador editar el perfil deportivo y datos físicos de cualquiera de sus deportistas asignados.
    """
    model = AthleteProfile
    form_class = AthleteProfileForm
    template_name = 'users/athlete_profile_form.html'

    def get_queryset(self):
        if hasattr(self.request.user, 'trainer_profile'):
            return AthleteProfile.objects.filter(assigned_trainer=self.request.user)
        return AthleteProfile.objects.none()

    def get_success_url(self):
        messages.success(self.request, f"Perfil deportivo de {self.object.user.first_name or self.object.user.email} actualizado con éxito.")
        return reverse('training:athlete_detail', kwargs={'pk': self.object.pk})

