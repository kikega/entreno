from django.views.generic import TemplateView, CreateView, DetailView, UpdateView, DeleteView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect, Http404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

import json
from collections import defaultdict
from datetime import datetime

from django.db.models import Q, Count
from django.utils import timezone

from users.models import AthleteProfile, AthleteProgressLog
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
        if not request.user.is_trainer:
            messages.error(request, "Acción permitida solo para entrenadores.")
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)


class AthleteRequiredMixin(LoginRequiredMixin):
    """Restringe el acceso a usuarios con perfil de deportista."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not request.user.is_athlete:
            messages.error(request, "Acción permitida solo para deportistas.")
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)


def build_trainer_context(user):
    """
    Construye el contexto del área de gestión: deportistas asignados,
    métricas de carga/rendimiento (ACWR) y totales del catálogo.
    """
    trainer = user.trainer_profile
    athletes = AthleteProfile.objects.filter(
        assigned_trainer=user
    ).select_related('user')

    athletes_metrics = []
    for athlete in athletes:
        metrics = get_athlete_sport_metrics(athlete)
        athletes_metrics.append({
            'athlete': athlete,
            'metrics': metrics
        })

    return {
        'athletes': athletes,
        'athletes_metrics': athletes_metrics,
        'total_athletes': len(athletes),
        'total_plans': trainer.created_plans.count(),
        'total_exercises': Exercise.objects.count(),
    }


def build_athlete_context(user):
    """
    Construye el contexto del área personal del deportista: métricas,
    próximos planes, gráficos de peso/composición e historial reciente.
    """
    profile = user.athlete_profile

    context = {
        'metrics': get_athlete_sport_metrics(profile),
        'total_completed_workouts': profile.sessions.count(),
        'next_plan': profile.assigned_plans.filter(is_completed=False).order_by('target_date').first(),
        'trainer': profile.assigned_trainer,
        'log_form': AthleteProgressLogForm(),
        'profile': profile,
    }

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

    context['recent_logs'] = logs.order_by('-date')[:5]

    # Evolución de fuerza (mejor 1RM estimado por ejercicio a lo largo del tiempo)
    evolution = exercise_1rm_evolution(profile)
    context['rm_evolution'] = evolution
    context['rm_chart_labels'] = json.dumps(list(evolution.keys()))
    context['rm_chart_data'] = json.dumps(
        {name: [p['1rm'] for p in points] for name, points in evolution.items()}
    )

    return context


@login_required
def dashboard_redirect(request, tab):
    """
    Redirección de compatibilidad: los antiguos dashboards separados ahora viven
    en el espacio unificado ('home') como pestañas de contexto.
    """
    return HttpResponseRedirect(f"{reverse('home')}?tab={tab}")


class WorkoutPlanCreateView(TrainerRequiredMixin, CreateView):
    """
    Permite a los entrenadores crear manualmente un nuevo plan de entrenamiento para sus deportistas.
    """
    model = WorkoutPlan
    form_class = WorkoutPlanForm
    template_name = 'training/workout_plan_form.html'

    def get_form_kwargs(self):
        """Pasa la instancia del entrenador al formulario para filtrar sus atletas asignados."""
        kwargs = super().get_form_kwargs()
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
    Solo acceden el entrenador que lo creó y el deportista destinatario.
    """
    model = WorkoutPlan
    template_name = 'training/workout_plan_detail.html'
    context_object_name = 'plan'

    def get_object(self, queryset=None):
        """Restringe el acceso al entrenador creador y al deportista asignado al plan."""
        obj = super().get_object(queryset)
        user = self.request.user
        allowed = (
            (user.is_trainer and obj.trainer == user.trainer_profile) or
            (user.is_athlete and obj.athlete == user.athlete_profile)
        )
        if not allowed:
            raise Http404("Plan de entrenamiento no encontrado.")
        return obj

    def get_context_data(self, **kwargs):
        """Inyecta los formularios y datos de sesión según la relación del usuario con el plan."""
        context = super().get_context_data(**kwargs)
        plan = self.object
        user = self.request.user
        is_owner = user.is_athlete and plan.athlete == user.athlete_profile
        can_manage = user.is_trainer and plan.trainer == user.trainer_profile
        context['is_plan_owner'] = is_owner
        context['can_manage_plan'] = can_manage
        context['exercise_form'] = PlannedExerciseForm()

        # Para el deportista destinatario: sesión en vivo con per-exercicio (inicio/fin y peso)
        if is_owner:
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


