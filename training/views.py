from django.views.generic import TemplateView, CreateView, DetailView, UpdateView, DeleteView, ListView
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

from django.db.models import Q
from django.utils import timezone

from users.models import AthleteProfile
from users.forms import AthleteProgressLogForm, AthleteProfileForm
from .models import WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise, LoggedSet, Exercise
from .forms import WorkoutPlanForm, PlannedExerciseForm, WorkoutSessionForm, ExerciseForm
from .analytics import (
    calculate_acwr,
    get_athlete_sport_metrics,
    exercise_1rm_evolution,
    is_rm_based_exercise,
    estimate_1rm,
    pct_of_1rm,
)
from .ml_engine import SmartPlanGenerator


class TrainerRequiredMixin(LoginRequiredMixin):
    """Restringe el acceso a usuarios con perfil de entrenador."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not hasattr(request.user, 'trainer_profile'):
            messages.error(request, "Acción permitida solo para entrenadores.")
            return redirect('users:dashboard_router')
        request.session['active_role'] = 'trainer'
        return super().dispatch(request, *args, **kwargs)


class TrainerDashboardView(LoginRequiredMixin, TemplateView):
    """
    Vista de panel principal para entrenadores. Muestra la lista de deportistas asignados,
    sus métricas de carga/rendimiento (ACWR, volúmenes) y resumen general de la actividad.
    """
    template_name = 'training/trainer_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        """Valida que el usuario tenga perfil de entrenador y establece el rol activo en la sesión."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not hasattr(request.user, 'trainer_profile'):
            return redirect('users:dashboard_router')
        request.session['active_role'] = 'trainer'
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Construye el contexto con los datos del entrenador, sus atletas asignados y métricas calculadas."""
        context = super().get_context_data(**kwargs)
        if hasattr(self.request.user, 'trainer_profile'):
            trainer = self.request.user.trainer_profile
            athletes = AthleteProfile.objects.filter(
                assigned_trainer=self.request.user
            ).select_related('user')

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
    """
    Vista de panel principal para deportistas. Muestra sus métricas personales,
    próximos planes asignados, gráficos de peso/composición e historial reciente.
    """
    template_name = 'training/athlete_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        """Valida que el usuario sea un deportista activo y establece el rol en la sesión."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not hasattr(request.user, 'athlete_profile'):
            return redirect('users:dashboard_router')
        request.session['active_role'] = 'athlete'
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Procesa y compila el historial de logs, sesiones y datos serializados para gráficos."""
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

        # Evolución de fuerza (mejor 1RM estimado por ejercicio a lo largo del tiempo)
        evolution = exercise_1rm_evolution(profile)
        context['rm_evolution'] = evolution
        context['rm_chart_labels'] = json.dumps(list(evolution.keys()))
        context['rm_chart_data'] = json.dumps(
            {name: [p['1rm'] for p in points] for name, points in evolution.items()}
        )

        return context


class WorkoutPlanCreateView(LoginRequiredMixin, CreateView):
    """
    Permite a los entrenadores crear manualmente un nuevo plan de entrenamiento para sus deportistas.
    """
    model = WorkoutPlan
    form_class = WorkoutPlanForm
    template_name = 'training/workout_plan_form.html'

    def get_form_kwargs(self):
        """Pasa la instancia del entrenador al formulario para filtrar sus atletas asignados."""
        kwargs = super().get_form_kwargs()
        if hasattr(self.request.user, 'trainer_profile'):
            kwargs['trainer'] = self.request.user.trainer_profile
        return kwargs

    def form_valid(self, form):
        """Asigna automáticamente el perfil del entrenador solicitante al plan antes de guardar."""
        form.instance.trainer = self.request.user.trainer_profile
        return super().form_valid(form)

    def get_success_url(self):
        """Redirige al detalle del plan recién creado para añadir ejercicios."""
        return reverse('training:plan_detail', kwargs={'pk': self.object.pk})



class WorkoutPlanDetailView(LoginRequiredMixin, DetailView):
    """
    Vista de detalle de un plan de entrenamiento. Muestra los ejercicios prescritos,
    permitiendo al entrenador añadir ejercicios o al atleta registrar una sesión.
    """
    model = WorkoutPlan
    template_name = 'training/workout_plan_detail.html'
    context_object_name = 'plan'

    def get_context_data(self, **kwargs):
        """Inyecta los formularios y datos de sesión según el rol del usuario."""
        context = super().get_context_data(**kwargs)
        plan = self.object
        context['exercise_form'] = PlannedExerciseForm()

        # Para deportistas: sesión en vivo con per-exercicio (inicio/fin y peso)
        if hasattr(self.request.user, 'athlete_profile'):
            session, _ = WorkoutSession.objects.get_or_create(
                workout_plan=plan,
                athlete=plan.athlete,
            )
            context['session'] = session
            context['session_form'] = WorkoutSessionForm()
            logged_map = {
                le.planned_exercise_id: le
                for le in session.logged_exercises.all()
            }
            context['live_items'] = [
                {'planned': pe, 'logged': logged_map.get(pe.id)}
                for pe in plan.planned_exercises.all().select_related('exercise')
            ]

        if plan.is_completed:
            context['workout_session'] = getattr(plan, 'session', None)

        return context


class LiveWorkoutView(LoginRequiredMixin, DetailView):
    """
    Interfaz interactiva en vivo para que el deportista ejecute y registre serie a serie un entrenamiento.
    Permite iniciar/finalizar cada ejercicio, registrar el peso (si el ejercicio tiene cargas con RM),
    cronometrar el tiempo empleado y mostrar el % respecto al 1RM estimado.
    """
    model = WorkoutPlan
    template_name = 'training/live_workout.html'
    context_object_name = 'plan'

    def dispatch(self, request, *args, **kwargs):
        """Comprueba que el deportista autenticado sea el destinatario del plan antes de dar acceso."""
        obj = self.get_object()
        if hasattr(request.user, 'athlete_profile') and obj.athlete != request.user.athlete_profile:
            messages.error(request, "No tienes acceso a este entrenamiento.")
            return redirect('training:athlete_dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan = self.object
        session, _ = WorkoutSession.objects.get_or_create(
            workout_plan=plan,
            athlete=plan.athlete,
        )
        context['session'] = session
        context['session_form'] = WorkoutSessionForm()
        if plan.is_completed:
            context['workout_session'] = session

        # Mapa ejercicio planificado -> LoggedExercise dentro de esta sesión
        logged_map = {
            le.planned_exercise_id: le
            for le in session.logged_exercises.all()
        }
        context['live_items'] = [
            {'planned': pe, 'logged': logged_map.get(pe.id)}
            for pe in plan.planned_exercises.all().select_related('exercise')
        ]
        return context


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

    try:
        weight_kg = float(request.POST.get('weight_kg', 0.0))
        reps = int(request.POST.get('reps', 0))
        rpe = float(request.POST.get('rpe', 8.0))
    except (TypeError, ValueError):
        return HttpResponse("Datos inválidos", status=400)

    if (
        weight_kg < 0 or weight_kg > 1000 or
        reps < 0 or reps > 1000 or
        rpe < 0 or rpe > 10
    ):
        return HttpResponse("Datos fuera de rango", status=400)

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

    # Actualizar agregados del ejercicio registrado
    logged_ex.actual_sets = str(current_set_count)
    logged_ex.actual_reps = str(sum(int(s.reps or 0) for s in logged_ex.sets.all()))
    logged_ex.actual_load = f"{float(logged_set.weight_kg)}kg" if logged_set.weight_kg else ""
    logged_ex.actual_rpe = str(float(logged_set.rpe or 0))
    logged_ex.save()

    html = f"""
    <div class="flex justify-between items-center bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 animate-fade-in">
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded-md font-bold">Serie {logged_set.set_number}</span>
            <span>{logged_set.weight_kg} kg × {logged_set.reps} reps</span>
        </div>
        <div class="flex items-center gap-3 text-slate-500">
            {"<span class='text-indigo-600 font-bold'>1RM~" + str(logged_set.est_1rm) + "kg</span> · <span class='text-primary font-bold'>" + str(logged_set.pct_1rm) + "% 1RM</span>" if logged_set.pct_1rm else ""}
            <span>RPE {logged_set.rpe}</span>
            <span class="text-emerald-500 font-bold">✓</span>
        </div>
    </div>
    """
    return HttpResponse(html)


@login_required
@require_POST
def start_exercise(request, planned_id):
    """
    Marca el inicio del ejercicio e inicia el cronómetro del mismo.
    Crea (o reutiliza) el WorkoutSession y el LoggedExercise asociado.
    """
    planned_exercise = get_object_or_404(PlannedExercise, pk=planned_id)
    plan = planned_exercise.workout_plan

    if not hasattr(request.user, 'athlete_profile') or plan.athlete != request.user.athlete_profile:
        return HttpResponse("No autorizado", status=403)

    session, _ = WorkoutSession.objects.get_or_create(
        workout_plan=plan,
        athlete=plan.athlete,
    )
    if session.started_at is None:
        session.started_at = timezone.now()
        session.save()

    logged_ex, _ = LoggedExercise.objects.get_or_create(
        workout_session=session,
        planned_exercise=planned_exercise,
    )
    if logged_ex.started_at is None:
        logged_ex.started_at = timezone.now()
        logged_ex.save()

    return _render_live_card(request, planned_exercise, session)


@login_required
@require_POST
def finish_exercise(request, planned_id):
    """
    Finaliza el ejercicio, detiene el cronómetro y conserva la duración total.
    """
    planned_exercise = get_object_or_404(PlannedExercise, pk=planned_id)
    plan = planned_exercise.workout_plan

    if not hasattr(request.user, 'athlete_profile') or plan.athlete != request.user.athlete_profile:
        return HttpResponse("No autorizado", status=403)

    session, _ = WorkoutSession.objects.get_or_create(
        workout_plan=plan,
        athlete=plan.athlete,
    )
    logged_ex, _ = LoggedExercise.objects.get_or_create(
        workout_session=session,
        planned_exercise=planned_exercise,
    )
    if logged_ex.started_at is None:
        logged_ex.started_at = session.started_at or timezone.now()
    logged_ex.finished_at = timezone.now()
    logged_ex.save()

    return _render_live_card(request, planned_exercise, session)


def _render_live_card(request, planned_exercise, session):
    """
    Devuelve el fragmento HTML de la tarjeta de un ejercicio en el modo en vivo.
    """
    logged_ex = LoggedExercise.objects.filter(
        workout_session=session,
        planned_exercise=planned_exercise,
    ).first()
    return render(
        request,
        'training/partials/live_exercise_card.html',
        {
            'planned': planned_exercise,
            'logged': logged_ex,
            'session': session,
        },
    )


@login_required
@require_POST
def generate_smart_plan(request, athlete_id):
    """
    Endpoint para generar un borrador de plan por deporte con sugerencias de ML.
    El entrenador lo revisa y ajusta antes de confirmarlo.
    """
    if not hasattr(request.user, 'trainer_profile'):
        messages.error(request, "Solo los entrenadores pueden generar planes asistidos.")
        return redirect('users:dashboard_router')

    athlete = get_object_or_404(AthleteProfile, pk=athlete_id, assigned_trainer=request.user)

    plan = SmartPlanGenerator.generate_plan_for_athlete(
        trainer_profile=request.user.trainer_profile,
        athlete_profile=athlete
    )

    messages.success(request, f"✨ ¡Borrador de plan '{plan.name}' generado con el asistente ML para {athlete.get_sport_display()}!"
                              " Revísalo y ajústalo antes de confirmarlo.")
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

        # Si venimos del modo en vivo y no se indicó duración, la calculamos desde el inicio
        if not session.duration_minutes and session.started_at:
            delta = timezone.now() - session.started_at
            session.duration_minutes = max(1, int(delta.total_seconds() // 60))
        session.save()

        # Marcar plan como completado
        plan.is_completed = True
        plan.save()

        messages.success(request, f"¡Entrenamiento '{plan.name}' completado con éxito! Gran trabajo.")

        # El modo en vivo redirige a la vista live para no perder el contexto de ejercicios
        if request.POST.get('session_stage') == 'live':
            return redirect('training:live_workout', pk=plan.pk)
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
    """
    Muestra la ficha detallada de un atleta a su entrenador, incluyendo su historial de planes y métricas deportivas.
    """
    model = AthleteProfile
    template_name = 'training/athlete_detail.html'
    context_object_name = 'athlete'

    def get_context_data(self, **kwargs):
        """Carga los planes asignados ordenados por fecha y las métricas avanzadas del deportista."""
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
        """Garantiza que el entrenador solo pueda acceder a los atletas que tiene explícitamente asignados."""
        if hasattr(self.request.user, 'trainer_profile'):
            return AthleteProfile.objects.filter(assigned_trainer=self.request.user)
        return AthleteProfile.objects.none()

    def get_success_url(self):
        """Informa del éxito de la operación y redirige al detalle del deportista."""
        messages.success(self.request, f"Perfil deportivo de {self.object.user.first_name or self.object.user.email} actualizado con éxito.")
        return reverse('training:athlete_detail', kwargs={'pk': self.object.pk})


class ExerciseListView(TrainerRequiredMixin, ListView):
    """
    Catálogo de ejercicios del entrenador: lista, buscador y edición (añadir/modificar/eliminar).
    """
    model = Exercise
    template_name = 'training/exercise_list.html'
    context_object_name = 'exercises'
    paginate_by = 12

    def get_queryset(self):
        qs = Exercise.objects.filter(
            created_by=self.request.user.trainer_profile
        ).order_by('name')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(category__icontains=q)
                | Q(movement_pattern__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_exercises'] = self.get_queryset().count()
        context['search'] = self.request.GET.get('q', '')
        return context


class ExerciseCreateView(TrainerRequiredMixin, CreateView):
    model = Exercise
    form_class = ExerciseForm
    template_name = 'training/exercise_form.html'

    def form_valid(self, form):
        form.instance.created_by = self.request.user.trainer_profile
        messages.success(self.request, f"Ejercicio '{form.instance.name}' creado con éxito.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('training:exercise_list')


class ExerciseUpdateView(TrainerRequiredMixin, UpdateView):
    model = Exercise
    form_class = ExerciseForm
    template_name = 'training/exercise_form.html'

    def get_queryset(self):
        return Exercise.objects.filter(created_by=self.request.user.trainer_profile)

    def form_valid(self, form):
        messages.success(self.request, f"Ejercicio '{form.instance.name}' actualizado con éxito.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('training:exercise_list')


class ExerciseDeleteView(TrainerRequiredMixin, DeleteView):
    model = Exercise
    template_name = 'training/exercise_confirm_delete.html'
    context_object_name = 'exercise'

    def get_queryset(self):
        return Exercise.objects.filter(created_by=self.request.user.trainer_profile)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['usage_count'] = PlannedExercise.objects.filter(exercise=self.object).count()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        usage = PlannedExercise.objects.filter(exercise=self.object).count()
        if usage > 0:
            messages.error(
                request,
                f"No se puede eliminar '{self.object.name}': está usado en {usage} plan(es). "
                "Elimínalo primero de los planes o edítalo.",
            )
            return redirect('training:exercise_list')
        messages.success(request, f"Ejercicio '{self.object.name}' eliminado.")
        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('training:exercise_list')


