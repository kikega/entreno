from django.views.generic import TemplateView, CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse

from users.models import AthleteProfile
from .models import WorkoutPlan, PlannedExercise
from .forms import WorkoutPlanForm, PlannedExerciseForm

class TrainerDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'training/trainer_dashboard.html'
    
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
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
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
