from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from training.models import Exercise
from training.templatetags.training_extras import render_markdown
from users.models import TrainerProfile

User = get_user_model()


class ExerciseMarkdownRenderTests(TestCase):
    """
    Pruebas unitarias para el renderizado del formato Markdown de ejercicios (5 puntos)
    y visualización en modales y plantillas.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email='trainer_md@test.com',
            password='testpassword123',
            first_name='Coach',
            last_name='Markdown'
        )
        self.trainer_profile = TrainerProfile.objects.create(user=self.user)

        self.sample_markdown = (
            "### 1. Nombre y objetivo\n"
            "- **Nombre:** Press de Banca con Barra\n"
            "- **Objetivo:** Fuerza y masa del pectoral mayor.\n\n"
            "### 2. Anatomía muscular\n"
            "- **Músculos principales:** Pectoral mayor, tríceps braquial.\n\n"
            "### 3. Ejecución técnica paso a paso\n"
            "- **Setup:** Retracción escapular activa en banco plano.\n\n"
            "### 4. Errores más comunes y cómo evitarlos\n"
            "- **Codos abiertos:** Mantener ángulo a 45-60 grados.\n\n"
            "### 5. Claves de seguridad y variantes\n"
            "- **Seguridad:** Agarre completo con pulgar cerrado."
        )

        self.exercise = Exercise.objects.create(
            name='Press Banca con Barra',
            category='fuerza',
            movement_pattern='empuje_horizontal',
            sport_tags=['powerlifting'],
            description=self.sample_markdown,
            created_by=self.trainer_profile
        )

    def test_render_markdown_filter_headings_and_lists(self):
        """Verifica que el filtro render_markdown convierta los encabezados ### y viñetas en HTML seguro."""
        html = render_markdown(self.sample_markdown)
        self.assertIn('<h3>1. Nombre y objetivo</h3>', html)
        self.assertIn('<h3>2. Anatomía muscular</h3>', html)
        self.assertIn('<h3>3. Ejecución técnica paso a paso</h3>', html)
        self.assertIn('<h3>4. Errores más comunes y cómo evitarlos</h3>', html)
        self.assertIn('<h3>5. Claves de seguridad y variantes</h3>', html)
        self.assertIn('<ul>', html)
        self.assertIn('<li>', html)
        self.assertIn('<strong>Nombre:</strong>', html)
        self.assertIn('<strong>Objetivo:</strong>', html)

    def test_render_markdown_filter_empty(self):
        """Verifica que el filtro maneje valores vacíos o nulos sin fallar."""
        self.assertEqual(render_markdown(None), "")
        self.assertEqual(render_markdown(""), "")

    def test_exercise_detail_modal_view(self):
        """Verifica que la vista modal del ejercicio retorne el HTML con la guía técnica formateada."""
        self.client.force_login(self.user)
        url = reverse('training:exercise_detail_modal', kwargs={'pk': self.exercise.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Press Banca con Barra')
        self.assertContains(response, '1. Nombre y objetivo')
        self.assertContains(response, '2. Anatomía muscular')
