import io
import tempfile
from xml.sax.saxutils import escape as xml_escape
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from training.am_catalog import AM_OFFICIAL_HEADERS, import_am_catalog_file
from training.models import Exercise, ExerciseDisciplineFit
from users.models import TrainerProfile

User = get_user_model()


def _build_minimal_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> None:
    """
    Construye un archivo .xlsx real (OpenXML) en disco con múltiples pestañas,
    sharedStrings y huecos de columnas vacías para probar el lector nativo de Excel.
    """
    shared_strings: list[str] = []
    sst_index: dict[str, int] = {}

    def get_sst_idx(val: str) -> int:
        if val not in sst_index:
            sst_index[val] = len(shared_strings)
            shared_strings.append(val)
        return sst_index[val]

    def col_letter(idx: int) -> str:
        res = ''
        n = idx + 1
        while n > 0:
            n, rem = divmod(n - 1, 26)
            res = chr(65 + rem) + res
        return res

    sheet_xmls: dict[str, str] = {}
    for s_idx, (sheet_name, rows) in enumerate(sheets.items(), start=1):
        row_nodes = []
        for r_idx, row in enumerate(rows, start=1):
            cell_nodes = []
            for c_idx, val in enumerate(row):
                if val == '' or val is None:
                    # Omitimos celdas vacías para verificar que el lector respeta coordenadas (ej. L2, N2)
                    continue
                s_id = get_sst_idx(str(val))
                ref = f"{col_letter(c_idx)}{r_idx}"
                cell_nodes.append(f'<c r="{ref}" t="s"><v>{s_id}</v></c>')
            row_nodes.append(f'<row r="{r_idx}">{"".join(cell_nodes)}</row>')
        sheet_xmls[f'xl/worksheets/sheet{s_idx}.xml'] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_nodes)}</sheetData>'
            '</worksheet>'
        )

    sheets_tags = []
    rels_tags = []
    for s_idx, sheet_name in enumerate(sheets.keys(), start=1):
        sheets_tags.append(
            f'<sheet name="{sheet_name}" sheetId="{s_idx}" r:id="rId{s_idx}"/>'
        )
        rels_tags.append(
            f'<Relationship Id="rId{s_idx}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{s_idx}.xml"/>'
        )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(sheets_tags)}</sheets>'
        '</workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(rels_tags)}'
        '</Relationships>'
    )
    si_nodes = ''.join(f'<si><t>{xml_escape(val)}</t></si>' for val in shared_strings)
    sst_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f'{si_nodes}</sst>'
    )

    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('xl/workbook.xml', workbook_xml)
        zf.writestr('xl/_rels/workbook.xml.rels', rels_xml)
        zf.writestr('xl/sharedStrings.xml', sst_xml)
        for arcname, content in sheet_xmls.items():
            zf.writestr(arcname, content)