class LiveWorkoutView(AthleteRequiredMixin, DetailView):
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
        if obj.athlete != request.user.athlete_profile:
            messages.error(request, "No tienes acceso a este entrenamiento.")
            return redirect('home')
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
    if not request.user.is_athlete or plan.athlete != request.user.athlete_profile:
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

    if not request.user.is_athlete or plan.athlete != request.user.athlete_profile:
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

    if not request.user.is_athlete or plan.athlete != request.user.athlete_profile:
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
    if not request.user.is_trainer:
        messages.error(request, "Solo los entrenadores pueden generar planes asistidos.")
        return redirect('home')

    athlete = get_object_or_404(
        AthleteProfile,
        Q(assigned_trainer=request.user) | Q(user=request.user),
        pk=athlete_id
    )

    try:
        plan = SmartPlanGenerator.generate_plan_for_athlete(
            trainer_profile=request.user.trainer_profile,
            athlete_profile=athlete
        )
        messages.success(
            request,
            f"✨ ¡Borrador de plan '{plan.name}' generado con el asistente ML para {athlete.get_sport_display()}! "
            "Revísalo y ajústalo antes de confirmarlo."
        )
        return redirect('training:plan_detail', pk=plan.pk)
    except ValueError as e:
        messages.error(request, f"No se pudo generar el plan asistido: {e}")
        return redirect('training:athlete_detail', pk=athlete_id)


