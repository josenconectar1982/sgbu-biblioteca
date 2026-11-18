# SGBU – Sistema de Gestión de Biblioteca Universitaria

Prototipo funcional del proyecto final de **Ingeniería de Software (UNIAJC)** para la
**Biblioteca Universitaria Gustavo Francisco Petro Urrego**. Implementa los requisitos del
documento SRS (IEEE 830): catálogo con disponibilidad en tiempo real, préstamos, devoluciones,
renovaciones, reservas en cola, sanciones automáticas, recordatorios por correo (simulados),
trazabilidad, reportes, políticas configurables, auditoría e importación desde CSV.

## Usuarios de demostración

| Rol | Correo | Contraseña |
|---|---|---|
| Estudiante habilitado | andres.mejia@estudiante.uniajc.edu.co | Lector123 |
| Estudiante sancionada | laura.gomez@estudiante.uniajc.edu.co | Lector123 |
| Docente | carlos.ruiz@uniajc.edu.co | Lector123 |
| Bibliotecaria | marta.lozano@uniajc.edu.co | Biblio123 |
| Administradora | admin@uniajc.edu.co | Admin123 |

La pantalla de inicio de sesión tiene botones de acceso rápido para cada rol.

## Ejecutar localmente

```bash
pip install -r requirements.txt
python app.py          # http://localhost:5000
```

## Despliegue en Render

El archivo `render.yaml` define un *Web Service* de Python (plan gratuito):
`pip install -r requirements.txt` y `gunicorn app:app`. La base SQLite se crea y se llena con
datos de ejemplo al arrancar; en el plan gratuito el disco es efímero, así que los datos vuelven
al estado inicial en cada reinicio (también se pueden restablecer desde *Políticas → Restablecer*).

## Estructura (según el diagrama de paquetes)

- `app.py` – presentación y controladores (rutas por rol, control de acceso RBAC).
- `servicios.py` – lógica de negocio (préstamo, devolución, sanción, reservas, renovación, proceso diario).
- `db.py` – persistencia SQLite, esquema y datos de demostración.
- `templates/`, `static/` – interfaz web responsive.
