"""
Servicio de importación, normalización y validación del catálogo maestro de ejercicios
del Sistema AM (`BD_Maestra_Ejercicios`, 15 columnas) desde archivos CSV, TSV o Excel (.xlsx).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from django.db import transaction

from training.models import Exercise, ExerciseDisciplineFit
from users.models import TrainerProfile

# Las 15 columnas obligatorias definidas en la sección 2.3 del PRD Sistema AM (V2.1)
AM_OFFICIAL_HEADERS: List[str] = [
    'ID_Ejercicio',
    'Nombre_Ejercicio',
    'Bloque_Asignado',
    'Patron_Vector',
    'Ruta_Candado',
    'Nivel_Complejidad',
    'Material_Requerido',
    'Etiqueta_ISA',
    'Regimen_Contractil',
    'Articulacion_Comprometida',
    'URL_Video_Oculto',
    'ID_Opcion_A_Isometrica',
    'URL_Video_Opcion_A',
    'ID_Opcion_B_Vector',
    'URL_Video_Opcion_B',
]

# Filas de ejemplo representativas del Sistema AM para generar plantilla CSV de muestra
AM_SAMPLE_ROWS: List[Dict[str, str]] = [
    {
        'ID_Ejercicio': 'B1_001',
        'Nombre_Ejercicio': 'Respiración Cocodrilo + Rotación Torácica Cuadrupedia',
        'Bloque_Asignado': 'B1_Movilidad',
        'Patron_Vector': 'Rotacional_Core',
        'Ruta_Candado': 'Libre',
        'Nivel_Complejidad': 'Nivel_0_Novato',
        'Material_Requerido': 'Ninguno',
        'Etiqueta_ISA': 'ISA_Estrecho',
        'Regimen_Contractil': 'Dinamico_Estandar',
        'Articulacion_Comprometida': 'Ninguna',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b1_001',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': '',
        'URL_Video_Opcion_B': '',
    },
    {
        'ID_Ejercicio': 'B2_001',
        'Nombre_Ejercicio': 'Lanzamiento Rotacional Balón Medicinal Pared',
        'Bloque_Asignado': 'B2_Velocidad',
        'Patron_Vector': 'Rotacional_Core',
        'Ruta_Candado': 'Candado_Balon_Ligero',
        'Nivel_Complejidad': 'Nivel_1_Base',
        'Material_Requerido': 'Balones medicinales LIGEROS (<= 6 kg)',
        'Etiqueta_ISA': 'Universal',
        'Regimen_Contractil': 'Concentrico_Propulsivo',
        'Articulacion_Comprometida': 'Hombros',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b2_001',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': '',
        'URL_Video_Opcion_B': '',
    },
    {
        'ID_Ejercicio': 'B3_001',
        'Nombre_Ejercicio': 'Cargada de Potencia desde Colgado (Hang Power Clean)',
        'Bloque_Asignado': 'B3_Potencia',
        'Patron_Vector': 'Triple_Extension',
        'Ruta_Candado': 'Candado_Olimpico_R1',
        'Nivel_Complejidad': 'Nivel_3_Avanzado',
        'Material_Requerido': 'Barra olímpica (20 kg) y discos',
        'Etiqueta_ISA': 'Universal',
        'Regimen_Contractil': 'Concentrico_Propulsivo',
        'Articulacion_Comprometida': 'Munecas',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b3_001',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': 'B3_002',
        'URL_Video_Opcion_B': 'https://www.youtube.com/watch?v=ejemplo_b3_002',
    },
    {
        'ID_Ejercicio': 'B3_002',
        'Nombre_Ejercicio': 'Salto con Trap Bar (Trap Bar Jump)',
        'Bloque_Asignado': 'B3_Potencia',
        'Patron_Vector': 'Triple_Extension',
        'Ruta_Candado': 'Ruta_Salto_Lastrado_R3',
        'Nivel_Complejidad': 'Nivel_1_Base',
        'Material_Requerido': 'Trap Bar',
        'Etiqueta_ISA': 'Universal',
        'Regimen_Contractil': 'Concentrico_Propulsivo',
        'Articulacion_Comprometida': 'Rodillas',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b3_002',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': '',
        'URL_Video_Opcion_B': '',
    },
    {
        'ID_Ejercicio': 'B4P_001',
        'Nombre_Ejercicio': 'Sentadilla Barra Alta',
        'Bloque_Asignado': 'B4_Principal',
        'Patron_Vector': 'Dominante_Rodilla',
        'Ruta_Candado': 'Libre',
        'Nivel_Complejidad': 'Nivel_1_Base',
        'Material_Requerido': 'Barra olímpica (20 kg) y discos, Rack',
        'Etiqueta_ISA': 'ISA_Estrecho',
        'Regimen_Contractil': 'Dinamico_Estandar',
        'Articulacion_Comprometida': 'Rodillas',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b4p_001',
        'ID_Opcion_A_Isometrica': 'B4P_ISO_01',
        'URL_Video_Opcion_A': 'https://www.youtube.com/watch?v=ejemplo_b4p_iso_01',
        'ID_Opcion_B_Vector': 'B4P_002',
        'URL_Video_Opcion_B': 'https://www.youtube.com/watch?v=ejemplo_b4p_002',
    },
    {
        'ID_Ejercicio': 'B4P_ISO_01',
        'Nombre_Ejercicio': 'Sentadilla Isométrica contra Pines (Squat Isopush)',
        'Bloque_Asignado': 'B4_Principal',
        'Patron_Vector': 'Dominante_Rodilla',
        'Ruta_Candado': 'Libre',
        'Nivel_Complejidad': 'Nivel_0_Novato',
        'Material_Requerido': 'Barra olímpica (20 kg) y discos, Rack',
        'Etiqueta_ISA': 'Universal',
        'Regimen_Contractil': 'Isopush',
        'Articulacion_Comprometida': 'Ninguna',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b4p_iso_01',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': '',
        'URL_Video_Opcion_B': '',
    },
    {
        'ID_Ejercicio': 'B4P_002',
        'Nombre_Ejercicio': 'Peso Muerto con Barra Hexagonal (Trap Bar Deadlift)',
        'Bloque_Asignado': 'B4_Principal',
        'Patron_Vector': 'Dominante_Cadera',
        'Ruta_Candado': 'Libre',
        'Nivel_Complejidad': 'Nivel_1_Base',
        'Material_Requerido': 'Trap Bar',
        'Etiqueta_ISA': 'ISA_Ancho',
        'Regimen_Contractil': 'Dinamico_Estandar',
        'Articulacion_Comprometida': 'Lumbares',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b4p_002',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': '',
        'URL_Video_Opcion_B': '',
    },
    {
        'ID_Ejercicio': 'B5_001',
        'Nombre_Ejercicio': 'Sprints Repetidos AirBike RSS-P (8s ON / 52s Pasivo)',
        'Bloque_Asignado': 'B5_Cardio',
        'Patron_Vector': 'Ninguno',
        'Ruta_Candado': 'Libre',
        'Nivel_Complejidad': 'Nivel_0_Novato',
        'Material_Requerido': 'AirBike',
        'Etiqueta_ISA': 'Universal',
        'Regimen_Contractil': 'Concentrico_Propulsivo',
        'Articulacion_Comprometida': 'Ninguna',
        'URL_Video_Oculto': 'https://www.youtube.com/watch?v=ejemplo_b5_001',
        'ID_Opcion_A_Isometrica': '',
        'URL_Video_Opcion_A': '',
        'ID_Opcion_B_Vector': '',
        'URL_Video_Opcion_B': '',
    },
]


def _slugify_token(value: str) -> str:
    """Elimina tildes, convierte a minúsculas y colapsa separadores en guiones bajos."""
    if not value:
        return ''
    cleaned = value.replace('\ufeff', '').strip()
    no_accents = ''.join(
        ch for ch in unicodedata.normalize('NFKD', cleaned)
        if not unicodedata.combining(ch)
    )
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', no_accents).strip('_').lower()
    return slug


# Mapa flexible de cabeceras normalizadas -> nombre canónico de columna Sistema AM
HEADER_ALIASES: Dict[str, str] = {
    'id_ejercicio': 'ID_Ejercicio',
    'codigo_ejercicio': 'ID_Ejercicio',
    'codigo': 'ID_Ejercicio',
    'id': 'ID_Ejercicio',
    'code': 'ID_Ejercicio',
    'nombre_ejercicio': 'Nombre_Ejercicio',
    'nombre': 'Nombre_Ejercicio',
    'ejercicio': 'Nombre_Ejercicio',
    'denominacion': 'Nombre_Ejercicio',
    'bloque_asignado': 'Bloque_Asignado',
    'bloque': 'Bloque_Asignado',
    'ubicacion_sesion': 'Bloque_Asignado',
    'patron_vector': 'Patron_Vector',
    'vector': 'Patron_Vector',
    'patron_biomecanico': 'Patron_Vector',
    'ruta_candado': 'Ruta_Candado',
    'candado': 'Ruta_Candado',
    'ruta': 'Ruta_Candado',
    'nivel_complejidad': 'Nivel_Complejidad',
    'complejidad': 'Nivel_Complejidad',
    'nivel': 'Nivel_Complejidad',
    'material_requerido': 'Material_Requerido',
    'material': 'Material_Requerido',
    'equipamiento': 'Material_Requerido',
    'etiqueta_isa': 'Etiqueta_ISA',
    'isa': 'Etiqueta_ISA',
    'angulo_isa': 'Etiqueta_ISA',
    'regimen_contractil': 'Regimen_Contractil',
    'regimen': 'Regimen_Contractil',
    'contraccion': 'Regimen_Contractil',
    'articulacion_comprometida': 'Articulacion_Comprometida',
    'articulacion': 'Articulacion_Comprometida',
    'zona_comprometida': 'Articulacion_Comprometida',
    'url_video_oculto': 'URL_Video_Oculto',
    'url_video': 'URL_Video_Oculto',
    'video_principal': 'URL_Video_Oculto',
    'video_url': 'URL_Video_Oculto',
    'id_opcion_a_isometrica': 'ID_Opcion_A_Isometrica',
    'id_opcion_a': 'ID_Opcion_A_Isometrica',
    'opcion_a_isometrica': 'ID_Opcion_A_Isometrica',
    'opcion_a': 'ID_Opcion_A_Isometrica',
    'url_video_opcion_a': 'URL_Video_Opcion_A',
    'video_opcion_a': 'URL_Video_Opcion_A',
    'id_opcion_b_vector': 'ID_Opcion_B_Vector',
    'id_opcion_b': 'ID_Opcion_B_Vector',
    'opcion_b_vector': 'ID_Opcion_B_Vector',
    'opcion_b': 'ID_Opcion_B_Vector',
    'url_video_opcion_b': 'URL_Video_Opcion_B',
    'video_opcion_b': 'URL_Video_Opcion_B',
}


def _build_choice_lookup(choices: Sequence[Tuple[str, str]], extra_aliases: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for canonical, label in choices:
        lookup[_slugify_token(canonical)] = canonical
        lookup[_slugify_token(label)] = canonical
    if extra_aliases:
        for alias, target in extra_aliases.items():
            lookup[_slugify_token(alias)] = target
    return lookup


SESSION_BLOCK_LOOKUP = _build_choice_lookup(
    Exercise.SESSION_BLOCK_CHOICES,
    {
        'b1': 'B1_Movilidad',
        'movilidad': 'B1_Movilidad',
        'b2': 'B2_Velocidad',
        'velocidad': 'B2_Velocidad',
        'b3': 'B3_Potencia',
        'potencia': 'B3_Potencia',
        'b4_principal': 'B4_Principal',
        'principal': 'B4_Principal',
        'b4_accesorio': 'B4_Accesorio',
        'accesorio': 'B4_Accesorio',
        'b4_auxiliar': 'B4_Auxiliar',
        'auxiliar': 'B4_Auxiliar',
        'b5': 'B5_Cardio',
        'cardio': 'B5_Cardio',
        'sistemas_energeticos': 'B5_Cardio',
    },
)

PATRON_VECTOR_LOOKUP = _build_choice_lookup(
    Exercise.PATRON_VECTOR_CHOICES,
    {
        'rodilla': 'Dominante_Rodilla',
        'cadera': 'Dominante_Cadera',
        'bisagra': 'Dominante_Cadera',
        'anti_rotacion': 'Anti_Movimiento_Core',
        'anti_movimiento': 'Anti_Movimiento_Core',
        'core_rotacional': 'Rotacional_Core',
        'ninguna': 'Ninguno',
        'general': 'Ninguno',
        'na': 'Ninguno',
        'n_a': 'Ninguno',
    },
)

LOCK_ROUTE_LOOKUP = _build_choice_lookup(
    Exercise.LOCK_ROUTE_CHOICES,
    {
        'candado_olimpico': 'Candado_Olimpico_R1',
        'ruta_1': 'Candado_Olimpico_R1',
        'r1': 'Candado_Olimpico_R1',
        'ruta_landmine': 'Ruta_Landmine_R2',
        'ruta_2': 'Ruta_Landmine_R2',
        'r2': 'Ruta_Landmine_R2',
        'ruta_salto_lastrado': 'Ruta_Salto_Lastrado_R3',
        'ruta_3': 'Ruta_Salto_Lastrado_R3',
        'r3': 'Ruta_Salto_Lastrado_R3',
        'ruta_balistica_sup': 'Ruta_Balistica_Sup_R4',
        'ruta_4': 'Ruta_Balistica_Sup_R4',
        'r4': 'Ruta_Balistica_Sup_R4',
        'sin_candado': 'Libre',
        'ninguno': 'Libre',
        'ninguna': 'Libre',
    },
)

COMPLEXITY_LOOKUP = _build_choice_lookup(
    Exercise.COMPLEXITY_LEVEL_CHOICES,
    {
        '0': 'Nivel_0_Novato',
        'nivel_0': 'Nivel_0_Novato',
        'novato': 'Nivel_0_Novato',
        '1': 'Nivel_1_Base',
        'nivel_1': 'Nivel_1_Base',
        'base': 'Nivel_1_Base',
        '2': 'Nivel_2_Intermedio',
        'nivel_2': 'Nivel_2_Intermedio',
        'intermedio': 'Nivel_2_Intermedio',
        '3': 'Nivel_3_Avanzado',
        'nivel_3': 'Nivel_3_Avanzado',
        'avanzado': 'Nivel_3_Avanzado',
    },
)

ISA_TAG_LOOKUP = _build_choice_lookup(
    Exercise.ISA_TAG_CHOICES,
    {
        'estrecho': 'ISA_Estrecho',
        'ancho': 'ISA_Ancho',
        'neutro': 'Universal',
        'todos': 'Universal',
        'ambos': 'Universal',
    },
)

CONTRACTILE_LOOKUP = _build_choice_lookup(
    Exercise.CONTRACTILE_REGIME_CHOICES,
    {
        'estandar': 'Dinamico_Estandar',
        'dinamico': 'Dinamico_Estandar',
        'concentrico': 'Concentrico_Propulsivo',
        'propulsivo': 'Concentrico_Propulsivo',
    },
)

JOINT_LOOKUP = _build_choice_lookup(
    Exercise.COMPROMISED_JOINT_CHOICES,
    {
        'hombro': 'Hombros',
        'lumbar': 'Lumbares',
        'espalda_baja': 'Lumbares',
        'rodilla': 'Rodillas',
        'muneca': 'Munecas',
        'tobillo': 'Tobillos',
        'codo': 'Codos',
        'caderas': 'Cadera',
        'ninguno': 'Ninguna',
        'sin_compromiso': 'Ninguna',
        'na': 'Ninguna',
        'n_a': 'Ninguna',
    },
)

EMPTY_SENTINELS = {
    '', '-', '--', 'n_a', 'na', 'none', 'null',
    'ninguno', 'ninguna', 'sin_material', 'peso_corporal', 'autocarga', 'libre',
}

EMPTY_REF_SENTINELS = {
    '', '-', '--', 'n_a', 'na', 'none', 'null', 'ninguno', 'ninguna', 'no_aplica',
}


class AMCatalogImportError(Exception):
    """Error estructural o de validación estricta al importar el catálogo Sistema AM."""


@dataclass
class AMImportResult:
    """Resumen detallado de la ejecución de importación del catálogo Sistema AM."""
    total_rows: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_empty_rows: int = 0
    linked_option_a_count: int = 0
    linked_option_b_count: int = 0
    auto_created_stubs: int = 0
    dry_run: bool = False
    sheet_used: str = ''
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def parse_equipment_cell(raw_value: str) -> List[str]:
    """
    Convierte la celda `Material_Requerido` en una lista limpia de etiquetas de inventario.
    Soporta valores vacíos ('Ninguno', 'Peso corporal', '-') -> [] y listas separadas por ';', '|' o ','.
    """
    if not raw_value:
        return []
    text = str(raw_value).strip()
    if _slugify_token(text) in EMPTY_SENTINELS:
        return []

    if ';' in text:
        parts = text.split(';')
    elif '|' in text:
        parts = text.split('|')
    else:
        parts = text.split(',')

    seen = set()
    items: List[str] = []
    for part in parts:
        clean = part.strip()
        slug = _slugify_token(clean)
        if not clean or slug in EMPTY_SENTINELS:
            continue
        if slug not in seen:
            seen.add(slug)
            items.append(clean)
    return items


def clean_video_url(raw_value: str, row_num: int, field_label: str, warnings: List[str], strict: bool = False) -> Optional[str]:
    """Limpia y valida enlaces de vídeo de YouTube / web; devuelve None si está vacío."""
    if not raw_value:
        return None
    val = str(raw_value).strip()
    if _slugify_token(val) in EMPTY_REF_SENTINELS or val in {'#', 'pendiente', 'Pendiente'}:
        return None
    parsed = urlparse(val)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return val
    msg = f"Fila {row_num}: '{field_label}' contiene una URL no válida ('{val}')."
    if strict:
        raise AMCatalogImportError(msg)
    warnings.append(msg + " Se omitió el enlace.")
    return None


def derive_legacy_category_and_pattern(session_block: str, patron_vector: str, lock_route: str) -> Tuple[str, str]:
    """
    Deriva automáticamente `Exercise.category` y `Exercise.movement_pattern` para mantener
    compatibilidad total con el motor de analíticas (1RM/ACWR), pestañas de UI y ML.
    """
    block_to_category = {
        'B1_Movilidad': 'movilidad',
        'B2_Velocidad': 'velocidad',
        'B3_Potencia': 'potencia',
        'B4_Principal': 'fuerza',
        'B4_Accesorio': 'fuerza',
        'B4_Auxiliar': 'fuerza',
        'B5_Cardio': 'otro',
    }
    category = block_to_category.get(session_block, 'otro')

    if session_block == 'B5_Cardio':
        return category, 'metabolico'

    vector_to_pattern = {
        'Dominante_Rodilla': 'dominante_rodilla',
        'Dominante_Cadera': 'dominante_cadera',
        'Triple_Extension': 'potencia_olimpica' if lock_route == 'Candado_Olimpico_R1' else 'dominante_cadera',
        'Empuje_Horizontal': 'empuje_horizontal',
        'Empuje_Vertical': 'empuje_vertical',
        'Traccion_Vertical': 'traccion_vertical',
        'Traccion_Horizontal': 'traccion_horizontal',
        'Rotacional_Core': 'core_rotacional',
        'Anti_Movimiento_Core': 'core_rotacional',
        'Ninguno': 'otro',
    }
    movement_pattern = vector_to_pattern.get(patron_vector, 'otro')
    return category, movement_pattern


def _detect_csv_delimiter(header_line: str) -> str:
    """Detecta el delimitador CSV (',', ';' o '\\t') ignorando comas dentro de comillas."""
    candidates = [';', ',', '\t']
    counts = {d: 0 for d in candidates}
    in_quotes = False
    for ch in header_line:
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes and ch in counts:
            counts[ch] += 1
    best = max(candidates, key=lambda d: counts[d])
    return best if counts[best] > 0 else ','


def read_tabular_csv(file_path: Path) -> List[List[str]]:
    """Lee un archivo CSV/TSV probando codificaciones habituales en España/Excel."""
    raw_bytes = file_path.read_bytes()
    text: Optional[str] = None
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise AMCatalogImportError(f"No se pudo decodificar el archivo '{file_path}'.")

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    delimiter = _detect_csv_delimiter(lines[0])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader]


def _excel_col_to_index(cell_ref: str) -> int:
    """Convierte la referencia de celda Excel (ej. 'A1', 'O2', 'AA10') en índice base 0."""
    letters = ''.join(ch for ch in cell_ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return max(0, idx - 1)


def read_tabular_xlsx(file_path: Path, preferred_sheet: Optional[str] = None) -> Tuple[List[List[str]], str]:
    """
    Lee una hoja de un libro Excel (.xlsx) sin requerir dependencias externas usando
    la librería estándar (`zipfile` + `xml.etree.ElementTree`), o `openpyxl` si está disponible.
    Prioriza automáticamente la pestaña 'BD_Maestra_Ejercicios' o 'BD_Local_Ejercicios'.
    """
    if not zipfile.is_zipfile(file_path):
        raise AMCatalogImportError(f"El archivo '{file_path}' no es un libro .xlsx válido.")

    ns_main = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    ns_rel = {'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    r_id_attr = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'

    with zipfile.ZipFile(file_path, 'r') as zf:
        if 'xl/workbook.xml' not in zf.namelist():
            raise AMCatalogImportError(f"Estructura .xlsx inválida en '{file_path}' (falta xl/workbook.xml).")

        # 1. Leer cadenas compartidas (sharedStrings.xml) si existen
        shared_strings: List[str] = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            sst_root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in sst_root.findall('main:si', ns_main):
                texts = [t.text or '' for t in si.findall('.//main:t', ns_main)]
                shared_strings.append(''.join(texts))

        # 2. Resolver mapa rId -> ruta de worksheet
        rels_map: Dict[str, str] = {}
        if 'xl/_rels/workbook.xml.rels' in zf.namelist():
            rels_root = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
            for rel in rels_root.findall('rel:Relationship', ns_rel):
                rid = rel.attrib.get('Id', '')
                target = rel.attrib.get('Target', '').lstrip('/')
                if not target.startswith('xl/'):
                    target = f"xl/{target}"
                rels_map[rid] = target

        wb_root = ET.fromstring(zf.read('xl/workbook.xml'))
        sheets_info: List[Tuple[str, str]] = []
        for idx, sh in enumerate(wb_root.findall('.//main:sheet', ns_main), start=1):
            name = sh.attrib.get('name', f'Sheet{idx}')
            rid = sh.attrib.get(r_id_attr, '')
            xml_path = rels_map.get(rid, f'xl/worksheets/sheet{idx}.xml')
            sheets_info.append((name, xml_path))

        if not sheets_info:
            raise AMCatalogImportError(f"El archivo Excel '{file_path}' no contiene hojas de cálculo.")

        # 3. Seleccionar pestaña destino
        chosen_sheet: Optional[Tuple[str, str]] = None
        if preferred_sheet:
            target_slug = _slugify_token(preferred_sheet)
            for name, xml_path in sheets_info:
                if _slugify_token(name) == target_slug:
                    chosen_sheet = (name, xml_path)
                    break
            if chosen_sheet is None:
                available = ', '.join(n for n, _ in sheets_info)
                raise AMCatalogImportError(
                    f"No se encontró la pestaña '{preferred_sheet}'. Pestañas disponibles: {available}"
                )
        else:
            default_candidates = {'bd_maestra_ejercicios', 'bd_local_ejercicios'}
            for name, xml_path in sheets_info:
                if _slugify_token(name) in default_candidates:
                    chosen_sheet = (name, xml_path)
                    break
            if chosen_sheet is None:
                chosen_sheet = sheets_info[0]

        sheet_name, sheet_xml_path = chosen_sheet
        if sheet_xml_path not in zf.namelist():
            raise AMCatalogImportError(f"No se pudo abrir la hoja '{sheet_name}' ({sheet_xml_path}).")

        # 4. Extraer celdas preservando huecos por coordenada de columna
        ws_root = ET.fromstring(zf.read(sheet_xml_path))
        rows_out: List[List[str]] = []
        for row_el in ws_root.findall('.//main:sheetData/main:row', ns_main):
            cells_by_col: Dict[int, str] = {}
            max_col = -1
            for cell in row_el.findall('main:c', ns_main):
                ref = cell.attrib.get('r', '')
                col_idx = _excel_col_to_index(ref) if ref else (max_col + 1)
                max_col = max(max_col, col_idx)
                cell_type = cell.attrib.get('t', '')

                val_str = ''
                if cell_type == 'inlineStr':
                    texts = [t.text or '' for t in cell.findall('.//main:t', ns_main)]
                    val_str = ''.join(texts)
                else:
                    v_el = cell.find('main:v', ns_main)
                    if v_el is not None and v_el.text is not None:
                        raw_v = v_el.text
                        if cell_type == 's':
                            try:
                                val_str = shared_strings[int(raw_v)]
                            except (ValueError, IndexError):
                                val_str = raw_v
                        else:
                            val_str = raw_v
                cells_by_col[col_idx] = val_str.strip()

            if max_col >= 0:
                row_values = [cells_by_col.get(c, '') for c in range(max_col + 1)]
                rows_out.append(row_values)

        return rows_out, sheet_name


def map_headers(raw_headers: Sequence[str]) -> Dict[str, int]:
    """Mapea la fila de cabeceras del archivo a las claves oficiales del Sistema AM."""
    header_map: Dict[str, int] = {}
    for idx, col_name in enumerate(raw_headers):
        slug = _slugify_token(col_name)
        canonical = HEADER_ALIASES.get(slug)
        if canonical and canonical not in header_map:
            header_map[canonical] = idx

    missing_required = [req for req in ('ID_Ejercicio', 'Nombre_Ejercicio') if req not in header_map]
    if missing_required:
        detected = ', '.join(h for h in raw_headers if h) or '(vacío)'
        raise AMCatalogImportError(
            f"Faltan columnas obligatorias {missing_required}. "
            f"Cabeceras detectadas: [{detected}]. "
            f"Se esperan las columnas de BD_Maestra_Ejercicios (ej. {', '.join(AM_OFFICIAL_HEADERS[:6])}...)."
        )
    return header_map


def _normalize_choice(
    raw_value: str,
    lookup: Dict[str, str],
    field_label: str,
    row_num: int,
    warnings: List[str],
    strict: bool = False,
    default: str = '',
) -> str:
    if not raw_value:
        return default
    slug = _slugify_token(raw_value)
    if not slug or slug in {'-', '--'}:
        return default
    if slug in lookup:
        return lookup[slug]
    msg = f"Fila {row_num}: Valor desconocido '{raw_value}' en columna '{field_label}'."
    if strict:
        raise AMCatalogImportError(msg)
    warnings.append(msg + f" Se dejó como '{default or 'vacío'}'.")
    return default


def import_am_catalog_file(
    file_path: Path | str,
    *,
    sheet_name: Optional[str] = None,
    trainer_profile: Optional[TrainerProfile] = None,
    dry_run: bool = False,
    strict: bool = False,
    create_missing_regressions: bool = False,
) -> AMImportResult:
    """
    Importa un archivo CSV, TSV o XLSX con la tabla `BD_Maestra_Ejercicios` en el modelo `Exercise`.
    Ejecuta el proceso en 2 pasadas dentro de una transacción atómica:
      - Pasada 1: Crea o actualiza (upsert por `code`) cada ejercicio del catálogo y su ajuste MMA.
      - Pasada 2: Vincula el árbol de sustitución por dolor articular (`Opción A` y `Opción B`).
    """
    path = Path(file_path)
    if not path.exists():
        raise AMCatalogImportError(f"El archivo '{path}' no existe.")

    suffix = path.suffix.lower()
    used_sheet = ''
    if suffix == '.xlsx':
        matrix, used_sheet = read_tabular_xlsx(path, preferred_sheet=sheet_name)
    elif suffix in ('.csv', '.tsv', '.txt'):
        matrix = read_tabular_csv(path)
    else:
        raise AMCatalogImportError(
            f"Formato de archivo '{suffix}' no soportado. Usa un archivo .csv, .tsv o .xlsx."
        )

    if not matrix:
        raise AMCatalogImportError(f"El archivo '{path}' está vacío.")

    # Localizar la primera fila no vacía como fila de cabeceras
    header_row_idx = None
    for idx, row in enumerate(matrix):
        if any(cell.strip() for cell in row):
            header_row_idx = idx
            break
    if header_row_idx is None:
        raise AMCatalogImportError(f"El archivo '{path}' no contiene filas con datos.")

    header_map = map_headers(matrix[header_row_idx])
    data_rows = matrix[header_row_idx + 1:]

    result = AMImportResult(dry_run=dry_run, sheet_used=used_sheet)
    pending_regressions: List[Tuple[int, Exercise, str, Optional[str], str, Optional[str]]] = []

    def _cell(row: Sequence[str], col_key: str) -> str:
        col_idx = header_map.get(col_key)
        if col_idx is None or col_idx >= len(row):
            return ''
        return row[col_idx].strip()

    seen_codes_in_file: Dict[str, int] = {}

    with transaction.atomic():
        # --- PASADA 1: Upsert de ejercicios principales ---
        for offset, row in enumerate(data_rows, start=header_row_idx + 2):
            if not any(c.strip() for c in row):
                result.skipped_empty_rows += 1
                continue

            result.total_rows += 1
            raw_code = _cell(row, 'ID_Ejercicio')
            raw_name = _cell(row, 'Nombre_Ejercicio')

            if not raw_code or not raw_name:
                msg = f"Fila {offset}: 'ID_Ejercicio' ('{raw_code}') y 'Nombre_Ejercicio' ('{raw_name}') son obligatorios."
                if strict:
                    raise AMCatalogImportError(msg)
                result.errors.append(msg)
                continue

            code_upper = raw_code.upper()
            if code_upper in seen_codes_in_file:
                dup_msg = (
                    f"Fila {offset}: Código duplicado '{raw_code}' en el mismo archivo "
                    f"(visto antes en fila {seen_codes_in_file[code_upper]})."
                )
                if strict:
                    raise AMCatalogImportError(dup_msg)
                result.warnings.append(dup_msg + " Se sobrescribirá con la última aparición.")
            seen_codes_in_file[code_upper] = offset

            session_block = _normalize_choice(
                _cell(row, 'Bloque_Asignado'), SESSION_BLOCK_LOOKUP,
                'Bloque_Asignado', offset, result.warnings, strict=strict,
            )
            patron_vector = _normalize_choice(
                _cell(row, 'Patron_Vector'), PATRON_VECTOR_LOOKUP,
                'Patron_Vector', offset, result.warnings, strict=strict,
            )
            lock_route = _normalize_choice(
                _cell(row, 'Ruta_Candado'), LOCK_ROUTE_LOOKUP,
                'Ruta_Candado', offset, result.warnings, strict=strict, default='Libre',
            )
            complexity_level = _normalize_choice(
                _cell(row, 'Nivel_Complejidad'), COMPLEXITY_LOOKUP,
                'Nivel_Complejidad', offset, result.warnings, strict=strict,
            )
            isa_tag = _normalize_choice(
                _cell(row, 'Etiqueta_ISA'), ISA_TAG_LOOKUP,
                'Etiqueta_ISA', offset, result.warnings, strict=strict, default='Universal',
            )
            contractile_regime = _normalize_choice(
                _cell(row, 'Regimen_Contractil'), CONTRACTILE_LOOKUP,
                'Regimen_Contractil', offset, result.warnings, strict=strict,
            )
            compromised_joint = _normalize_choice(
                _cell(row, 'Articulacion_Comprometida'), JOINT_LOOKUP,
                'Articulacion_Comprometida', offset, result.warnings, strict=strict, default='Ninguna',
            )

            equipment_list = parse_equipment_cell(_cell(row, 'Material_Requerido'))
            video_url = clean_video_url(
                _cell(row, 'URL_Video_Oculto'), offset, 'URL_Video_Oculto', result.warnings, strict=strict
            )
            opt_a_ref = _cell(row, 'ID_Opcion_A_Isometrica')
            opt_a_video = clean_video_url(
                _cell(row, 'URL_Video_Opcion_A'), offset, 'URL_Video_Opcion_A', result.warnings, strict=strict
            )
            opt_b_ref = _cell(row, 'ID_Opcion_B_Vector')
            opt_b_video = clean_video_url(
                _cell(row, 'URL_Video_Opcion_B'), offset, 'URL_Video_Opcion_B', result.warnings, strict=strict
            )

            category, movement_pattern = derive_legacy_category_and_pattern(
                session_block, patron_vector, lock_route
            )

            existing = Exercise.objects.filter(code__iexact=raw_code).first()
            if existing is None:
                exercise = Exercise(
                    code=raw_code,
                    name=raw_name,
                    category=category,
                    movement_pattern=movement_pattern,
                    sport_tags=['mma'],
                    video_url=video_url,
                    session_block=session_block,
                    patron_vector=patron_vector,
                    lock_route=lock_route,
                    complexity_level=complexity_level,
                    required_equipment=equipment_list,
                    isa_tag=isa_tag,
                    contractile_regime=contractile_regime,
                    compromised_joint=compromised_joint,
                    created_by=trainer_profile,
                )
                exercise.save()
                result.created_count += 1
            else:
                exercise = existing
                exercise.code = raw_code
                exercise.name = raw_name
                exercise.category = category
                exercise.movement_pattern = movement_pattern
                tags = list(exercise.sport_tags or [])
                if 'mma' not in tags:
                    tags.append('mma')
                exercise.sport_tags = tags
                if video_url is not None:
                    exercise.video_url = video_url
                exercise.session_block = session_block
                exercise.patron_vector = patron_vector
                exercise.lock_route = lock_route
                exercise.complexity_level = complexity_level
                exercise.required_equipment = equipment_list
                exercise.isa_tag = isa_tag
                exercise.contractile_regime = contractile_regime
                exercise.compromised_joint = compromised_joint
                if trainer_profile is not None:
                    exercise.created_by = trainer_profile
                exercise.save()
                result.updated_count += 1

            ExerciseDisciplineFit.objects.update_or_create(
                exercise=exercise,
                sport='mma',
                defaults={'fit': 5},
            )

            pending_regressions.append((offset, exercise, opt_a_ref, opt_a_video, opt_b_ref, opt_b_video))

        # --- PASADA 2: Resolución de Opción A (Isométrica) y Opción B (Vector) ---
        by_code: Dict[str, Exercise] = {}
        by_name: Dict[str, Exercise] = {}
        for ex in Exercise.objects.all():
            if ex.code:
                by_code[ex.code.upper()] = ex
            by_name[ex.name.strip().lower()] = ex

        def _resolve_regression(
            parent: Exercise,
            ref_raw: str,
            ref_video: Optional[str],
            label: str,
            row_num: int,
            is_isometric: bool,
        ) -> Optional[Exercise]:
            if not ref_raw or _slugify_token(ref_raw) in EMPTY_REF_SENTINELS:
                return None

            target = by_code.get(ref_raw.upper()) or by_name.get(ref_raw.strip().lower())
            if target is None and create_missing_regressions:
                # Crear stub para no perder la referencia cuando la regresión no tenía fila propia
                looks_like_code = bool(re.match(r'^[A-Za-z0-9_-]{2,25}$', ref_raw) and '_' in ref_raw)
                stub = Exercise.objects.create(
                    code=ref_raw if looks_like_code else None,
                    name=ref_raw,
                    category=parent.category,
                    movement_pattern=parent.movement_pattern,
                    sport_tags=['mma'],
                    video_url=ref_video,
                    session_block=parent.session_block,
                    patron_vector=parent.patron_vector if is_isometric else '',
                    lock_route='Libre',
                    complexity_level='Nivel_0_Novato' if is_isometric else parent.complexity_level,
                    isa_tag='Universal',
                    contractile_regime='Isopush' if is_isometric else 'Dinamico_Estandar',
                    compromised_joint='Ninguna',
                    created_by=trainer_profile,
                )
                ExerciseDisciplineFit.objects.update_or_create(
                    exercise=stub, sport='mma', defaults={'fit': 5}
                )
                if stub.code:
                    by_code[stub.code.upper()] = stub
                by_name[stub.name.strip().lower()] = stub
                result.auto_created_stubs += 1
                target = stub

            if target is None:
                msg = (
                    f"Fila {row_num} ({parent.code}): Referencia {label} '{ref_raw}' "
                    "no encontrada en el catálogo."
                )
                if strict:
                    raise AMCatalogImportError(msg)
                result.warnings.append(msg)
                return None

            if target.pk == parent.pk:
                msg = f"Fila {row_num} ({parent.code}): {label} no puede apuntar al mismo ejercicio."
                if strict:
                    raise AMCatalogImportError(msg)
                result.warnings.append(msg)
                return None

            if ref_video and not target.video_url:
                target.video_url = ref_video
                target.save(update_fields=['video_url', 'updated_at'])

            return target

        for row_num, exercise, opt_a_ref, opt_a_video, opt_b_ref, opt_b_video in pending_regressions:
            target_a = _resolve_regression(
                exercise, opt_a_ref, opt_a_video, 'ID_Opcion_A_Isometrica', row_num, is_isometric=True
            )
            target_b = _resolve_regression(
                exercise, opt_b_ref, opt_b_video, 'ID_Opcion_B_Vector', row_num, is_isometric=False
            )

            changed = False
            if exercise.regression_option_a_id != (target_a.pk if target_a else None):
                exercise.regression_option_a = target_a
                changed = True
            if exercise.option_a_video_url != opt_a_video:
                exercise.option_a_video_url = opt_a_video
                changed = True
            if exercise.regression_option_b_id != (target_b.pk if target_b else None):
                exercise.regression_option_b = target_b
                changed = True
            if exercise.option_b_video_url != opt_b_video:
                exercise.option_b_video_url = opt_b_video
                changed = True

            if target_a is not None:
                result.linked_option_a_count += 1
            if target_b is not None:
                result.linked_option_b_count += 1

            if changed:
                exercise.save(update_fields=[
                    'regression_option_a', 'option_a_video_url',
                    'regression_option_b', 'option_b_video_url',
                    'updated_at',
                ])

        if dry_run:
            transaction.set_rollback(True)

    return result


def generate_am_csv_template(output_path: Path | str, include_examples: bool = True) -> Path:
    """
    Genera un archivo CSV UTF-8 con las 15 columnas exactas de `BD_Maestra_Ejercicios`
    y ejemplos realistas del Sistema AM listos para validar o entregar al entrenador.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=AM_OFFICIAL_HEADERS)
        writer.writeheader()
        if include_examples:
            for sample in AM_SAMPLE_ROWS:
                writer.writerow(sample)
    return target
