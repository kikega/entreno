"""
Comando de administración para entrenar el modelo de ML de progresión de carga.

Uso:
    python manage.py train_plan_model

Construye el dataset supervisado a partir de las series registradas (LoggedSet),
entrena un LGBMRegressor y guarda el modelo serializado con joblib. Si no hay
datos suficientes, aborta informando del mínimo de muestras necesario.
"""
from django.core.management.base import BaseCommand, CommandError

from training.ml.build_dataset import (
    MIN_SAMPLES_FOR_TRAINING,
    build_supervised_dataset,
)
from training.ml.model import MODEL_PATH, train_model


class Command(BaseCommand):
    help = 'Entrena el modelo de ML para sugerir la carga de los planes de entrenamiento.'

    def handle(self, *args, **options):
        self.stdout.write('Construyendo dataset supervisado a partir de LoggedSet...')
        rows, targets = build_supervised_dataset()

        if len(rows) < MIN_SAMPLES_FOR_TRAINING:
            raise CommandError(
                f'Datos insuficientes para entrenar: {len(rows)} ejemplos '
                f'(mínimo {MIN_SAMPLES_FOR_TRAINING}). '
                'Registra más series de entrenamiento reales y reintenta.'
            )

        self.stdout.write(f'Entrenando modelo con {len(rows)} ejemplos...')
        _, metrics = train_model(rows, targets)

        self.stdout.write(self.style.SUCCESS(
            f'Modelo entrenado y guardado en {MODEL_PATH}.\n'
            f'Muestras: {metrics["n_samples"]}\n'
            f'MAE validación: {metrics["val_mae"]:.2f} kg\n'
            f'R² validación: {metrics["val_r2"]:.3f}'
        ))