@login_required
@require_POST
def complete_workout(request, plan_id):
    """
    Registra el entrenamiento como completado y guarda la sesión física asociada.
    """
    plan = get_object_or_404(WorkoutPlan, pk=plan_id)

    if not request.user.is_athlete or plan.athlete != request.user.athlete_profile:
        messages.error(request, "No tienes permiso para completar este entrenamiento.")
        return redirect('home')

    form = WorkoutSessionForm(request.POST)

    if form.is_valid():
        session, _ = WorkoutSession.objects.get_or_create(
            workout_plan=plan,
            athlete=request.user.athlete_profile
        )
        session.duration_minutes = form.cleaned_data.get('duration_minutes')
        session.calories_burned = form.cleaned_data.get('calories_burned')
        session.avg_heart_rate = form.cleaned_data.get('avg_heart_rate')
        session.notes = form.cleaned_data.get('notes')

        # Asignar RPE global de la sesión (desde formulario o POST con conversión segura)
        session_rpe = form.cleaned_data.get('session_rpe')
        if session_rpe is None and request.POST.get('session_rpe'):
            try:
                raw_rpe = float(str(request.POST.get('session_rpe')).replace(',', '.'))
                if 1.0 <= raw_rpe <= 10.0:
                    session_rpe = raw_rpe
            except (ValueError, TypeError):
                session_rpe = None

        if session_rpe is not None:
            session.session_rpe = session_rpe

        # Si venimos del modo en vivo y no se indicó duración, la calculamos desde el inicio
        if not session.duration_minutes and session.started_at:
            delta = timezone.now() - session.started_at
            session.duration_minutes = max(1, int(delta.total_seconds() // 60))
        session.save()

        # Marcar plan como completado
        plan.is_completed = True
        plan.save()

        messages.success(request, f"¡Entrenamiento '{plan.name}' completado con éxito! Gran trabajo.")
    else:
        messages.error(request, "Error al registrar la sesión de entrenamiento. Por favor verifica los datos.")

    # El modo en vivo redirige a la vista live para no perder el contexto de ejercicios
    if request.POST.get('session_stage') == 'live':
        return redirect('training:live_workout', pk=plan.pk)

    return HttpResponseRedirect(f"{reverse('home')}?tab=athlete")


@login_required
@require_POST
def add_planned_exercise(request, plan_id):
    """
    Vista diseñada para manejar peticiones POST de HTMX para añadir ejercicios a un plan.
    Restringida al entrenador propietario del plan.
    """
    plan = get_object_or_404(WorkoutPlan, pk=plan_id)
    if not request.user.is_trainer or plan.trainer != request.user.trainer_profile:
        return HttpResponse("No autorizado", status=403)

    form = PlannedExerciseForm(request.POST)
    if form.is_valid():
        planned_exercise = form.save(commit=False)
        planned_exercise.workout_plan = plan
        planned_exercise.save()
        return render(request, 'training/partials/exercise_row.html', {'exercise': planned_exercise})
    return HttpResponse("Error en formulario", status=400)


class AthleteDetailView(TrainerRequiredMixin, DetailView):
    """
    Muestra la ficha detallada de un atleta a su entrenador, incluyendo su historial de planes y métricas deportivas.
    """
    model = AthleteProfile
    template_name = 'training/athlete_detail.html'
    context_object_name = 'athlete'

    def get_queryset(self):
        """Un entrenador solo puede ver la ficha de sus deportistas asignados o la suya propia si es deportista."""
        return AthleteProfile.objects.filter(
            Q(assigned_trainer=self.request.user) | Q(user=self.request.user)
        )

    def get_context_data(self, **kwargs):
        """Carga los planes asignados ordenados por fecha y las métricas avanzadas del deportista."""
        context = super().get_context_data(**kwargs)
        context['plans'] = self.object.assigned_plans.all().order_by('-target_date')
        context['metrics'] = get_athlete_sport_metrics(self.object)
        return context


class TrainerAthleteProfileUpdateView(TrainerRequiredMixin, UpdateView):
    """
    Permite al entrenador editar el perfil deportivo, composición física y datos personales
    de cualquiera de sus deportistas asignados de manera aislada a su propia cuenta de entrenador.
    """
    model = AthleteProfile
    form_class = AthleteProfileForm
    template_name = 'training/trainer_athlete_form.html'
    context_object_name = 'athlete'

    def get_queryset(self):
        """Garantiza que el entrenador solo pueda acceder a los atletas que tiene asignados o a sí mismo."""
        return AthleteProfile.objects.filter(
            Q(assigned_trainer=self.request.user) | Q(user=self.request.user)
        ).select_related('user')

    def form_valid(self, form):
        """Guarda los datos del deportista y actualiza su registro de progreso diario si dispone de peso."""
        response = super().form_valid(form)
        profile = self.object
        if profile.weight is not None:
            AthleteProgressLog.objects.update_or_create(
                athlete=profile,
                date=timezone.now().date(),
                defaults={
                    'weight': profile.weight,
                    'fat_percentage': profile.fat_percentage,
                    'lean_mass_percentage': profile.lean_mass_percentage,
                }
            )
        return response

    def get_success_url(self):
        """Informa del éxito de la operación y redirige al detalle del deportista."""
        messages.success(self.request, f"Perfil deportivo de {self.object.user.first_name or self.object.user.email} actualizado con éxito.")
        return reverse('training:athlete_detail', kwargs={'pk': self.object.pk})


class TrainerAthleteDeleteView(TrainerRequiredMixin, DeleteView):
    """
    Permite al entrenador desasignar un deportista de su gestión («Mis deportistas»).
    No elimina al usuario ni su perfil de deportista de la base de datos (responsabilidad
    exclusiva del administrador), permitiendo que el deportista siga existiendo para
    asignarse a otro entrenador o asumir el rol dual de entrenador y deportista.
    """
    model = AthleteProfile
    template_name = 'training/athlete_confirm_delete.html'
    context_object_name = 'athlete'

    def get_queryset(self):
        """Solo permite desasignar deportistas asignados al entrenador actual."""
        return AthleteProfile.objects.filter(
            assigned_trainer=self.request.user
        ).select_related('user')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plans_count'] = self.object.assigned_plans.count()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        athlete_user = self.object.user
        display_name = f"{athlete_user.first_name} {athlete_user.last_name}".strip() or athlete_user.email

        self.object.assigned_trainer = None
        self.object.trainer_confirmed = False
        self.object.save(update_fields=['assigned_trainer', 'trainer_confirmed', 'updated_at'])

        messages.success(
            request,
            f"Deportista '{display_name}' desasignado de tu lista de deportistas. Su cuenta sigue activa en la plataforma."
        )
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('training:trainer_dashboard')


class ExerciseListView(TrainerRequiredMixin, ListView):
    """
    Catálogo de ejercicios general: accesible para todos los entrenadores independientemente
    de quién haya creado el ejercicio en la base de datos.
    Lista por categorías (pestañas), buscador por nombre y paginación numerada.
    """
    model = Exercise
    template_name = 'training/exercise_list.html'
    context_object_name = 'exercises'
    paginate_by = 12

    def get_queryset(self):
        self.base_qs = Exercise.objects.all()
        qs = self.base_qs.order_by('name')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        self.current_category = self.request.GET.get('cat', '').strip()
        if self.current_category in dict(Exercise.CATEGORY_CHOICES):
            qs = qs.filter(category=self.current_category)
        return qs

    def render_to_response(self, context, **response_kwargs):
        """En peticiones HTMX devuelve solo el bloque de resultados (grid + paginador)."""
        if self.request.headers.get('HX-Request'):
            return render(self.request, 'training/partials/exercise_results.html', context)
        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category_labels = dict(Exercise.CATEGORY_CHOICES)
        counts = (
            self.base_qs.values('category')
            .annotate(total=Count('id'))
            .order_by('-total')
        )
        categories = [
            {'value': item['category'], 'label': category_labels.get(item['category'], item['category']), 'count': item['total']}
            for item in counts
            if item['total'] > 0
        ]
        context['categories'] = categories
        context['total_exercises'] = self.base_qs.count()
        context['current_category'] = getattr(self, 'current_category', '')
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


@login_required
def exercise_detail_modal_view(request, pk):
    """
    Devuelve un fragmento HTML con la ficha técnica completa del ejercicio renderizada en Markdown
    para visualización rápida en modal o panel desplegable.
    """
    exercise = get_object_or_404(Exercise, pk=pk)
    return render(request, 'training/partials/exercise_detail_modal.html', {'exercise': exercise})



