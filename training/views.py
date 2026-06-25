from django.views.generic import TemplateView, CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse

import json
from collections import defaultdict
from datetime import datetime

from users.models import AthleteProfile
from users.forms import AthleteProgressLogForm
from .models import WorkoutPlan, PlannedExercise
from .forms import WorkoutPlanForm, PlannedExerciseForm

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
            
            context['athletes'] = athletes
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
        
        # Stats
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
        # Ensure the user is either the trainer or the athlete
        return context

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
            # Retorna solo el fragmento HTML de la nueva fila (o un renderizado parcial)
            return render(request, 'training/partials/exercise_row.html', {'exercise': planned_exercise})
        else:
            # Podríamos manejar el error enviando el formulario de nuevo con HTMX
            return HttpResponse("Error en formulario", status=400)
    return HttpResponse(status=405)

class AthleteDetailView(LoginRequiredMixin, DetailView):
    model = AthleteProfile
    template_name = 'training/athlete_detail.html'
    context_object_name = 'athlete'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Mostrar los planes de este deportista
        context['plans'] = self.object.assigned_plans.all().order_by('-target_date')
        return context
