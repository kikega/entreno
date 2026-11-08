from django.views.generic import View, TemplateView, CreateView, DetailView, UpdateView, DeleteView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect, Http404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, date

from django.db.models import Q, Count
from django.utils import timezone

from users.models import AthleteProfile, AthleteProgressLog
from users.forms import AthleteProgressLogForm, AthleteProfileForm
from .models import (
    WorkoutPlan, PlannedExercise, WorkoutSession, LoggedExercise, LoggedSet,
    Exercise, MMATriageProfile, TrainerNotification, Macrocycle, MacrocycleBlock,
)
from .forms import (
    WorkoutPlanForm, PlannedExerciseForm, WorkoutSessionForm, ExerciseForm,
    AthleteMMATriageForm, TrainerMMATriageClinicalForm,
    MacrocycleBlockConfigForm, BlockProgressionPrescribeForm,
)
from .am_macrocycle import (
    build_live_exercise_item,
    build_mesocycle_matrix,
    compute_readiness_adjusted_prescription,
)
from .am_rules_engine import (
    evaluate_am_rules,
    AMMacrocycleGenerator,
    AMUniversalLLMClient,
)
from .analytics import (
    calculate_acwr,
    get_athlete_sport_metrics,
    exercise_1rm_evolution,
    is_rm_based_exercise,
    estimate_1rm,
    pct_of_1rm,
    build_am_historical_ledger,
    build_am_visual_dashboard,
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
    métricas de carga/rendimiento (ACWR), estado de triage MMA y alertas activas.
    """
    trainer = user.trainer_profile
    athletes = list(
        AthleteProfile.objects.filter(assigned_trainer=user)
        .select_related('user', 'mma_triage')
    )
    active_macrocycles_by_athlete = {}
    for mc in (
        Macrocycle.objects.filter(athlete__in=athletes, is_active=True)
        .prefetch_related('blocks')
        .order_by('-created_at')
    ):
        active_macrocycles_by_athlete.setdefault(mc.athlete_id, mc)

    athletes_metrics = []
    pending_triage_count = 0
    for athlete in athletes:
        metrics = get_athlete_sport_metrics(athlete)
        triage = getattr(athlete, 'mma_triage', None)
        if triage and triage.review_status == 'pendiente_revision':
            pending_triage_count += 1
        athletes_metrics.append({
            'athlete': athlete,
            'metrics': metrics,
            'mma_triage': triage,
            'active_macrocycle': active_macrocycles_by_athlete.get(athlete.id),
        })

    unread_notifications = list(
        trainer.notifications.filter(is_read=False)
        .select_related('athlete__user')[:10]
    )

    return {
        'athletes': athletes,
        'athletes_metrics': athletes_metrics,
        'total_athletes': len(athletes),
        'total_plans': trainer.created_plans.count(),
        'total_exercises': Exercise.objects.count(),
        'unread_notifications': unread_notifications,
        'pending_triage_count': pending_triage_count,
    }


def build_athlete_context(user):
    """
    Construye el contexto del área personal del deportista: métricas,
    próximos planes (aislando bloques no publicados), bloque activo del Sistema AM,
    gráficos de peso/composición, historial reciente y ficha de Triage MMA.
    """
    profile = user.athlete_profile
    mma_triage = MMATriageProfile.objects.filter(athlete=profile).first()

    visible_plans_qs = (
        profile.assigned_plans
        .filter(WorkoutPlan.visible_to_athlete_q())
        .select_related('macrocycle_block')
    )
    active_macrocycle = (
        Macrocycle.objects.filter(athlete=profile, is_active=True)
        .order_by('-created_at')
        .first()
    )
    active_block = active_macrocycle.active_published_block if active_macrocycle else None
    active_block_summary = None
    if active_block is not None:
        block_plans = list(
            active_block.workout_plans.order_by('week_number', 'day_number', 'target_date')
        )
        completed_block_plans = sum(1 for p in block_plans if p.is_completed)
        active_block_summary = {
            'block': active_block,
            'plans': block_plans,
            'total_sessions': len(block_plans),
            'completed_sessions': completed_block_plans,
            'next_block_plan': next((p for p in block_plans if not p.is_completed), None),
        }

    context = {
        'metrics': get_athlete_sport_metrics(profile),
        'total_completed_workouts': profile.sessions.count(),
        'next_plan': visible_plans_qs.filter(is_completed=False).order_by('target_date').first(),
        'visible_plans': list(visible_plans_qs.order_by('-target_date')[:5]),
        'active_block_summary': active_block_summary,
        'trainer': profile.assigned_trainer,
        'log_form': AthleteProgressLogForm(),
        'profile': profile,
        'mma_triage': mma_triage,
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

    def _get_preselected_athlete(self):
        athlete_id = self.request.GET.get('athlete') or self.request.POST.get('preselected_athlete')
        if not athlete_id or not str(athlete_id).isdigit():
            return None
        return AthleteProfile.objects.filter(
            Q(assigned_trainer=self.request.user) | Q(user=self.request.user),
            pk=int(athlete_id),
        ).first()

    def get_initial(self):
        initial = super().get_initial()
        athlete = self._get_preselected_athlete()
        if athlete:
            initial['athlete'] = athlete.pk
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['preselected_athlete'] = self._get_preselected_athlete()
        return context

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
        """Restringe el acceso al entrenador creador y al deportista asignado (solo si el bloque está publicado)."""
        obj = super().get_object(queryset)
        user = self.request.user
        can_manage = user.is_trainer and obj.trainer == user.trainer_profile
        is_athlete_allowed = (
            user.is_athlete
            and obj.athlete == user.athlete_profile
            and obj.is_visible_to_athlete
        )
        if not (can_manage or is_athlete_allowed):
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
                for le in session.logged_exercises.select_related('substituted_exercise').prefetch_related('sets').all()
            }
            context['live_items'] = [
                build_live_exercise_item(pe, session, logged_map.get(pe.id))
                for pe in plan.planned_exercises.all().select_related(
                    'exercise__regression_option_a',
                    'exercise__regression_option_b',
                )
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
        """Comprueba que el deportista autenticado sea el destinatario y que el bloque esté publicado."""
        if not request.user.is_authenticated or not request.user.is_athlete:
            return super().dispatch(request, *args, **kwargs)
        obj = self.get_object()
        if obj.athlete != request.user.athlete_profile:
            messages.error(request, "No tienes acceso a este entrenamiento.")
            return redirect('home')
        if not obj.is_visible_to_athlete:
            raise Http404("Este bloque de entrenamiento aún no ha sido publicado.")
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
            for le in session.logged_exercises.select_related('substituted_exercise').prefetch_related('sets').all()
        }
        context['live_items'] = [
            build_live_exercise_item(pe, session, logged_map.get(pe.id))
            for pe in plan.planned_exercises.all().select_related(
                'exercise__regression_option_a',
                'exercise__regression_option_b',
            )
        ]
        context['readiness_levels'] = [
            {'level': 5, 'short': '5 · Óptimo', 'Zone': 'green'},
            {'level': 4, 'short': '4 · Bien', 'Zone': 'green'},
            {'level': 3, 'short': '3 · Normal', 'Zone': 'green'},
            {'level': 2, 'short': '2 · Fatiga', 'Zone': 'yellow'},
            {'level': 1, 'short': '1 · Colapso', 'Zone': 'red'},
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

    # Validar permisos y visibilidad del bloque
    if (
        not request.user.is_athlete
        or plan.athlete != request.user.athlete_profile
        or not plan.is_visible_to_athlete
    ):
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

    live_item = build_live_exercise_item(planned_exercise, session, logged_ex)
    if live_item['is_omitted_by_injury']:
        return HttpResponse(
            "Ejercicio omitido por lesión articular (OMITIDO_POR_LESION).",
            status=400,
        )
    if live_item['adjusted']['is_suppressed']:
        return HttpResponse(
            "Este bloque está suprimido hoy por Colapso Sistémico (Nivel 1).",
            status=400,
        )
    if logged_ex.sets.count() >= live_item['target_sets_count']:
        return HttpResponse(
            "Serie bloqueada: ya has completado todas las series prescritas para esta sesión (protección de volumen/descarga).",
            status=400,
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

    if request.headers.get('HX-Target') == f'live-card-{planned_exercise.id}':
        if logged_ex.started_at is None:
            logged_ex.started_at = timezone.now()
            logged_ex.save(update_fields=['started_at'])
        return _render_live_card(request, planned_exercise, session)

    html = f"""
    <div class="flex flex-wrap justify-between items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 animate-fade-in">
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 bg-sky-100 text-sky-800 rounded-md font-bold">Serie {logged_set.set_number}</span>
            <span>{logged_set.weight_kg} kg × {logged_set.reps} reps</span>
        </div>
        <div class="flex items-center gap-3 text-slate-500">
            {"<span class='text-sky-600 font-bold'>1RM~" + str(logged_set.est_1rm) + " kg</span> · <span class='text-primary font-bold'>" + str(logged_set.pct_1rm) + "% 1RM</span>" if logged_set.pct_1rm else ""}
            <span>RPE {logged_set.rpe}</span>
            <span class="text-emerald-600 font-bold">✓</span>
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

    if (
        not request.user.is_athlete
        or plan.athlete != request.user.athlete_profile
        or not plan.is_visible_to_athlete
    ):
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

    if (
        not request.user.is_athlete
        or plan.athlete != request.user.athlete_profile
        or not plan.is_visible_to_athlete
    ):
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
    Devuelve el fragmento HTML de la tarjeta de un ejercicio en el modo en vivo,
    incluyendo prescripción adaptada por el Semáforo de Disposición (1-5),
    Árbol Autónomo de Dolor Articular (⚠️) y Bloqueo de Series en Descarga.
    """
    logged_ex = (
        LoggedExercise.objects.filter(
            workout_session=session,
            planned_exercise=planned_exercise,
        )
        .select_related('substituted_exercise')
        .prefetch_related('sets')
        .first()
    )
    item = build_live_exercise_item(planned_exercise, session, logged_ex)
    return render(
        request,
        'training/partials/live_exercise_card.html',
        {
            'item': item,
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
    if not plan.is_visible_to_athlete:
        return HttpResponse("Este bloque aún no ha sido publicado.", status=403)

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
        """Carga los planes asignados ordenados por fecha, ficha de Triage MMA, macrociclo activo y métricas del deportista."""
        context = super().get_context_data(**kwargs)
        context['plans'] = self.object.assigned_plans.all().order_by('-target_date')
        context['metrics'] = get_athlete_sport_metrics(self.object)
        context['mma_triage'] = MMATriageProfile.objects.filter(athlete=self.object).first()
        context['active_macrocycle'] = (
            Macrocycle.objects.filter(athlete=self.object, is_active=True)
            .prefetch_related('blocks')
            .order_by('-created_at')
            .first()
        )
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
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
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


class AthleteMMATriageView(AthleteRequiredMixin, View):
    """
    Ficha Única Editable del Atleta para el Sistema AM (Flujos A y B).
    Permite al luchador completar su ingesta inicial o actualizar en cualquier momento su fecha de
    combate, peso o marcas (RM / Wingate) sobre el mismo expediente único, activando automáticamente
    el protocolo 'Reset on Submit' sin exponer jamás las columnas privadas del entrenador.
    """
    template_name = 'training/mma_triage_athlete_form.html'

    def _get_or_init_triage(self, athlete: AthleteProfile) -> MMATriageProfile:
        triage, created = MMATriageProfile.objects.get_or_create(
            athlete=athlete,
            defaults={
                'fasting_weight_kg': athlete.weight,
            },
        )
        return triage

    def get(self, request, *args, **kwargs):
        triage = self._get_or_init_triage(request.user.athlete_profile)
        form = AthleteMMATriageForm(instance=triage)
        return render(request, self.template_name, {
            'form': form,
            'triage': triage,
        })

    def post(self, request, *args, **kwargs):
        triage = self._get_or_init_triage(request.user.athlete_profile)
        form = AthleteMMATriageForm(request.POST, instance=triage)
        if form.is_valid():
            updated_triage = form.save(commit=False)
            updated_triage.submit_by_athlete()
            messages.success(
                request,
                "Tu Ficha Única MMA se ha actualizado correctamente. "
                "Tu entrenador ha recibido una alerta para revisar los cambios."
            )
            return redirect('training:athlete_mma_triage')

        messages.error(
            request,
            "Revisa los campos marcados en rojo antes de guardar tu ficha."
        )
        return render(request, self.template_name, {
            'form': form,
            'triage': triage,
        })


class TrainerMMATriageReviewView(TrainerRequiredMixin, View):
    """
    Panel Clínico Privado y Cerrojo Manual del Entrenador para el Sistema AM (Flujo A pasos 3-4 y Flujo B).
    Permite al entrenador asignado completar pruebas durante la entrevista (Ángulo ISA, Wingate, RM),
    configurar Hard Overrides de candados, Vetos Biomecánicos, Directrices Clínicas Privadas
    (`Prompt_Override`) y activar/desactivar el Cerrojo Manual (`approved_for_generation`).
    """
    template_name = 'training/mma_triage_trainer_clinical.html'

    def _get_authorized_athlete(self, request, pk: int) -> AthleteProfile:
        return get_object_or_404(
            AthleteProfile.objects.select_related('user').filter(
                Q(assigned_trainer=request.user) | Q(user=request.user)
            ),
            pk=pk,
        )

    def get(self, request, pk: int, *args, **kwargs):
        athlete = self._get_authorized_athlete(request, pk)
        triage, _ = MMATriageProfile.objects.get_or_create(
            athlete=athlete,
            defaults={'fasting_weight_kg': athlete.weight},
        )
        form = TrainerMMATriageClinicalForm(instance=triage)
        return render(request, self.template_name, {
            'athlete': athlete,
            'triage': triage,
            'form': form,
            'am_diagnosis': evaluate_am_rules(triage),
            'llm_enabled': AMUniversalLLMClient.is_enabled_and_configured(),
        })

    def post(self, request, pk: int, *args, **kwargs):
        athlete = self._get_authorized_athlete(request, pk)
        triage, _ = MMATriageProfile.objects.get_or_create(
            athlete=athlete,
            defaults={'fasting_weight_kg': athlete.weight},
        )
        form = TrainerMMATriageClinicalForm(request.POST, instance=triage)
        if form.is_valid():
            updated_triage = form.save(commit=False)
            updated_triage.review_by_trainer(request.user.trainer_profile)
            if updated_triage.approved_for_generation:
                messages.success(
                    request,
                    f"Expediente clínico de {athlete.user.display_name} auditado y APROBADO (Cerrojo Manual activo)."
                )
            else:
                messages.info(
                    request,
                    f"Cambios clínicos guardados para {athlete.user.display_name}. "
                    "El expediente permanece en estado PENDIENTE DE REVISIÓN (Cerrojo desactivado)."
                )
            return redirect('training:trainer_mma_triage', pk=athlete.pk)

        messages.error(
            request,
            "No se pudo guardar la auditoría clínica. Revisa los errores indicados abajo."
        )
        return render(request, self.template_name, {
            'athlete': athlete,
            'triage': triage,
            'form': form,
            'am_diagnosis': evaluate_am_rules(triage),
            'llm_enabled': AMUniversalLLMClient.is_enabled_and_configured(),
        })


@login_required
@require_POST
def mark_notification_read(request, notification_id: int):
    """Marca como leída una alerta operativa del panel del entrenador."""
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)
    notif = get_object_or_404(
        TrainerNotification,
        pk=notification_id,
        trainer=request.user.trainer_profile,
    )
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    if request.headers.get('HX-Request'):
        return HttpResponse("")
    return redirect(f"{reverse('home')}?tab=trainer")


# ==============================================================================
# FASE 3: MACROCICLOS DE 4 BLOQUES, PUBLICACIÓN PROGRESIVA Y MATRIZ DE MESOCICLO
# ==============================================================================

@login_required
@require_POST
def macrocycle_init(request, athlete_id: int):
    """
    Inicializa (o abre si ya existe uno activo) el Macrociclo Sistema AM de 4 bloques
    (Off-Season, Pre-Training Camp, Training Camp y Fight Week) para un deportista asignado.
    Todos los bloques nacen con `is_published=False` (invisibles al atleta hasta publicación).
    """
    if not request.user.is_trainer:
        messages.error(request, "Solo los entrenadores pueden gestionar macrociclos.")
        return redirect('home')

    athlete = get_object_or_404(
        AthleteProfile.objects.select_related('user').filter(
            Q(assigned_trainer=request.user) | Q(user=request.user)
        ),
        pk=athlete_id,
    )
    triage = MMATriageProfile.objects.filter(athlete=athlete).first()
    sessions_per_week = triage.available_days_per_week if triage else 3
    fight_date = triage.next_fight_date if triage else None

    macrocycle = (
        Macrocycle.objects.filter(
            athlete=athlete,
            trainer=request.user.trainer_profile,
            is_active=True,
        )
        .order_by('-created_at')
        .first()
    )
    created = False
    if macrocycle is None:
        macrocycle = Macrocycle.objects.create(
            name=f"Macrociclo Sistema AM — {athlete.user.display_name}",
            trainer=request.user.trainer_profile,
            athlete=athlete,
            target_fight_date=fight_date,
            is_active=True,
        )
        created = True

    macrocycle.initialize_four_blocks(
        weeks_per_block=4,
        sessions_per_week=sessions_per_week,
    )

    if created:
        messages.success(
            request,
            "Macrociclo de 4 bloques (Off-Season, Pre-Training Camp, Training Camp y Fight Week) "
            "inicializado en modo borrador privado."
        )
    return redirect('training:macrocycle_control', pk=macrocycle.pk)


class TrainerMacrocycleControlView(TrainerRequiredMixin, View):
    """
    Panel de Control (`Panel_Control`) del Entrenador para el Macrociclo Sistema AM.
    Permite auditar los 4 bloques progresivos (`Bloque 1` a `Bloque 4`), activar/desactivar
    su publicación progresiva (`[ ] Publicar Bloque 1..4`) y editar/visualizar la Matriz
    de Mesociclo de 4 semanas por día de entrenamiento.
    """
    template_name = 'training/macrocycle_control.html'

    def get(self, request, pk: int, *args, **kwargs):
        macrocycle = get_object_or_404(
            Macrocycle.objects.select_related('athlete__user', 'trainer__user'),
            pk=pk,
            trainer=request.user.trainer_profile,
        )
        macrocycle.initialize_four_blocks()
        blocks = list(
            macrocycle.blocks.prefetch_related('workout_plans').order_by('block_number')
        )

        raw_block_num = request.GET.get('block', '1')
        selected_block_num = int(raw_block_num) if str(raw_block_num).isdigit() else 1
        selected_block = next(
            (b for b in blocks if b.block_number == selected_block_num),
            blocks[0],
        )

        raw_day_num = request.GET.get('day', '1')
        selected_day = int(raw_day_num) if str(raw_day_num).isdigit() else 1
        selected_day = max(1, min(selected_day, selected_block.sessions_per_week or 3))

        matrix = build_mesocycle_matrix(selected_block, day_number=selected_day)
        mma_triage = MMATriageProfile.objects.filter(athlete=macrocycle.athlete).first()

        blocks_info = []
        for b in blocks:
            b_plans = list(b.workout_plans.all())
            blocks_info.append({
                'block': b,
                'total_plans': len(b_plans),
                'completed_plans': sum(1 for p in b_plans if p.is_completed),
            })

        am_catalog_exercises = list(
            Exercise.objects.select_related('regression_option_a', 'regression_option_b')
            .order_by('code', 'name')
        )

        return render(request, self.template_name, {
            'macrocycle': macrocycle,
            'blocks_info': blocks_info,
            'selected_block': selected_block,
            'selected_day': selected_day,
            'matrix': matrix,
            'mma_triage': mma_triage,
            'am_diagnosis': evaluate_am_rules(mma_triage) if mma_triage else None,
            'llm_enabled': AMUniversalLLMClient.is_enabled_and_configured(),
            'am_catalog_exercises': am_catalog_exercises,
            'block_config_form': MacrocycleBlockConfigForm(instance=selected_block),
            'prescribe_form': BlockProgressionPrescribeForm(initial={
                'day_number': selected_day,
                'order': len(matrix['rows']) + 1,
            }),
        })


@login_required
@require_POST
def toggle_block_publication(request, block_id: int):
    """
    Control de Publicación Progresiva (`[ ] Publicar Bloque 1..4`) en `Panel_Control`.
    Solo el entrenador propietario del macrociclo puede proyectar u ocultar un bloque
    en la vista `Entrenamiento_Activo` del deportista.
    """
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    block = get_object_or_404(
        MacrocycleBlock.objects.select_related('macrocycle__athlete__user'),
        pk=block_id,
        macrocycle__trainer=request.user.trainer_profile,
    )

    action = request.POST.get('action', '').strip().lower()
    if action == 'publish':
        new_state = True
    elif action == 'unpublish':
        new_state = False
    elif request.POST.get('mode') == 'checkbox':
        new_state = 'is_published' in request.POST
    else:
        new_state = not block.is_published

    block.set_published(new_state)

    if new_state:
        messages.success(
            request,
            f"✅ '{block.title}' publicado y proyectado en el Entrenamiento Activo de {block.macrocycle.athlete.user.display_name}."
        )
    else:
        messages.info(
            request,
            f"🔒 '{block.title}' ocultado para el deportista (modo borrador privado)."
        )

    day_param = request.POST.get('day') or request.GET.get('day') or '1'
    target_url = f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}&day={day_param}"
    return redirect(target_url)


@login_required
@require_POST
def update_macrocycle_block(request, block_id: int):
    """Actualiza la configuración estructural (subfase, semanas, días, fechas y notas privadas) de un bloque."""
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    block = get_object_or_404(
        MacrocycleBlock.objects.select_related('macrocycle'),
        pk=block_id,
        macrocycle__trainer=request.user.trainer_profile,
    )
    form = MacrocycleBlockConfigForm(request.POST, instance=block)
    if form.is_valid():
        form.save()
        messages.success(request, f"Configuración de '{block.title}' actualizada.")
    else:
        messages.error(request, "No se pudo actualizar el bloque. Revisa los valores introducidos.")

    return redirect(
        f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}"
    )


@login_required
@require_POST
def prescribe_block_exercise(request, block_id: int):
    """
    Prescribe un ejercicio y su progresión en las 4 semanas (o `weeks_count` semanas) de un bloque
    para un día de sesión concreto, aplicando dos garantías clave del Sistema AM:
      1. Recálculo No Destructivo: jamás altera semanas ya completadas o con series reales (`LoggedSet`).
      2. Nomenclatura Fraccionada y Regla de Accesorios: fuerza RIR 3-4 automáticamente en `B4_Accesorio`
         si el atleta está en mantenimiento o corte de peso.
    """
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    block = get_object_or_404(
        MacrocycleBlock.objects.select_related('macrocycle__athlete', 'macrocycle__trainer'),
        pk=block_id,
        macrocycle__trainer=request.user.trainer_profile,
    )
    form = BlockProgressionPrescribeForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Datos de prescripción inválidos. Revisa el formulario.")
        return redirect(
            f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}"
        )

    exercise = form.cleaned_data['exercise']
    session_block = form.cleaned_data['session_block'] or exercise.session_block or ''
    day_num = min(form.cleaned_data['day_number'], block.sessions_per_week or 6)
    order = form.cleaned_data['order']
    tempo = form.cleaned_data['tempo']
    rest = form.cleaned_data['rest']
    focus = form.cleaned_data['focus']
    notes = form.cleaned_data['notes']

    base_date = block.start_date or timezone.now().date()
    athlete = block.macrocycle.athlete
    trainer = block.macrocycle.trainer

    updated_weeks = 0
    preserved_weeks = 0

    for week_num in block.week_numbers:
        plan_date = base_date + timedelta(days=(week_num - 1) * 7 + (day_num - 1) * 2)
        plan = (
            WorkoutPlan.objects.filter(
                macrocycle_block=block,
                week_number=week_num,
                day_number=day_num,
            )
            .order_by('id')
            .first()
        )
        if plan is None:
            plan = WorkoutPlan.objects.create(
                name=f"{block.title} · Semana {week_num} · Día {day_num}",
                trainer=trainer,
                athlete=athlete,
                macrocycle_block=block,
                week_number=week_num,
                day_number=day_num,
                sport=athlete.sport or 'mma',
                target_date=plan_date,
            )

        # Salvaguarda no destructiva: nunca sobrescribir semanas con historial real
        if plan.has_logged_activity:
            preserved_weeks += 1
            continue

        spec = form.week_spec(week_num)
        pe = PlannedExercise.objects.filter(
            workout_plan=plan,
            exercise=exercise,
            order=order,
        ).first()
        if pe is None:
            pe = PlannedExercise(
                workout_plan=plan,
                exercise=exercise,
                order=order,
            )
        pe.session_block = session_block
        pe.sets = spec['sets']
        pe.reps = spec['reps']
        pe.rir = spec['rir']
        pe.rpe = spec['rpe']
        pe.load = spec['load']
        pe.tempo = tempo
        pe.rest = rest
        pe.focus = focus
        pe.notes = notes
        pe.save()
        updated_weeks += 1

    msg = f"Ejercicio '{exercise.name}' pautado en {updated_weeks} semana(s) del Día {day_num}."
    if preserved_weeks:
        msg += f" Se protegieron intactas {preserved_weeks} semana(s) con marcas ya registradas."
    messages.success(request, msg)

    return redirect(
        f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}&day={day_num}"
    )


class AthleteActiveBlockView(AthleteRequiredMixin, View):
    """
    Vista `Entrenamiento_Activo` del deportista (Sistema AM §4).
    Proyecta exclusivamente el bloque publicado activo en formato de Matriz de 4 Semanas,
    manteniendo 100 % invisibles e inaccesibles (`404`) los bloques no publicados y las
    notas privadas de auditoría del entrenador.
    """
    template_name = 'training/active_block_athlete.html'

    def get(self, request, *args, **kwargs):
        profile = request.user.athlete_profile
        macrocycle = (
            Macrocycle.objects.filter(athlete=profile, is_active=True)
            .order_by('-created_at')
            .first()
        )

        published_blocks = list(macrocycle.published_blocks) if macrocycle else []
        requested_block_id = request.GET.get('block')
        selected_block = None

        if requested_block_id:
            if not str(requested_block_id).isdigit():
                raise Http404("Bloque no encontrado.")
            selected_block = get_object_or_404(
                MacrocycleBlock,
                pk=int(requested_block_id),
                macrocycle__athlete=profile,
                is_published=True,
            )
        elif macrocycle is not None:
            selected_block = macrocycle.active_published_block

        selected_day = 1
        matrix = None
        if selected_block is not None:
            raw_day = request.GET.get('day', '1')
            selected_day = int(raw_day) if str(raw_day).isdigit() else 1
            selected_day = max(1, min(selected_day, selected_block.sessions_per_week or 3))
            matrix = build_mesocycle_matrix(selected_block, day_number=selected_day)

        return render(request, self.template_name, {
            'macrocycle': macrocycle if published_blocks else None,
            'published_blocks': published_blocks,
            'selected_block': selected_block,
            'selected_day': selected_day,
            'matrix': matrix,
        })


# ==============================================================================
# FASE 4: MOTOR DE REGLAS ALGORÍTMICAS DE 8 MÓDULOS + ML / LLM OPCIONAL (.env)
# ==============================================================================

@login_required
@require_POST
def generate_am_macrocycle(request, athlete_id: int):
    """
    Dispara la generación o recálculo no destructivo de los 4 bloques del Macrociclo
    Sistema AM aplicando los 8 Módulos Algorítmicos y el predictor ML de la aplicación
    (o el conector LLM configurado en `.env` si `AM_LLM_ENABLED=True`).
    Exige obligatoriamente el Cerrojo Manual (`approved_for_generation=True`).
    """
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    athlete = get_object_or_404(
        AthleteProfile.objects.select_related('user').filter(
            Q(assigned_trainer=request.user) | Q(user=request.user)
        ),
        pk=athlete_id,
    )
    triage, _ = MMATriageProfile.objects.get_or_create(
        athlete=athlete,
        defaults={'fasting_weight_kg': athlete.weight},
    )

    try:
        result = AMMacrocycleGenerator.generate_or_recalculate_macrocycle(
            triage=triage,
            trainer=request.user.trainer_profile,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('training:trainer_mma_triage', pk=athlete.pk)

    macrocycle = result['macrocycle']
    engine_label = (
        f"LLM ({result['engine_source']}) + ML"
        if str(result['engine_source']).startswith('llm:')
        else "Motor Determinista 8 Módulos + ML"
    )
    msg = (
        f"⚡ Macrociclo generado/recalculado con {engine_label}: "
        f"{result['generated_plans']} sesiones actualizadas "
        f"(ML predictivo en {result['ml_predictions_used']} prescripciones)."
    )
    if result['preserved_plans']:
        msg += f" Se protegieron intactas {result['preserved_plans']} sesiones con marcas reales registradas."
    messages.success(request, msg)
    return redirect('training:macrocycle_control', pk=macrocycle.pk)


@login_required
@require_POST
def recalculate_block_calendar_view(request, block_id: int):
    """
    Módulo 8 (Recálculo Dinámico de Calendario No Destructivo):
    Reestructura un bloque activo cuando cambia la fecha de pelea a mitad de bloque
    (Adelanto a 3 semanas, Short-Notice <= 14 días, Retraso a 5 semanas o Modelo Pendular 6-8 semanas)
    preservando el 100 % de las semanas ya completadas o con series registradas.
    """
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    block = get_object_or_404(
        MacrocycleBlock.objects.select_related('macrocycle__athlete__user'),
        pk=block_id,
        macrocycle__trainer=request.user.trainer_profile,
    )
    athlete = block.macrocycle.athlete
    triage = MMATriageProfile.objects.filter(athlete=athlete).first()

    raw_date = (request.POST.get('next_fight_date') or '').strip()
    new_fight_date = None
    if raw_date:
        try:
            new_fight_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Formato de fecha de combate inválido (usa YYYY-MM-DD).")
            return redirect(
                f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}"
            )
    elif triage and triage.next_fight_date:
        new_fight_date = triage.next_fight_date
    elif block.macrocycle.target_fight_date:
        new_fight_date = block.macrocycle.target_fight_date

    if new_fight_date is None:
        messages.error(request, "Indica la nueva fecha de combate para recalcular el calendario del bloque.")
        return redirect(
            f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}"
        )

    result = AMMacrocycleGenerator.recalculate_block_calendar(
        block=block,
        new_fight_date=new_fight_date,
        triage=triage,
    )
    messages.success(
        request,
        f"📅 Módulo 8 ({result['mode']}): {result['description']} "
        f"(Sesiones con historial protegidas: {result['preserved_plans']})."
    )
    return redirect(
        f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}"
    )


# ==============================================================================
# FASE 5: SEMÁFORO DE DISPOSICIÓN DIARIA, ÁRBOL DE DOLOR ARTICULAR,
#         BLOQUEO DE SERIES EN DESCARGA Y EDICIÓN RÁPIDA XLOOKUP
# ==============================================================================

@login_required
@require_POST
def update_session_readiness(request, plan_id: int):
    """
    Actualiza el Semáforo de Disposición Diaria (Niveles 1 a 5) en la sesión activa
    y recalcula en tiempo real las prescripciones dinámicas:
      - Nivel 3-5 (Verde): Esquema_Normal
      - Nivel 2 (Amarillo): Esquema_Fatiga (+1 serie B1, B2/B3 a RPE 6, -1 serie/-1 RPE en B4 accesorio, B5 Zona 2)
      - Nivel 1 (Rojo): Esquema_Regenerativo (suprime 100% B2/B3, B4 bombeo RIR 5-6, B5 Zona 2 sin impacto)
    Si el atleta reporta Nivel 1 o 2, notifica al entrenador (`low_readiness`).
    """
    if not request.user.is_athlete:
        return HttpResponse("No autorizado", status=403)

    plan = get_object_or_404(
        WorkoutPlan.objects.select_related('macrocycle_block', 'trainer__user', 'athlete__user'),
        pk=plan_id,
        athlete=request.user.athlete_profile,
    )
    if not plan.is_visible_to_athlete:
        return HttpResponse("No autorizado", status=403)

    raw_level = (request.POST.get('readiness_level') or '4').strip()
    try:
        level = max(1, min(5, int(raw_level)))
    except ValueError:
        level = 4

    session, _ = WorkoutSession.objects.get_or_create(
        workout_plan=plan,
        athlete=request.user.athlete_profile,
    )
    previous_level = session.readiness_level
    session.readiness_level = level
    session.save(update_fields=['readiness_level'])

    if level in (1, 2) and previous_level != level and plan.trainer_id:
        meta = session.readiness_ui_meta
        TrainerNotification.objects.create(
            trainer=plan.trainer,
            athlete=plan.athlete,
            event_type='low_readiness',
            message=(
                f"{plan.athlete.user.display_name} activó '{meta['badge']}' "
                f"en '{plan.name}' ({meta['summary']})."
            ),
        )

    if request.headers.get('HX-Request'):
        planned_exercises = list(
            plan.planned_exercises.select_related(
                'exercise',
                'exercise__regression_option_a',
                'exercise__regression_option_b',
            ).order_by('order', 'id')
        )
        logged_dict = {
            le.planned_exercise_id: le
            for le in session.logged_exercises.select_related(
                'substituted_exercise',
            ).prefetch_related('sets')
        }
        live_items = [
            build_live_exercise_item(
                pe,
                session=session,
                logged=logged_dict.get(pe.id),
            )
            for pe in planned_exercises
        ]
        return render(request, 'training/partials/live_workout_list_area.html', {
            'plan': plan,
            'session': session,
            'live_items': live_items,
            'readiness_levels': [
                {'level': 5, 'short': '5 · Óptimo', 'Zone': 'green'},
                {'level': 4, 'short': '4 · Bien', 'Zone': 'green'},
                {'level': 3, 'short': '3 · Normal', 'Zone': 'green'},
                {'level': 2, 'short': '2 · Fatiga', 'Zone': 'yellow'},
                {'level': 1, 'short': '1 · Colapso', 'Zone': 'red'},
            ],
        })

    return redirect('training:live_workout', pk=plan.id)


@login_required
@require_POST
def trigger_pain_tree(request, planned_id: int):
    """
    Árbol Autónomo de Sustitución por Dolor Articular (`⚠️ Molestia`):
      normal -> option_a (Isopush/Isohold) -> option_b (Cambio de Vector) -> omitted_injury (OMITIDO_POR_LESION).
    También admite `action='reset'`, `'option_a'`, `'option_b'`, `'omitted_injury'`.
    """
    if not request.user.is_athlete:
        return HttpResponse("No autorizado", status=403)

    planned_exercise = get_object_or_404(
        PlannedExercise.objects.select_related(
            'workout_plan__macrocycle_block',
            'workout_plan__trainer',
            'workout_plan__athlete__user',
            'exercise',
            'exercise__regression_option_a',
            'exercise__regression_option_b',
        ),
        pk=planned_id,
        workout_plan__athlete=request.user.athlete_profile,
    )
    plan = planned_exercise.workout_plan
    if not plan.is_visible_to_athlete:
        return HttpResponse("No autorizado", status=403)

    session, _ = WorkoutSession.objects.get_or_create(
        workout_plan=plan,
        athlete=request.user.athlete_profile,
    )
    logged_ex, _ = LoggedExercise.objects.get_or_create(
        workout_session=session,
        planned_exercise=planned_exercise,
    )

    action = (request.POST.get('action') or 'advance').strip()
    new_status = logged_ex.apply_pain_tree_action(action=action)

    if request.POST.get('origin') == 'matrix':
        status_labels = {
            'normal': f"Ejercicio '{planned_exercise.exercise.name}' restablecido al estado original.",
            'option_a': f"⚠️ Molestia articular: Conmutado a Opción A Isométrica ({logged_ex.active_exercise.name}).",
            'option_b': f"⚠️ Persiste molestia: Conmutado a Opción B Cambio de Vector ({logged_ex.active_exercise.name}).",
            'omitted_injury': f"🛑 '{planned_exercise.exercise.name}' marcado como OMITIDO_POR_LESION. Entrenador notificado.",
        }
        messages.warning(request, status_labels.get(new_status, "Estado articular actualizado."))
        block_id = plan.macrocycle_block_id or ''
        day_num = plan.day_number or 1
        return redirect(f"{reverse('training:athlete_active_block')}?block={block_id}&day={day_num}")

    return _render_live_card(request, planned_exercise, session)


@login_required
def exercise_xlookup_meta_view(request):
    """
    Endpoint XLOOKUP de `BD_Local_Ejercicios` para el Entrenador (`Panel_Control`):
    Dado un `exercise_id`, código (`[B4P_001]`) o nombre de ejercicio, devuelve al instante
    su vídeo demostrativo y sus regresiones enlazadas Opción A (Isométrica) y Opción B (Vector).
    """
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    raw_id = (
        request.GET.get('exercise_id')
        or request.GET.get('exercise')
        or ''
    ).strip()
    raw_query = (
        request.GET.get('q')
        or request.GET.get('new_exercise_query')
        or ''
    ).strip()

    exercise = None
    qs = Exercise.objects.select_related('regression_option_a', 'regression_option_b')

    if raw_id and raw_id.isdigit():
        exercise = qs.filter(pk=int(raw_id)).first()
    elif raw_query:
        # Formato datalist: "[CODE] Nombre" o código exacto o nombre
        if raw_query.startswith('[') and ']' in raw_query:
            code_part = raw_query[1:raw_query.index(']')].strip()
            exercise = qs.filter(code__iexact=code_part).first()
        if exercise is None:
            exercise = (
                qs.filter(Q(code__iexact=raw_query) | Q(name__iexact=raw_query)).first()
                or qs.filter(Q(code__icontains=raw_query) | Q(name__icontains=raw_query)).first()
            )

    if request.GET.get('format') == 'json':
        if exercise is None:
            return JsonResponse({'found': False})
        return JsonResponse({
            'found': True,
            'id': exercise.id,
            'code': exercise.code,
            'name': exercise.name,
            'session_block': exercise.session_block,
            'video_url': exercise.video_url,
            'option_a_name': exercise.regression_option_a.name if exercise.regression_option_a else '',
            'option_a_video_url': exercise.effective_option_a_video_url,
            'option_b_name': exercise.regression_option_b.name if exercise.regression_option_b else '',
            'option_b_video_url': exercise.effective_option_b_video_url,
        })

    if exercise is None:
        return HttpResponse(
            '<div class="am-xlookup-preview am-xlookup-empty">'
            'Selecciona o escribe un ejercicio del catálogo AM para previsualizar su vídeo y árbol de dolor.'
            '</div>'
        )

    opt_a_html = (
        f'<span class="am-xlookup-pill">🅰️ {exercise.regression_option_a.name}</span>'
        if exercise.regression_option_a
        else '<span class="am-xlookup-pill am-xlookup-muted">🅰️ Sin Opción A</span>'
    )
    opt_b_html = (
        f'<span class="am-xlookup-pill">🅱️ {exercise.regression_option_b.name}</span>'
        if exercise.regression_option_b
        else '<span class="am-xlookup-pill am-xlookup-muted">🅱️ Sin Opción B</span>'
    )
    video_html = (
        f'<a href="{exercise.video_url}" target="_blank" rel="noopener noreferrer" class="am-xlookup-link">'
        f'▶ Vídeo Demo</a>'
        if exercise.video_url
        else '<span class="am-xlookup-muted">Sin vídeo URL</span>'
    )
    code_badge = f'<code>{exercise.code}</code> · ' if exercise.code else ''
    block_badge = f'<span class="am-xlookup-pill">{exercise.get_session_block_display()}</span>' if exercise.session_block else ''

    return HttpResponse(
        f'<div class="am-xlookup-preview">'
        f'<div class="am-xlookup-main">{code_badge}<strong>{exercise.name}</strong> {block_badge} {video_html}</div>'
        f'<div class="am-xlookup-regressions">{opt_a_html} {opt_b_html}</div>'
        f'</div>'
    )


@login_required
@require_POST
def quick_swap_block_exercise(request, block_id: int):
    """
    Edición rápida del entrenador con autocompletado XLOOKUP (`BD_Local_Ejercicios`):
    Sustituye un ejercicio en una fila (`day_number` + `order`) a lo largo de las semanas
    del bloque que NO tengan actividad registrada (`has_logged_activity == False`),
    enlazando automáticamente su vídeo y sus regresiones Opción A y Opción B.
    """
    if not request.user.is_trainer:
        return HttpResponse("No autorizado", status=403)

    block = get_object_or_404(
        MacrocycleBlock.objects.select_related('macrocycle__athlete__user'),
        pk=block_id,
        macrocycle__trainer=request.user.trainer_profile,
    )

    raw_day = (request.POST.get('day_number') or '1').strip()
    raw_order = (request.POST.get('order') or '1').strip()
    raw_old_ex = (request.POST.get('old_exercise_id') or '').strip()
    raw_new_id = (request.POST.get('new_exercise_id') or '').strip()
    raw_query = (request.POST.get('new_exercise_query') or '').strip()

    day_num = int(raw_day) if raw_day.isdigit() else 1
    order_num = int(raw_order) if raw_order.isdigit() else 1

    qs = Exercise.objects.select_related('regression_option_a', 'regression_option_b')
    new_exercise = None
    if raw_new_id and raw_new_id.isdigit():
        new_exercise = qs.filter(pk=int(raw_new_id)).first()
    elif raw_query:
        if raw_query.startswith('[') and ']' in raw_query:
            code_part = raw_query[1:raw_query.index(']')].strip()
            new_exercise = qs.filter(code__iexact=code_part).first()
        if new_exercise is None:
            new_exercise = (
                qs.filter(Q(code__iexact=raw_query) | Q(name__iexact=raw_query)).first()
                or qs.filter(Q(code__icontains=raw_query) | Q(name__icontains=raw_query)).first()
            )

    if new_exercise is None:
        messages.error(request, "No se encontró el ejercicio seleccionado en el catálogo AM.")
        return redirect(
            f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}&day={day_num}"
        )

    plans = list(
        WorkoutPlan.objects.filter(
            macrocycle_block=block,
            day_number=day_num,
        ).order_by('week_number')
    )

    swapped_weeks = 0
    preserved_weeks = 0
    for plan in plans:
        if plan.has_logged_activity:
            preserved_weeks += 1
            continue
        pe_qs = PlannedExercise.objects.filter(workout_plan=plan, order=order_num)
        if raw_old_ex and raw_old_ex.isdigit():
            pe_qs = pe_qs.filter(exercise_id=int(raw_old_ex)) | PlannedExercise.objects.filter(
                workout_plan=plan, order=order_num
            )
        pe = pe_qs.first()
        if pe:
            pe.exercise = new_exercise
            if new_exercise.session_block:
                pe.session_block = new_exercise.session_block
            pe.save(update_fields=['exercise', 'session_block'])
            swapped_weeks += 1

    msg = (
        f"🔄 XLOOKUP aplicado: '{new_exercise.name}' enlazado con su vídeo y regresiones (Opción A/B) "
        f"en {swapped_weeks} semana(s) del Día {day_num}."
    )
    if preserved_weeks:
        msg += f" Se protegieron intactas {preserved_weeks} semana(s) con marcas registradas."
    messages.success(request, msg)

    return redirect(
        f"{reverse('training:macrocycle_control', kwargs={'pk': block.macrocycle_id})}?block={block.block_number}&day={day_num}"
    )


# ==============================================================================
# FASE 6: REGISTRO_HISTORICO Y DASHBOARD_VISUAL (TELEMETRÍA Y EXPORTACIÓN CSV)
# ==============================================================================

def _resolve_authorized_athlete_for_analytics(request, pk: int) -> AthleteProfile:
    """
    Autoriza la consulta de analítica (`Dashboard_Visual` y `Registro_Historico`)
    únicamente al propio deportista propietario del perfil o a su entrenador asignado.
    """
    user = request.user
    if user.is_athlete and getattr(user, 'athlete_profile', None) and user.athlete_profile.pk == pk:
        return user.athlete_profile
    if user.is_trainer:
        return get_object_or_404(
            AthleteProfile.objects.select_related('user').filter(
                Q(assigned_trainer=user) | Q(user=user)
            ),
            pk=pk,
        )
    raise Http404("Perfil de deportista no autorizado.")


class AMVisualDashboardView(LoginRequiredMixin, View):
    """
    Vista unificada `Dashboard_Visual` + `Registro_Historico` (Sistema AM §4.4 / Fase 6):
    Muestra KPIs biomecánicos (ACWR, sRPE, Tonelaje semanal y por bloque B1..B5,
    Evolución 1RM Brzycki, Semáforo de Disposición Diaria y Árbol de Dolor Articular)
    junto con el libro mayor filtrable de series registradas.
    """
    template_name = 'training/am_visual_dashboard.html'

    def get(self, request, pk: int, *args, **kwargs):
        athlete = _resolve_authorized_athlete_for_analytics(request, pk)
        raw_block = (request.GET.get('block') or '').strip()
        block_id = int(raw_block) if raw_block.isdigit() else None
        session_block = (request.GET.get('session_block') or '').strip() or None
        pain_filter = (request.GET.get('pain_status') or '').strip() or None

        dashboard = build_am_visual_dashboard(athlete)
        ledger = build_am_historical_ledger(
            athlete,
            block_id=block_id,
            session_block=session_block,
            pain_filter=pain_filter,
            limit=250,
        )

        is_trainer_view = bool(
            request.user.is_trainer
            and (athlete.assigned_trainer_id == request.user.id or athlete.user_id == request.user.id)
        )

        return render(request, self.template_name, {
            'athlete': athlete,
            'dashboard': dashboard,
            'historical_ledger': ledger,
            'selected_block_id': block_id,
            'selected_session_block': session_block or '',
            'selected_pain_status': pain_filter or '',
            'session_block_choices': Exercise.SESSION_BLOCK_CHOICES,
            'pain_status_choices': LoggedExercise.PAIN_STATUS_CHOICES,
            'is_trainer_view': is_trainer_view,
        })


class AthleteMyAMDashboardView(AthleteRequiredMixin, View):
    """Atajo directo del deportista autenticado hacia su propio `Dashboard_Visual` y `Registro_Historico`."""

    def get(self, request, *args, **kwargs):
        return AMVisualDashboardView.as_view()(request, pk=request.user.athlete_profile.pk)


@login_required
def export_am_historical_ledger_csv(request, pk: int):
    """
    Exporta el `Registro_Historico` completo de un deportista en formato CSV UTF-8 con BOM
    (compatible directamente con Microsoft Excel / LibreOffice Calc).
    """
    athlete = _resolve_authorized_athlete_for_analytics(request, pk)
    raw_block = (request.GET.get('block') or '').strip()
    block_id = int(raw_block) if raw_block.isdigit() else None
    session_block = (request.GET.get('session_block') or '').strip() or None
    pain_filter = (request.GET.get('pain_status') or '').strip() or None

    ledger = build_am_historical_ledger(
        athlete,
        block_id=block_id,
        session_block=session_block,
        pain_filter=pain_filter,
        limit=None,
    )

    filename = f"Registro_Historico_AM_{athlete.user.first_name or 'Atleta'}_{athlete.id}.csv"
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # UTF-8 BOM para apertura directa en Excel

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Fecha',
        'Bloque_Macrociclo',
        'Semana',
        'Dia',
        'Bloque_Concurrente',
        'Ejercicio_Prescrito',
        'Ejercicio_Ejecutado',
        'Estado_Dolor_Articular',
        'Semaforo_Nivel',
        'Esquema_Fisiologico',
        'Serie_Num',
        'Peso_kg',
        'Repeticiones',
        'RPE_Real',
        'Tonelaje_kg',
        '1RM_Brzycki_kg',
        'sRPE_Sesion',
    ])

    for row in ledger:
        writer.writerow([
            row['date'],
            row['block_title'],
            row['week_number'] or '',
            row['day_number'] or '',
            row['session_block'],
            row['prescribed_exercise'],
            row['executed_exercise'],
            row['pain_status'],
            row['readiness_level'],
            row['readiness_scheme'],
            row['set_number'],
            row['weight_kg'],
            row['reps'],
            row['rpe'] if row['rpe'] is not None else '',
            row['tonnage_kg'],
            row['est_1rm_kg'],
            row['session_srpe'],
        ])

    return response








