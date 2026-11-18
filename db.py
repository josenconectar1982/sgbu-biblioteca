"""Base de datos del SGBU (SQLite) y datos de demostración.

En Render (plan gratuito) el disco es efímero: la base se crea y se llena
con datos de ejemplo cada vez que el servicio arranca.
"""
import os, random, sqlite3
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("SGBU_DB", os.path.join(os.path.dirname(__file__), "sgbu.db"))
COL = timezone(timedelta(hours=-5))  # Colombia, UTC-5 sin horario de verano
FMT = "%Y-%m-%d %H:%M"


def ahora():
    return datetime.now(COL).replace(tzinfo=None, second=0, microsecond=0)


def conectar():
    con = sqlite3.connect(DB_PATH, detect_types=0, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


ESQUEMA = """
CREATE TABLE usuarios(
  id INTEGER PRIMARY KEY, documento TEXT UNIQUE NOT NULL, nombres TEXT NOT NULL, apellidos TEXT NOT NULL,
  correo TEXT UNIQUE NOT NULL, telefono TEXT, codigo TEXT, tipo TEXT NOT NULL, programa TEXT,
  estado TEXT NOT NULL DEFAULT 'ACTIVO', pass_hash TEXT NOT NULL, intentos INTEGER DEFAULT 0,
  bloqueado_hasta TEXT, creado TEXT);
CREATE TABLE politicas(
  tipo_lector TEXT PRIMARY KEY, max_ejemplares INTEGER, dias_prestamo INTEGER, max_renovaciones INTEGER,
  max_reservas INTEGER, dias_sancion_por_dia INTEGER, dias_aviso INTEGER);
CREATE TABLE categorias(id INTEGER PRIMARY KEY, nombre TEXT UNIQUE);
CREATE TABLE autores(id INTEGER PRIMARY KEY, nombre TEXT, nacionalidad TEXT);
CREATE TABLE libros(
  id INTEGER PRIMARY KEY, isbn TEXT UNIQUE, titulo TEXT, editorial TEXT, anio INTEGER, edicion TEXT,
  idioma TEXT, categoria_id INTEGER REFERENCES categorias(id), palabras TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE libro_autor(libro_id INTEGER REFERENCES libros(id), autor_id INTEGER REFERENCES autores(id));
CREATE TABLE ejemplares(
  id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, libro_id INTEGER REFERENCES libros(id), ubicacion TEXT,
  estado TEXT, circulacion TEXT, fecha_ingreso TEXT, observacion TEXT);
CREATE TABLE prestamos(
  id INTEGER PRIMARY KEY, ejemplar_id INTEGER REFERENCES ejemplares(id), lector_id INTEGER REFERENCES usuarios(id),
  bibliotecario_id INTEGER REFERENCES usuarios(id), fecha_prestamo TEXT, fecha_vencimiento TEXT,
  fecha_devolucion TEXT, renovaciones INTEGER DEFAULT 0, estado TEXT, recibido_por INTEGER);
CREATE TABLE reservas(
  id INTEGER PRIMARY KEY, libro_id INTEGER REFERENCES libros(id), lector_id INTEGER REFERENCES usuarios(id),
  fecha TEXT, fecha_disponible TEXT, fecha_expiracion TEXT, estado TEXT, ejemplar_id INTEGER);
CREATE TABLE sanciones(
  id INTEGER PRIMARY KEY, lector_id INTEGER REFERENCES usuarios(id), prestamo_id INTEGER, fecha_inicio TEXT,
  fecha_fin TEXT, dias INTEGER, motivo TEXT, estado TEXT, justificacion TEXT);
CREATE TABLE notificaciones(
  id INTEGER PRIMARY KEY, lector_id INTEGER REFERENCES usuarios(id), tipo TEXT, asunto TEXT, mensaje TEXT,
  fecha TEXT, estado_envio TEXT);
CREATE TABLE auditoria(
  id INTEGER PRIMARY KEY, fecha TEXT, usuario_id INTEGER, accion TEXT, entidad TEXT, detalle TEXT, ip TEXT);
CREATE TABLE festivos(fecha TEXT PRIMARY KEY, nombre TEXT);
"""

CATEGORIAS = ["Ingeniería de software", "Programación", "Bases de datos", "Redes y telecomunicaciones",
              "Inteligencia artificial", "Matemáticas", "Física", "Administración", "Contabilidad y finanzas",
              "Literatura", "Referencia"]

# (titulo, autores, editorial, año, edición, categoría, nº ejemplares, circulación)
LIBROS = [
    ("Ingeniería del software: un enfoque práctico", ["Roger S. Pressman"], "McGraw-Hill", 2010, "7.ª", 0, 2, "GENERAL"),
    ("Ingeniería de software", ["Ian Sommerville"], "Pearson", 2011, "9.ª", 0, 3, "GENERAL"),
    ("UML gota a gota", ["Martin Fowler"], "Addison-Wesley", 1999, "1.ª", 0, 1, "SOLO_SALA"),
    ("El proceso unificado de desarrollo de software", ["Ivar Jacobson", "Grady Booch", "James Rumbaugh"], "Addison-Wesley", 2000, "1.ª", 0, 2, "GENERAL"),
    ("Código limpio", ["Robert C. Martin"], "Anaya Multimedia", 2012, "1.ª", 1, 3, "GENERAL"),
    ("Patrones de diseño", ["Erich Gamma", "Richard Helm"], "Addison-Wesley", 2003, "1.ª", 0, 2, "RESTRINGIDO"),
    ("Cómo programar en Java", ["Paul Deitel", "Harvey Deitel"], "Pearson", 2016, "10.ª", 1, 4, "GENERAL"),
    ("Python para todos", ["Raúl González Duque"], "Autoedición", 2018, "2.ª", 1, 2, "GENERAL"),
    ("Estructuras de datos y algoritmos", ["Alfred V. Aho", "John E. Hopcroft"], "Addison-Wesley", 1988, "1.ª", 1, 2, "GENERAL"),
    ("Introducción a los algoritmos", ["Thomas H. Cormen"], "MIT Press", 2009, "3.ª", 1, 1, "RESTRINGIDO"),
    ("Fundamentos de bases de datos", ["Abraham Silberschatz", "Henry F. Korth"], "McGraw-Hill", 2014, "6.ª", 2, 3, "GENERAL"),
    ("Sistemas de bases de datos", ["Ramez Elmasri", "Shamkant Navathe"], "Pearson", 2007, "5.ª", 2, 2, "GENERAL"),
    ("Redes de computadoras", ["Andrew S. Tanenbaum"], "Pearson", 2012, "5.ª", 3, 3, "GENERAL"),
    ("Redes de computadoras: un enfoque descendente", ["James F. Kurose", "Keith W. Ross"], "Pearson", 2017, "7.ª", 3, 2, "GENERAL"),
    ("Inteligencia artificial: un enfoque moderno", ["Stuart Russell", "Peter Norvig"], "Pearson", 2004, "2.ª", 4, 2, "RESTRINGIDO"),
    ("Aprendizaje automático", ["Tom M. Mitchell"], "McGraw-Hill", 1997, "1.ª", 4, 1, "GENERAL"),
    ("Cálculo de una variable", ["James Stewart"], "Cengage", 2012, "7.ª", 5, 4, "GENERAL"),
    ("Álgebra lineal y sus aplicaciones", ["David C. Lay"], "Pearson", 2012, "4.ª", 5, 3, "GENERAL"),
    ("Matemáticas discretas", ["Kenneth H. Rosen"], "McGraw-Hill", 2004, "5.ª", 5, 2, "GENERAL"),
    ("Probabilidad y estadística para ingeniería", ["Ronald E. Walpole"], "Pearson", 2012, "9.ª", 5, 2, "GENERAL"),
    ("Física universitaria", ["Hugh D. Young", "Roger A. Freedman"], "Pearson", 2013, "13.ª", 6, 3, "GENERAL"),
    ("Física para ciencias e ingeniería", ["Raymond A. Serway"], "Cengage", 2008, "7.ª", 6, 2, "GENERAL"),
    ("Administración", ["Stephen P. Robbins", "Mary Coulter"], "Pearson", 2014, "12.ª", 7, 2, "GENERAL"),
    ("Administración estratégica", ["Fred R. David"], "Pearson", 2013, "14.ª", 7, 1, "GENERAL"),
    ("Contabilidad financiera", ["Charles T. Horngren"], "Pearson", 2010, "9.ª", 8, 2, "GENERAL"),
    ("Cien años de soledad", ["Gabriel García Márquez"], "Sudamericana", 1967, "1.ª", 9, 3, "GENERAL"),
    ("María", ["Jorge Isaacs"], "Norma", 1867, "Ed. conmemorativa", 9, 2, "GENERAL"),
    ("El amor en los tiempos del cólera", ["Gabriel García Márquez"], "Oveja Negra", 1985, "1.ª", 9, 1, "GENERAL"),
    ("Diccionario de la lengua española", ["Real Academia Española"], "Espasa", 2014, "23.ª", 10, 2, "SOLO_SALA"),
    ("Manual de normas APA", ["American Psychological Association"], "APA", 2020, "7.ª", 10, 1, "SOLO_SALA"),
]

NOMBRES = ["Andrés", "Valentina", "Santiago", "Camila", "Juan David", "Mariana", "Sebastián", "Daniela", "Felipe",
           "Isabella", "Nicolás", "Sofía", "Mateo", "Juliana", "Alejandro", "Paula", "Esteban", "Natalia", "Diego",
           "Luisa", "Cristian", "Manuela", "Kevin", "Angie"]
APELLIDOS = ["Mejía", "Ramírez", "Torres", "Castillo", "Rojas", "Muñoz", "Cardona", "Ospina", "Valencia", "Moreno",
             "Arango", "Rentería", "Mosquera", "Caicedo", "Hurtado", "Quintero", "Rivas", "Zapata", "Salazar", "Lozada"]
PROGRAMAS = ["Ingeniería de Sistemas", "Ingeniería Industrial", "Ingeniería Electrónica", "Administración de Empresas",
             "Contaduría Pública", "Tecnología en Desarrollo de Software", "Diseño Visual"]

FESTIVOS_2026 = [("2026-01-01", "Año Nuevo"), ("2026-01-12", "Reyes Magos"), ("2026-03-23", "San José"),
                 ("2026-04-02", "Jueves Santo"), ("2026-04-03", "Viernes Santo"), ("2026-05-01", "Día del Trabajo"),
                 ("2026-05-18", "Ascensión"), ("2026-06-08", "Corpus Christi"), ("2026-06-15", "Sagrado Corazón"),
                 ("2026-06-29", "San Pedro y San Pablo"), ("2026-07-20", "Independencia"), ("2026-08-07", "Batalla de Boyacá"),
                 ("2026-08-17", "Asunción"), ("2026-10-12", "Día de la Raza"), ("2026-11-02", "Todos los Santos"),
                 ("2026-11-16", "Independencia de Cartagena"), ("2026-12-08", "Inmaculada Concepción"), ("2026-12-25", "Navidad"),
                 ("2027-01-01", "Año Nuevo"), ("2027-01-11", "Reyes Magos")]


def f(dt):
    return dt.strftime(FMT)


def crear_y_sembrar(forzar=False):
    if os.path.exists(DB_PATH):
        if not forzar:
            return
        os.remove(DB_PATH)
    con = conectar()
    con.executescript(ESQUEMA)
    rnd = random.Random(2026)
    now = ahora()
    hoy = now.replace(hour=0, minute=0)

    con.executemany("INSERT INTO festivos VALUES(?,?)", FESTIVOS_2026)
    con.executemany("INSERT INTO politicas VALUES(?,?,?,?,?,?,?)", [
        ("ESTUDIANTE", 3, 8, 1, 2, 1, 2), ("DOCENTE", 5, 15, 2, 3, 1, 2), ("ADMINISTRATIVO", 3, 8, 1, 2, 1, 2)])
    for c in CATEGORIAS:
        con.execute("INSERT INTO categorias(nombre) VALUES(?)", (c,))

    # ---------------- usuarios
    def usuario(doc, nom, ape, correo, tipo, clave, programa=None, codigo=None, tel=None):
        cur = con.execute(
            "INSERT INTO usuarios(documento,nombres,apellidos,correo,telefono,codigo,tipo,programa,pass_hash,creado) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (doc, nom, ape, correo, tel or "31%08d" % rnd.randint(0, 99999999), codigo, tipo, programa,
             generate_password_hash(clave, method="pbkdf2:sha256", salt_length=8), f(now - timedelta(days=200))))
        return cur.lastrowid

    admin = usuario("31987654", "Patricia", "Ocampo Lenis", "admin@uniajc.edu.co", "ADMINISTRADOR", "Admin123", "Dirección de Biblioteca", "ADM-001")
    marta = usuario("66845123", "Marta", "Lozano Vélez", "marta.lozano@uniajc.edu.co", "BIBLIOTECARIO", "Biblio123", "Circulación", "BIB-007")
    jorge = usuario("16789432", "Jorge", "Paz Cuero", "jorge.paz@uniajc.edu.co", "BIBLIOTECARIO", "Biblio123", "Circulación", "BIB-011")
    laura = usuario("1107845123", "Laura", "Gómez Ríos", "laura.gomez@estudiante.uniajc.edu.co", "ESTUDIANTE", "Lector123", "Ingeniería de Sistemas", "2231045")
    carlos = usuario("94512378", "Carlos", "Ruiz Mena", "carlos.ruiz@uniajc.edu.co", "DOCENTE", "Lector123", "Facultad de Ingeniería", "DOC-2051")
    andres = usuario("1144201876", "Andrés", "Mejía Cano", "andres.mejia@estudiante.uniajc.edu.co", "ESTUDIANTE", "Lector123", "Ingeniería Industrial", "2219876")
    lectores = [laura, carlos, andres]
    usados = set()
    for i in range(30):
        while True:
            n, a1, a2 = rnd.choice(NOMBRES), rnd.choice(APELLIDOS), rnd.choice(APELLIDOS)
            if (n, a1) not in usados:
                usados.add((n, a1)); break
        tipo = rnd.choices(["ESTUDIANTE", "DOCENTE", "ADMINISTRATIVO"], [70, 18, 12])[0]
        base = (n.split()[0] + "." + a1).lower().translate(str.maketrans("áéíóúñ", "aeioun"))
        dom = "estudiante.uniajc.edu.co" if tipo == "ESTUDIANTE" else "uniajc.edu.co"
        prog = rnd.choice(PROGRAMAS) if tipo == "ESTUDIANTE" else ("Facultad de " + rnd.choice(["Ingeniería", "Ciencias Empresariales", "Educación"]) if tipo == "DOCENTE" else rnd.choice(["Registro Académico", "Bienestar Universitario", "Tesorería"]))
        cod = ("22%05d" % rnd.randint(0, 99999)) if tipo == "ESTUDIANTE" else ("DOC-%04d" % rnd.randint(1000, 9999) if tipo == "DOCENTE" else "ADM-%03d" % rnd.randint(100, 999))
        lectores.append(usuario(str(rnd.randint(1000000000, 1199999999)), n, a1 + " " + a2, base + "%d@%s" % (i, dom), tipo, "Lector123", prog, cod))

    # ---------------- libros y ejemplares
    autor_ids = {}
    ejemplares_por_libro = {}
    for li, (tit, auts, edit, anio, ed, cat, n, circ) in enumerate(LIBROS, start=1):
        isbn = "978-%d-%02d-%06d-%d" % (rnd.randint(84, 99), rnd.randint(10, 99), rnd.randint(0, 999999), rnd.randint(0, 9))
        con.execute("INSERT INTO libros(id,isbn,titulo,editorial,anio,edicion,idioma,categoria_id,palabras) VALUES(?,?,?,?,?,?,?,?,?)",
                    (li, isbn, tit, edit, anio, ed, "Español", cat + 1, CATEGORIAS[cat].lower()))
        for a in auts:
            if a not in autor_ids:
                autor_ids[a] = con.execute("INSERT INTO autores(nombre,nacionalidad) VALUES(?,?)", (a, "")).lastrowid
            con.execute("INSERT INTO libro_autor VALUES(?,?)", (li, autor_ids[a]))
        ejemplares_por_libro[li] = []
        for k in range(1, n + 1):
            est = f"Estante {cat + 1}{'ABCD'[k % 4]}" if circ != "SOLO_SALA" else "Sala de referencia"
            eid = con.execute("INSERT INTO ejemplares(codigo,libro_id,ubicacion,estado,circulacion,fecha_ingreso) VALUES(?,?,?,?,?,?)",
                              ("BUGP-%03d-%02d" % (li, k), li, est, "DISPONIBLE", circ, f(now - timedelta(days=rnd.randint(300, 1500))))).lastrowid
            ejemplares_por_libro[li].append(eid)

    # ---------------- historial de préstamos (devueltos) para reportes
    popular = {1: 9, 2: 8, 5: 7, 7: 7, 11: 6, 17: 9, 18: 5, 13: 5, 26: 6, 21: 5}
    ocupado = {}  # ejemplar -> fecha hasta la que está ocupado
    bib = [marta, jorge]
    pid = 0
    for li in range(1, len(LIBROS) + 1):
        if LIBROS[li - 1][7] == "SOLO_SALA":
            continue
        veces = popular.get(li, rnd.randint(0, 3))
        for _ in range(veces):
            e = rnd.choice(ejemplares_por_libro[li])
            ini = hoy - timedelta(days=rnd.randint(25, 150), hours=-rnd.randint(8, 17))
            dias = 8
            venc = (ini + timedelta(days=dias)).replace(hour=18, minute=0)
            dev = venc - timedelta(days=rnd.randint(0, 5), hours=rnd.randint(0, 5))
            if rnd.random() < 0.15:
                dev = venc + timedelta(days=rnd.randint(1, 4))
            lec = rnd.choice(lectores[3:])
            pid = con.execute("INSERT INTO prestamos(ejemplar_id,lector_id,bibliotecario_id,fecha_prestamo,fecha_vencimiento,fecha_devolucion,estado,recibido_por) VALUES(?,?,?,?,?,?,?,?)",
                              (e, lec, rnd.choice(bib), f(ini), f(venc), f(dev), "DEVUELTO", rnd.choice(bib))).lastrowid
            if dev > venc:
                d = (dev - venc).days + (1 if (dev - venc).seconds else 0)
                fi = dev.replace(hour=0, minute=0)
                con.execute("INSERT INTO sanciones(lector_id,prestamo_id,fecha_inicio,fecha_fin,dias,motivo,estado) VALUES(?,?,?,?,?,?,?)",
                            (lec, pid, f(fi)[:10], f(fi + timedelta(days=d - 1))[:10], d, "Devolución tardía del préstamo P-%d" % pid, "CUMPLIDA"))

    def prestar(e, lec, ini, venc, estado="ACTIVO", renov=0):
        con.execute("UPDATE ejemplares SET estado='PRESTADO' WHERE id=?", (e,))
        return con.execute("INSERT INTO prestamos(ejemplar_id,lector_id,bibliotecario_id,fecha_prestamo,fecha_vencimiento,renovaciones,estado) VALUES(?,?,?,?,?,?,?)",
                           (e, lec, rnd.choice(bib), f(ini), f(venc), renov, estado)).lastrowid

    def notif(lec, tipo, asunto, msg, fecha):
        con.execute("INSERT INTO notificaciones(lector_id,tipo,asunto,mensaje,fecha,estado_envio) VALUES(?,?,?,?,?,?)",
                    (lec, tipo, asunto, msg, f(fecha), "ENVIADA"))

    # ---------------- escenario del diagrama de objetos (Apéndice F)
    e1, e2 = ejemplares_por_libro[1]
    ini1 = (hoy - timedelta(days=16)).replace(hour=9, minute=15)
    p5760 = prestar(e1, laura, ini1, (ini1 + timedelta(days=8)).replace(hour=18, minute=0), "VENCIDO")
    notif(laura, "PRESTAMO_VENCIDO", "Préstamo vencido: Ingeniería del software",
          "Su préstamo del ejemplar BUGP-001-01 venció. Por favor devuélvalo cuanto antes para evitar más días de sanción.",
          (hoy - timedelta(days=7)).replace(hour=7))
    ini2 = (hoy - timedelta(days=13)).replace(hour=10)
    venc2 = (ini2 + timedelta(days=8)).replace(hour=18)
    dev2 = (hoy - timedelta(days=2)).replace(hour=11, minute=20)
    p5791 = con.execute("INSERT INTO prestamos(ejemplar_id,lector_id,bibliotecario_id,fecha_prestamo,fecha_vencimiento,fecha_devolucion,estado,recibido_por) VALUES(?,?,?,?,?,?,?,?)",
                        (e2, laura, marta, f(ini2), f(venc2), f(dev2), "DEVUELTO", marta)).lastrowid
    dsan = (dev2 - venc2).days + 1
    con.execute("INSERT INTO sanciones(lector_id,prestamo_id,fecha_inicio,fecha_fin,dias,motivo,estado) VALUES(?,?,?,?,?,?,?)",
                (laura, p5791, f(hoy - timedelta(days=2))[:10], f(hoy - timedelta(days=2) + timedelta(days=dsan - 1))[:10], dsan,
                 "Devolución tardía del préstamo P-%d" % p5791, "ACTIVA"))
    notif(laura, "SANCION_GENERADA", "Sanción generada", "Se generó una sanción por devolución tardía del préstamo P-%d." % p5791, dev2)
    con.execute("UPDATE ejemplares SET estado='RESERVADO' WHERE id=?", (e2,))
    con.execute("INSERT INTO reservas(libro_id,lector_id,fecha,fecha_disponible,fecha_expiracion,estado,ejemplar_id) VALUES(?,?,?,?,?,?,?)",
                (1, carlos, f(hoy - timedelta(days=6, hours=-14)), f(dev2 + timedelta(minutes=1)), f((now + timedelta(days=1)).replace(hour=18, minute=0)), "DISPONIBLE", e2))
    notif(carlos, "RESERVA_DISPONIBLE", "Su reserva está disponible",
          "El libro «Ingeniería del software: un enfoque práctico» está disponible para retirar (ejemplar BUGP-001-02).", dev2 + timedelta(minutes=1))

    # ---------------- préstamos activos y algunas reservas en cola
    activos = [(2, 0), (2, 1), (2, 2), (5, 0), (7, 0), (7, 1), (11, 0), (13, 0), (17, 0), (17, 1), (21, 0), (26, 0), (26, 1), (18, 0), (12, 0)]
    for li, k in activos:
        e = ejemplares_por_libro[li][k]
        lec = rnd.choice(lectores[3:])
        ini = (hoy - timedelta(days=rnd.randint(1, 7))).replace(hour=rnd.randint(8, 17))
        venc = (ini + timedelta(days=8)).replace(hour=18, minute=0)
        prestar(e, lec, ini, venc)
    # vencidos adicionales
    for li, k in [(9, 0), (22, 0), (14, 0)]:
        e = ejemplares_por_libro[li][k]
        lec = rnd.choice(lectores[3:])
        ini = (hoy - timedelta(days=rnd.randint(12, 20))).replace(hour=10)
        p = prestar(e, lec, ini, (ini + timedelta(days=8)).replace(hour=18), "VENCIDO")
    # préstamo de Andrés por vencer (para mostrar el recordatorio y la renovación)
    e = ejemplares_por_libro[4][0]
    ini = (hoy - timedelta(days=6)).replace(hour=15)
    prestar(e, andres, ini, (hoy + timedelta(days=2)).replace(hour=18))
    notif(andres, "COMPROBANTE_PRESTAMO", "Comprobante de préstamo", "Préstamo registrado del ejemplar BUGP-004-01. Vence el %s." % (hoy + timedelta(days=2)).strftime("%d/%m/%Y 18:00"), ini)
    # cola de reservas para Sommerville (todos prestados): 3 lectores -> aparece en sugerencias de compra
    for j, lec in enumerate(rnd.sample(lectores[3:], 3)):
        con.execute("INSERT INTO reservas(libro_id,lector_id,fecha,estado) VALUES(?,?,?,?)",
                    (2, lec, f(hoy - timedelta(days=4 - j, hours=-9)), "PENDIENTE"))
    # ejemplar perdido y en reparación
    con.execute("UPDATE ejemplares SET estado='PERDIDO' WHERE id=?", (ejemplares_por_libro[17][3],))
    con.execute("UPDATE ejemplares SET estado='EN_REPARACION', observacion='Lomo despegado' WHERE id=?", (ejemplares_por_libro[13][2],))

    # ---------------- auditoría inicial
    for k, (acc, ent, det) in enumerate([
            ("IMPORTAR", "Libro", "Importación inicial de 30 libros desde catalogo_2025.xlsx"),
            ("IMPORTAR", "Usuario", "Importación inicial de 36 usuarios desde usuarios.csv"),
            ("CONFIGURAR", "PoliticaPrestamo", "Parámetros iniciales por tipo de lector (Tabla 1)"),
            ("INICIO_SESION", "Usuario", "Ingreso de marta.lozano@uniajc.edu.co")]):
        con.execute("INSERT INTO auditoria(fecha,usuario_id,accion,entidad,detalle,ip) VALUES(?,?,?,?,?,?)",
                    (f(now - timedelta(days=30 - k)), admin if k < 3 else marta, acc, ent, det, "10.20.1.%d" % (10 + k)))
    con.commit()
    con.close()


if __name__ == "__main__":
    crear_y_sembrar(forzar=True)
    print("Base creada en", DB_PATH)
