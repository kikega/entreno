---
name: exercise-guide
description: >-
  Genera guías técnicas, biomecánicas y anatómicas de ejercicios de fuerza y entrenamiento en formato Markdown estructurado de 5 puntos (Nombre y objetivo, Anatomía muscular, Ejecución técnica paso a paso, Errores más comunes y cómo evitarlos, Claves de seguridad y variantes). Activar cuando el usuario solicite la descripción, técnica, músculos o errores de un ejercicio para copiar o introducir manualmente en el catálogo de ejercicios de EntrenoPro.
---

# Generador de Guías Técnicas de Ejercicios (EntrenoPro)

Esta habilidad permite al asistente generar guías técnicas y biomecánicas de ejercicios de entrenamiento con un formato Markdown riguroso, pedagógico, claro y conciso, optimizado para que los atletas comprendan la ejecución, los músculos participantes y los errores frecuentes directamente en la plataforma.

El contenido generado está preparado para que el usuario pueda copiarlo y pegarlo directamente en el campo **Descripción y Guía Técnica (Markdown)** del formulario de ejercicios de la aplicación.

---

## Estructura Estricta de 5 Puntos

Siempre que el usuario pida la descripción o guía técnica de uno o varios ejercicios, se debe generar exactamente el siguiente formato con encabezados de nivel 3 (`###`):

```markdown
### 1. Nombre y objetivo
- **Nombre:** [Nombre oficial del ejercicio y variantes comunes]
- **Categoría y patrón:** [Categoría: Fuerza / Potencia / Movilidad / Velocidad / etc.] · [Patrón biomecánico: Empuje horizontal / vertical, Tracción horizontal / vertical, Dominante de cadera / rodilla, Potencia olímpica, Metabólico, Isometría agarre, Core rotacional, etc.]
- **Objetivo principal:** [Propósito neuromuscular, biomecánico y de rendimiento físico: ej. fuerza máxima, hipertrofia de cadena posterior, potencia explosiva, estabilidad lumbopélvica, etc.]

### 2. Anatomía muscular
- **Músculos principales (agonistas):** [Músculos primarios que generan la mayor fuerza motriz]
- **Músculos secundarios (sinergistas):** [Músculos que colaboran y asisten en el movimiento articular]
- **Estabilizadores clave:** [Músculos que fijan la postura, escápulas, faja abdominal o alineación articular]

### 3. Ejecución técnica paso a paso
- **Posición inicial (setup):** [Colocación precisa de pies, manos, agarre, postura espinal y tensión previa]
- **Fase excéntrica (bajada/control):** [Trayectoria y control de la carga o del peso corporal, ángulos de flexión]
- **Fase concéntrica (subida/empuje):** [Punto de inflexión, aceleración, aplicación de fuerza y bloqueo articular seguro]
- **Respiración y tempo:** [Patrón respiratorio (maniobra de Valsalva si procede) y cadencia sugerida, ej. 3-1-1-0]

### 4. Errores más comunes y cómo evitarlos
- **[Error 1]:** [Explicación del riesgo lesivo o pérdida de tensión mecánica]. Corrección: *[Cue técnico o indicación motriz clara]*.
- **[Error 2]:** [Explicación]. Corrección: *[Cue técnico o indicación motriz clara]*.
- **[Error 3]:** [Explicación]. Corrección: *[Cue técnico o indicación motriz clara]*.

### 5. Claves de seguridad y variantes
- **Seguridad articular:** [Precauciones clave para articulaciones comprometidas (hombro, columna lumbar, rodillas, etc.)]
- **Cues verbales clave:** [1-2 frases mentales o sensaciones internas concisas para el atleta durante la serie (ej. "Atornilla los pies al suelo", "Lleva los codos a los bolsillos")]
- **Regresión:** [Variante adaptada para principiantes, falta de movilidad o molestias articulares]
- **Progresión:** [Variante avanzada para incrementar el estímulo, intensidad o sobrecarga progresiva]
```

---

## Pautas de Redacción

1. **Directo y sin rodeos:** Iniciar el bloque Markdown directamente en `### 1. Nombre y objetivo`. No añadir títulos de nivel 1 (`#`) ni prefacios redundantes.
2. **Formato amigable para el atleta:** Utilizar viñetas con términos en negrita (`- **Músculos principales:** ...`) para que la lectura sea inmediata en la interfaz móvil o de escritorio.
3. **Terminología precisa:** Emplear terminología anatómica rigurosa (ej. pectoral mayor porción clavicular/esternal, deltoides anterior, erectores espinales, transverso abdominal, manguito rotador).
4. **Cues motrices aplicables:** Las correcciones deben proporcionar sensaciones internas o indicaciones motrices prácticas (cues como "rompe la barra", "empuja el suelo separándolo", "pecho orgulloso").
5. **Listo para copiar:** Entregar el texto dentro de un bloque de código Markdown para facilitar que el usuario lo copie con un solo clic y lo pegue en el formulario de la aplicación.