class SistemaAMCatalogPhase1Tests(TestCase):
    """Pruebas unitarias e integrales de la Fase 1: Modelo Exercise AM e importador CSV/XLSX."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.trainer_user = User.objects.create_user(
            email='jorge.am@test.com',
            password='Password123!',
            first_name='Jorge',
            last_name='Alcaraz',
        )
        self.trainer_profile = TrainerProfile.objects.create(user=self.trainer_user)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_exercise_code_normalization_and_uniqueness(self):
        """ Múltiples ejercicios sin código AM ('') se guardan como NULL sin chocar; códigos iguales fallan."""
        ex1 = Exercise.objects.create(name='Ejercicio Genérico 1', code='')
        ex2 = Exercise.objects.create(name='Ejercicio Genérico 2', code='   ')
        self.assertIsNone(ex1.code)
        self.assertIsNone(ex2.code)
        self.assertFalse(ex1.is_am_catalog)
        self.assertEqual(str(ex1), 'Ejercicio Genérico 1')

        am_ex = Exercise.objects.create(name='Sentadilla Barra Alta', code=' B4P_001 ')
        self.assertEqual(am_ex.code, 'B4P_001')
        self.assertTrue(am_ex.is_am_catalog)
        self.assertEqual(str(am_ex), '[B4P_001] Sentadilla Barra Alta')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Exercise.objects.create(name='Duplicado', code='B4P_001')

    def test_self_regression_validation_and_effective_videos(self):
        """Un ejercicio no puede apuntar a sí mismo en Opción A/B; hereda vídeo de destino si no tiene override."""
        iso = Exercise.objects.create(
            code='B4P_ISO_01',
            name='Squat Isopush',
            video_url='https://youtube.com/watch?v=iso1',
        )
        main = Exercise.objects.create(
            code='B4P_001',
            name='Sentadilla Barra Alta',
            regression_option_a=iso,
        )
        self.assertEqual(main.effective_option_a_video_url, 'https://youtube.com/watch?v=iso1')

        main.option_a_video_url = 'https://youtube.com/watch?v=override_iso'
        self.assertEqual(main.effective_option_a_video_url, 'https://youtube.com/watch?v=override_iso')

        main.regression_option_a = main
        with self.assertRaises(ValidationError):
            main.clean()

    def test_generate_template_and_idempotent_csv_import(self):
        """Genera la plantilla CSV con manage.py, simula con --dry-run, importa y verifica idempotencia."""
        csv_path = self.tmp_path / 'plantilla_am.csv'
        out = io.StringIO()
        call_command('import_am_exercises', '--generate-template', str(csv_path), stdout=out)
        self.assertTrue(csv_path.exists())

        initial_count = Exercise.objects.count()

        # 1. Simulación dry-run: no debe persistir ningún cambio en BD
        call_command('import_am_exercises', str(csv_path), '--dry-run', stdout=io.StringIO())
        self.assertEqual(Exercise.objects.count(), initial_count)

        # 2. Importación real asignando al entrenador Jorge
        call_command(
            'import_am_exercises',
            str(csv_path),
            '--trainer-email',
            'jorge.am@test.com',
            stdout=io.StringIO(),
        )
        self.assertEqual(Exercise.objects.count(), initial_count + 8)

        squat = Exercise.objects.get(code='B4P_001')
        self.assertEqual(squat.name, 'Sentadilla Barra Alta')
        self.assertEqual(squat.session_block, 'B4_Principal')
        self.assertEqual(squat.category, 'fuerza')
        self.assertEqual(squat.patron_vector, 'Dominante_Rodilla')
        self.assertEqual(squat.movement_pattern, 'dominante_rodilla')
        self.assertEqual(squat.complexity_level, 'Nivel_1_Base')
        self.assertEqual(squat.isa_tag, 'ISA_Estrecho')
        self.assertEqual(squat.compromised_joint, 'Rodillas')
        self.assertEqual(squat.required_equipment, ['Barra olímpica (20 kg) y discos', 'Rack'])
        self.assertEqual(squat.created_by, self.trainer_profile)
        self.assertIsNotNone(squat.regression_option_a)
        self.assertEqual(squat.regression_option_a.code, 'B4P_ISO_01')
        self.assertIsNotNone(squat.regression_option_b)
        self.assertEqual(squat.regression_option_b.code, 'B4P_002')
        self.assertTrue(
            ExerciseDisciplineFit.objects.filter(exercise=squat, sport='mma', fit=5).exists()
        )

        # 3. Re-ejecución idempotente: actualiza los 8 sin duplicar
        res2 = import_am_catalog_file(csv_path, trainer_profile=self.trainer_profile)
        self.assertEqual(res2.created_count, 0)
        self.assertEqual(res2.updated_count, 8)
        self.assertEqual(Exercise.objects.count(), initial_count + 8)

    def test_semicolon_spanish_csv_accents_and_missing_regression_stubs(self):
        """Soporta CSV separado por ';' (Excel ES), tildes en cabeceras/valores y auto-creación de stubs."""
        csv_file = self.tmp_path / 'excel_es.csv'
        content = (
            'ID Ejercicio;Nombre Ejercicio;Bloque Asignado;Patrón Vector;Ruta Candado;'
            'Nivel Complejidad;Material Requerido;Etiqueta ISA;Régimen Contráctil;'
            'Articulación Comprometida;URL Video Oculto;ID Opción A Isométrica;'
            'URL Video Opción A;ID Opción B Vector;URL Video Opción B\n'
            'B4A_010;Press Militar con Barra;B4_Accesorio;Empuje Vertical;Libre;'
            'Nivel 2 Intermedio;Barra olímpica (20 kg) y discos;ISA Ancho;Dinámico Estándar;'
            'Muñecas;https://youtube.com/watch?v=pm1;B4A_ISO_99;'
            'https://youtube.com/watch?v=iso99;Ninguna;-\n'
        )
        csv_file.write_bytes(content.encode('cp1252'))

        call_command(
            'import_am_exercises',
            str(csv_file),
            '--create-missing-regressions',
            stdout=io.StringIO(),
        )
        press = Exercise.objects.get(code='B4A_010')
        self.assertEqual(press.patron_vector, 'Empuje_Vertical')
        self.assertEqual(press.complexity_level, 'Nivel_2_Intermedio')
        self.assertEqual(press.isa_tag, 'ISA_Ancho')
        self.assertEqual(press.contractile_regime, 'Dinamico_Estandar')
        self.assertEqual(press.compromised_joint, 'Munecas')
        self.assertIsNotNone(press.regression_option_a)
        self.assertEqual(press.regression_option_a.code, 'B4A_ISO_99')
        self.assertEqual(press.regression_option_a.video_url, 'https://youtube.com/watch?v=iso99')

    def test_xlsx_multisheet_import_and_catalog_code_search(self):
        """Detecta automáticamente la pestaña BD_Maestra_Ejercicios en un archivo .xlsx y permite buscar por código."""
        xlsx_path = self.tmp_path / 'Sistema_AM_Operaciones.xlsx'
        _build_minimal_xlsx(
            xlsx_path,
            {
                'Panel_Control': [['Resumen', 'Privado']],
                'BD_Maestra_Ejercicios': [
                    AM_OFFICIAL_HEADERS,
                    [
                        'B3_010', 'Landmine Punch Throw', 'B3_Potencia', 'Triple_Extension',
                        'Ruta_Landmine_R2', 'Nivel_1_Base', 'Barra olímpica (20 kg) y discos, Landmine',
                        'Universal', 'Concentrico_Propulsivo', 'Hombros',
                        'https://youtube.com/watch?v=lm10', '', '', 'B3_011',
                        'https://youtube.com/watch?v=lm11',
                    ],
                    [
                        'B3_011', 'MedBall Chest Pass', 'B3_Potencia', 'Empuje_Horizontal',
                        'Ruta_Balistica_Sup_R4', 'Nivel_0_Novato', 'Balones medicinales LIGEROS (<= 6 kg)',
                        'Universal', 'Concentrico_Propulsivo', 'Ninguna',
                        '', '', '', '', '',
                    ],
                ],
            },
        )

        res = import_am_catalog_file(xlsx_path, strict=True)
        self.assertEqual(res.sheet_used, 'BD_Maestra_Ejercicios')
        self.assertEqual(res.created_count, 2)
        self.assertEqual(res.linked_option_b_count, 1)

        b3_10 = Exercise.objects.get(code='B3_010')
        b3_11 = Exercise.objects.get(code='B3_011')
        self.assertEqual(b3_10.regression_option_b, b3_11)
        # El vídeo de B3_011 estaba vacío en su fila y se autocompletó desde URL_Video_Opcion_B
        self.assertEqual(b3_11.video_url, 'https://youtube.com/watch?v=lm11')

        # Verificar que el buscador del catálogo web encuentra por código AM ('B3_010')
        self.client.force_login(self.trainer_user)
        resp = self.client.get(reverse('training:exercise_list'), {'q': 'B3_010'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Landmine Punch Throw')

    def test_strict_mode_rejects_invalid_enum(self):
        """En modo --strict un valor fuera del catálogo cerrado aborta con CommandError y hace rollback."""
        bad_csv = self.tmp_path / 'bad.csv'
        bad_csv.write_text(
            ','.join(AM_OFFICIAL_HEADERS) + '\n'
            'B9_999,Ejercicio Inventado,Bloque_Inexistente,Dominante_Rodilla,Libre,'
            'Nivel_1_Base,Ninguno,Universal,Dinamico_Estandar,Ninguna,,,,,\n',
            encoding='utf-8',
        )
        before = Exercise.objects.count()
        with self.assertRaises(CommandError):
            call_command('import_am_exercises', str(bad_csv), '--strict', stdout=io.StringIO())
        self.assertEqual(Exercise.objects.count(), before)
