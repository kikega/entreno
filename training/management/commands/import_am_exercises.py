"""
Comando de gestión para importar o validar el catálogo maestro de ejercicios
del Sistema AM (`BD_Maestra_Ejercicios`) desde CSV, TSV o Excel (.xlsx), o
generar una plantilla CSV oficial lista para rellenar.

Ejemplos de uso:
    # 1. Generar una plantilla CSV con las 15 columnas oficiales y ejemplos MMA:
    python manage.py import_am_exercises --generate-template plantilla_am.csv

    # 2. Validar en seco (sin escribir en BD) el archivo Excel o CSV del entrenador:
    python manage.py import_am_exercises ruta/BD_Maestra_Ejercicios.xlsx --dry-run

    # 3. Importar el catálogo completo (idempotente: crea nuevos y actualiza existentes):
    python manage.py import_am_exercises ruta/BD_Maestra_Ejercicios.xlsx

    # 4. Asignar autoría a un entrenador específico e indicar pestaña Excel:
    python manage.py import_am_exercises ruta/archivo.xlsx --sheet BD_Maestra_Ejercicios --trainer-email jorge@ejemplo.com
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from training.am_catalog import (
    AMCatalogImportError,
    generate_am_csv_template,
    import_am_catalog_file,
)
from users.models import TrainerProfile


class Command(BaseCommand):
    help = (
        'Importa y actualiza el catálogo cerrado BD_Maestra_Ejercicios del Sistema AM '
        'desde archivos CSV/TSV/XLSX (15 columnas) o genera una plantilla CSV de referencia.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'file_path',
            nargs='?',
            type=str,
            help='Ruta al archivo .csv, .tsv o .xlsx con la tabla BD_Maestra_Ejercicios.',
        )
        parser.add_argument(
            '--generate-template',
            dest='template_path',
            type=str,
            default=None,
            help='Genera una plantilla CSV con las 15 columnas oficiales del Sistema AM en la ruta indicada.',
        )
        parser.add_argument(
            '--empty-template',
            action='store_true',
            help='Usado junto a --generate-template, crea solo la fila de cabeceras sin ejercicios de ejemplo.',
        )
        parser.add_argument(
            '--sheet',
            dest='sheet_name',
            type=str,
            default=None,
            help='Nombre de la pestaña a leer en archivos .xlsx (por defecto busca BD_Maestra_Ejercicios).',
        )
        parser.add_argument(
            '--trainer-email',
            dest='trainer_email',
            type=str,
            default=None,
            help='Correo del entrenador propietario al que asignar los ejercicios (por defecto: Catálogo Global).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Valida y simula la importación completa haciendo rollback al final sin modificar la base de datos.',
        )
        parser.add_argument(
            '--strict',
            action='store_true',
            help='Aborta inmediatamente ante cualquier valor de columna desconocido, URL inválida o referencia ausente.',
        )
        parser.add_argument(
            '--create-missing-regressions',
            action='store_true',
            help='Si Opción A o B referencia un código/nombre no listado en otra fila, crea un ejercicio base automáticamente.',
        )

    def handle(self, *args, **options):
        template_path = options.get('template_path')
        file_path = options.get('file_path')

        if template_path:
            out = generate_am_csv_template(
                template_path,
                include_examples=not options.get('empty_template', False),
            )
            self.stdout.write(self.style.SUCCESS(
                f'Plantilla CSV de BD_Maestra_Ejercicios generada correctamente en: {out}'
            ))
            if not file_path:
                return

        if not file_path:
            raise CommandError(
                'Debes indicar la ruta del archivo CSV/XLSX a importar o usar '
                '--generate-template <ruta.csv> para generar la plantilla.'
            )

        trainer_profile = None
        trainer_email = options.get('trainer_email')
        if trainer_email:
            User = get_user_model()
            user = User.objects.filter(email__iexact=trainer_email.strip()).first()
            if user is None:
                raise CommandError(f"No existe ningún usuario con el correo '{trainer_email}'.")
            trainer_profile = TrainerProfile.objects.filter(user=user).first()
            if trainer_profile is None:
                raise CommandError(
                    f"El usuario '{trainer_email}' no dispone de un perfil de entrenador activo."
                )

        try:
            result = import_am_catalog_file(
                file_path,
                sheet_name=options.get('sheet_name'),
                trainer_profile=trainer_profile,
                dry_run=options.get('dry_run', False),
                strict=options.get('strict', False),
                create_missing_regressions=options.get('create_missing_regressions', False),
            )
        except AMCatalogImportError as exc:
            raise CommandError(str(exc)) from exc

        mode_banner = '[SIMULACIÓN DRY-RUN - SIN CAMBIOS EN BD]' if result.dry_run else '[IMPORTACIÓN COMPLETADA]'
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{mode_banner} Sistema AM - BD_Maestra_Ejercicios'))
        if result.sheet_used:
            self.stdout.write(f'  • Pestaña Excel leída      : {result.sheet_used}')
        self.stdout.write(f'  • Filas procesadas         : {result.total_rows}')
        self.stdout.write(f'  • Ejercicios nuevos        : {result.created_count}')
        self.stdout.write(f'  • Ejercicios actualizados  : {result.updated_count}')
        self.stdout.write(f'  • Vínculos Opción A (Iso)  : {result.linked_option_a_count}')
        self.stdout.write(f'  • Vínculos Opción B (Vec)  : {result.linked_option_b_count}')
        if result.auto_created_stubs:
            self.stdout.write(f'  • Regresiones auto-creadas : {result.auto_created_stubs}')
        if result.skipped_empty_rows:
            self.stdout.write(f'  • Filas vacías ignoradas   : {result.skipped_empty_rows}')

        if result.warnings:
            self.stdout.write(self.style.WARNING(f'\nAvisos ({len(result.warnings)}):'))
            for w in result.warnings:
                self.stdout.write(self.style.WARNING(f'  ⚠ {w}'))

        if result.errors:
            self.stdout.write(self.style.ERROR(f'\nFilas con error omitidas ({len(result.errors)}):'))
            for err in result.errors:
                self.stdout.write(self.style.ERROR(f'  ✖ {err}'))

        self.stdout.write(self.style.SUCCESS('\nProceso finalizado correctamente.'))
