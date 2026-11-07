# Rework Station

Panel PyQt5 para cuatro estaciones de soldadura en MinnowBoard.

## Estructura

- `REWORK.py`: entrada, opciones de ejecucion y bloqueo de instancia.
- `ui.py`: menu Sistemas/Historial, identidad, temporizadores e incidencias.
- `storage.py`: consulta de operadores y persistencia SQLite, sin dependencia de Qt.
- `test_rework.py`: pruebas de datos y flujo de interfaz.

## Ejecutar en Windows

Se ha preparado `.venv` con Python 3.14 y PyQt5 en este equipo.

```powershell
.\.venv\Scripts\python.exe REWORK.py --demo --windowed
```

WWID de demostracion: `12251003` (Operador de prueba),
`100001` (Ana Garcia) y `100002` (Luis Perez).
La demostracion utiliza `rework_demo.db`, separada de la base normal.

Sin `--windowed`, la interfaz abre a pantalla completa. Sin `--demo`, no se
crean usuarios de prueba y se utiliza `rework.db` junto al codigo.
`--database RUTA` permite seleccionar otra base; el directorio debe existir
y permitir escritura. No use `--demo` con una base de usuarios reales.

Para reinstalar dependencias en un entorno compatible:

```powershell
.\.venv\Scripts\python.exe -m pip install --proxy http://proxy-dmz.intel.com:928 -r requirements.txt
```

En la MinnowBoard, use Python 3.9 o posterior y una distribucion compatible
con Qt5; si no hay ruedas pip para su plataforma, necesitara PyQt5 de su
distribucion. Hardware y renderizado Linux aun no se han probado.

## Base de usuarios

La tabla `operators` contiene `wwid` (texto, clave primaria), `name` y
`active` (1 permitido, 0 inactivo). Los ceros iniciales del WWID se conservan.
La busqueda es exacta y elimina espacios de los extremos.
No se permite iniciar con un WWID desconocido o inactivo.

Puede cargar usuarios desde un script de administracion o un editor SQLite.
Ejemplo Python con parametros, ejecutado desde la carpeta del proyecto:

```python
from storage import DEFAULT_DATABASE, StationStore

store = StationStore(DEFAULT_DATABASE)
with store.connection:
    store.connection.execute(
        "INSERT INTO operators (wwid, name, active) VALUES (?, ?, ?) "
        "ON CONFLICT(wwid) DO UPDATE SET name = excluded.name, active = excluded.active",
        ("009876", "Nombre del operador", 1),
    )
store.close()
```

Solo personal autorizado debe poder editar la base. No hay menu publico de
alta de usuarios. Para una base corporativa futura, sustituya la consulta en
`StationStore.lookup_operator` y la revalidacion al registrar la sesion.

## Flujo y registro

Activar sistema -> introducir/leer WWID -> validar nombre -> elegir duracion
-> confirmar. Cancelar no crea registros ni activa sesiones. Cambiar WWID
invalida la consulta anterior. La base revalida al iniciar.

`sessions` guarda estacion, WWID, copia del nombre, inicio UTC, minutos,
fin UTC y motivo de cierre. El historial muestra las ultimas 200 sesiones
en hora local; todos los registros permanecen en la base. `reports` guarda
las incidencias. Los archivos de texto antiguos no se importan ni se borran.

El cierre puede ser manual, por tiempo, por salida o por interrupcion.
Tras una interrupcion, se marca el cierre al reiniciar: esa fecha es la de
recuperacion, no la hora exacta del corte. No se reactivan sesiones antiguas.
Si falla guardar un cierre, la estacion queda bloqueada hasta reintentarlo.
Solo una instancia puede usar cada archivo de base de datos.

## Lector y hardware pendientes

Un lector de barras USB tipo teclado puede escribir el WWID en el campo y
enviar Enter para validarlo; la activacion sigue requiriendo confirmacion.
`IdentityDialog.receive_identifier(identifier)` es la entrada prevista para
un adaptador NFC: debe invocarse mediante una senal Qt en el hilo de GUI.
Si el lector devuelve un UID distinto del WWID, sera necesaria una tabla
de correspondencias y validacion de credenciales.

**Introducir un WWID no es autenticacion fuerte**: cualquiera que conozca
uno activo puede introducirlo. La integracion real debera verificar la
credencial, permisos por sistema y politica de acceso.

**Los GPIO NO estan conectados**, como en la version original. Esta version
gestiona sesiones y registros, no energiza equipos. Antes de conectar reles,
se necesita un controlador especifico para los pines de la MinnowBoard,
apagado seguro ante excepciones/cortes y un paro fisico independiente de la
interfaz. La base local tampoco es un registro de auditoria inalterable.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_rework
```

Las pruebas usan bases temporales/en memoria; no modifican usuarios reales.# Rework-Power-Control
