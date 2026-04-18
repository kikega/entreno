# Especificaciones del proyecto

## Objetivo

El objetivo es crear una aplicacion para la gestión de entrenamientos de deportistas profesionales, con las siguientes caracteristicas principales:

- La aplicación será multiusuario (entrenadores y deportistas), un usuario puede ser entrenador y llevar la planificación de entreno de varios deportistas y puede ser entrenador y deportista, que planificará y ejecutará su propio entrenamiento
- El perfil entrenador, dispondrá de un dashboard donde podrá planificar ejercicios y evaluar los entrenamientos realizados por los deportistas asignados o el suyo propio en caso de ser también deportista. 
- El perfil deportista, tendrá un dashboard para ver la evolución de los entrenos donde se incluiran los datos relativos a la ejecución de cada ejercicio en la planificación deportiva asignada
- - En el perfil del deportista tendrá valores morfologicos como peso, altura etc que ayudaran a realizar la planificación y seguimiento del plan de entrenamiento
- Los datos de la planificación deportiva realizados por el entrenador, serán individuales y no podrán ser vistos entre los usuarios de la aplicación, sólo un entrenador, podrá ver la planificación de todos sus deportistas asignados
- Los usuarios de daran de alta en la aplicación, donde su correo electrónico será el login de la aplicación. 
- El usuario que se defina como deportista, se encargará de asignarse un entrenador de los disponibles, cuando esto ocurra, el entrenador recibirá un correo con la información y podrá confiormar esa asignación. A partir de ese momento, ya podrá gestionar y planificar los entrenos de ese deportista 
- El entrenador se encargará de definir los ejercicios y sus caracteristicas, que quedaran reflejados en una tabla, ejercicio. En esta, se deifnira el ejercicio a realizar y la categoria a la que pertenece, que puede ser: fuerza, potencia, movilidad, velocidad, pliometria, tecnica, tactica, etc.
- Cada ejercicio, tendrá variables como Número de series, Repeticiones por serie, Carga, RPE, RIR Tempo, Foco, Descanso, Indicaciones, Enlace a video de ejemplo, etc.
- La aplicación podrá evaluar el rendimiento de cada deportista en un período de tiempo y mediante herramientas de ML, encontrar patrones y llegar a conclusiones que permitan ajustar los entrenos para alcanzar los objetivos previstos
- Si el deportista dispone de elementos que miden valores durante el ejercicio realizado, como  Calorias consumidas, duración del entreno, frecuencia cardiaca, etc, se pondran como datos globales en el entreno
- Los dahboard, incluiran gráficas con la relación de ejercicio realizado, rendimiento global, relación con el peso, etc.
- Para la identificación y login en el sistema, se utilizará el correo electrónico

## Procedimiento

- El entrenador define y configura los ejercicios y las pautas de los mismos para cada deportista
- El deportista seguira el plan realizado e introducira los datos relativos a cada ejercicio en cada entreno, podrá seguir la evolucion en su dashboard
- El entrenador marcará objetivos a alcanzar en un plazo determinado de tiempo
- Los datos relativoa al deportista los introducira el miso deportista

## Interfaz

- La interfaz tendrá 2 enfoques, el principal, será un dashboard para el entrenador y el usuario, donde se verá un enfoque general del usuario, con graficas de seguimiento, el plan de entrenamiento que se deberá seguir, donde se podran ver los ejercicios a realizar en un dia determinado y un botón para marcar el entrenamiento como completado.
- La parte del deportista será una vista mas detallada del entrenamiento realizado, donde se incluirán los datos de cada ejercicio realizado, como número de series, repeticiones por serie, carga, RPE, RIR Tempo, Foco, Descanso, Indicaciones, Enlace a video de ejemplo, etc. y un botón para marcar el entrenamiento como completado. Se priorizará la vista desde un teléfono movil
- Para la realización de la interfaz de la aplicación, se usará la aplicación stich, html, tailwind, htmx y javascript. Será una interfaz moderna, limpia y responsive, con un diseño limpio y profesional.

## Stack tecnológico

- Frontend: HTML, CSS, Taillwind, Htmx, JavaScript
- Backend: Django >= 6 para desarrollo y 4 para producción
- Distintos requerimientos para desarrollo y producción
- Libreria utilizada en el entorno virtual para desarrollo uv y venv para produccion
- Librerias de gráficos: Chart.js
- Base de datos: Postgresql, tanto en desarrollo como en producción
- En producción se utilizará el stack linux (AlmaLinux 9), Nginx y Gunicorn

## Seguridad

- La aplicacion debe tener una autenticacion de usuario y contraseña
- La aplicacion debe tener una sesion de usuario y contraseña
- El usuario se debe autenticar usando su correo electrónico, para lo que habrá que extender el modelo de usuario de django para que tenga un correo electronico y una contraseña.
- Se deberar primar la seguridad de el sitio controlando en los formularios la entrada  de datos, para lo que se debera validar que los datos introducidos sean correctos y que no se introduzcan datos no validos.
- Se debera implementar un sistema de autenticacion que permita al usuario acceder a su cuenta y que le permita gestionar sus datos.
- Utiliza un archivo .env para guardar las variables de entorno, 

## Escenario

- El entorno virtual ya está creado y se ha hecho con uv
- Instala las librerias necesarias para el desarrollo de la aplicación, se priorizará el uso de uv. Los datos como claves de api, contraseñas etc, se guardaran en el archivo .env
- La base de datos erá PostgreSQL, que se encuentra en un servidor local con una ip 192.168.122.100, usuario kike y contraseña 8kururunfa
- Actualiza .gitignore para que no se suban los archivos .env y .venv
- Crea el proyecto django y los modelos necesarios según especificaciones, una vez creados realiza los migraciones para crear las tablas en la base de datos