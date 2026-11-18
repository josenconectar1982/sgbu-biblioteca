"""SGBU – Sistema de Gestión de Biblioteca Universitaria
Biblioteca Universitaria Gustavo Francisco Petro Urrego · Proyecto de Ingeniería de Software (UNIAJC)
"""
import csv, io, os
from datetime import timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for, session, flash, g, Response, abort)
from werkzeug.security import check_password_hash, generate_password_hash
import db
from db import ahora, conectar
import servicios as sv
from servicios import ReglaNegocio, p, f

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "sgbu-demo-clave-local")
app.permanent_session_lifetime = timedelta(minutes=30)  # RNF04

db.crear_y_sembrar()

LECTORES = sv.TIPOS_LECTOR
PERSONAL = ("BIBLIOTECARIO", "ADMINISTRADOR")


# ------------------------------------------------------------------ infraestructura
@app.before_request
def antes():
    g.con = conectar()
    sv.refrescar_estados(g.con)
    g.user = None
    if "uid" in session:
        g.user = g.con.execute("SELECT * FROM usuarios WHERE id=?", (session["uid"],)).fetchone()
        session.permanent = True


@app.teardown_request
def despues(exc):
    con = g.pop("con", None)
    if con:
        con.close()


def ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def rol(*tipos):
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            if not g.user:
                return redirect(url_for("login", next=request.path))
            permitidos = set()
            for t in tipos:
                permitidos |= set(LECTORES) if t == "LECTOR" else {t}
            if g.user["tipo"] not in permitidos:
                abort(403)
            return fn(*a, **k)
        return w
    return deco


@app.template_filter("fecha")
def _fecha(s, hora=True):
    if not s:
        return "—"
    d = p(s) if isinstance(s, str) else s
    return d.strftime("%d/%m/%Y %H:%M" if hora and (len(s) > 10 if isinstance(s, str) else True) else "%d/%m/%Y")


@app.template_filter("dia")
def _dia(s):
    return _fecha(s, False)


@app.context_processor
def contexto():
    u = g.get("user")
    nnoti = 0
    if u and u["tipo"] in LECTORES:
        nnoti = g.con.execute("SELECT COUNT(*) FROM notificaciones WHERE lector_id=? AND fecha>=?", (u["id"], f(ahora() - timedelta(days=7)))).fetchone()[0]
    return dict(usuario=u, es_lector=bool(u and u["tipo"] in LECTORES), es_personal=bool(u and u["tipo"] in PERSONAL),
                es_admin=bool(u and u["tipo"] == "ADMINISTRADOR"), ahora=ahora(), nnoti=nnoti)


@app.errorhandler(403)
def prohibido(e):
    return render_template("error.html", codigo=403, msg="No tiene permisos para acceder a esta opción (control de acceso por rol, RNF04)."), 403


@app.errorhandler(404)
def no_encontrado(e):
    return render_template("error.html", codigo=404, msg="La página que busca no existe."), 404


def autores_de(libro_id):
    return ", ".join(r["nombre"] for r in g.con.execute("SELECT a.nombre FROM autores a JOIN libro_autor la ON la.autor_id=a.id WHERE la.libro_id=?", (libro_id,)))


# ------------------------------------------------------------------ RF01 autenticación
DEMO = [("ESTUDIANTE", "Andrés Mejía", "andres.mejia@estudiante.uniajc.edu.co", "Lector123", "Estudiante habilitado"),
        ("ESTUDIANTE", "Laura Gómez", "laura.gomez@estudiante.uniajc.edu.co", "Lector123", "Con sanción y préstamo vencido"),
        ("DOCENTE", "Carlos Ruiz", "carlos.ruiz@uniajc.edu.co", "Lector123", "Docente con reserva disponible"),
        ("BIBLIOTECARIO", "Marta Lozano", "marta.lozano@uniajc.edu.co", "Biblio123", "Mostrador de circulación"),
        ("ADMINISTRADOR", "Patricia Ocampo", "admin@uniajc.edu.co", "Admin123", "Políticas, auditoría y reportes")]


@app.route("/", methods=["GET"])
def inicio():
    if not g.user:
        return redirect(url_for("login"))
    return redirect(url_for("panel") if g.user["tipo"] in PERSONAL else url_for("catalogo"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        clave = request.form.get("clave", "")
        u = g.con.execute("SELECT * FROM usuarios WHERE lower(correo)=?", (correo,)).fetchone()
        now = ahora()
        if u and u["bloqueado_hasta"] and p(u["bloqueado_hasta"]) > now:
            flash("Cuenta bloqueada por intentos fallidos hasta las %s." % p(u["bloqueado_hasta"]).strftime("%H:%M"), "error")
        elif u and u["estado"] == "ACTIVO" and check_password_hash(u["pass_hash"], clave):
            g.con.execute("UPDATE usuarios SET intentos=0, bloqueado_hasta=NULL WHERE id=?", (u["id"],))
            sv.auditar(g.con, u["id"], "INICIO_SESION", "Usuario", "Ingreso de " + u["correo"], ip())
            g.con.commit()
            session.clear()
            session["uid"] = u["id"]
            return redirect(request.args.get("next") or url_for("inicio"))
        else:
            if u:
                intentos = (u["intentos"] or 0) + 1
                bloq = f(now + timedelta(minutes=15)) if intentos >= 5 else None
                g.con.execute("UPDATE usuarios SET intentos=?, bloqueado_hasta=? WHERE id=?", (0 if bloq else intentos, bloq, u["id"]))
                sv.auditar(g.con, u["id"], "ACCESO_FALLIDO", "Usuario", "Intento fallido %d de 5" % intentos, ip())
                g.con.commit()
                flash("Correo o contraseña incorrectos." + (" La cuenta quedó bloqueada 15 minutos." if bloq else " Intento %d de 5." % intentos), "error")
            else:
                flash("Correo o contraseña incorrectos.", "error")
    return render_template("login.html", demo=DEMO)


@app.route("/salir")
def salir():
    session.clear()
    flash("Sesión cerrada correctamente.", "ok")
    return redirect(url_for("login"))


# ------------------------------------------------------------------ RF05 catálogo
def disponibilidad(libro_id):
    ejs = g.con.execute("SELECT * FROM ejemplares WHERE libro_id=? AND estado NOT IN ('PERDIDO','DADO_DE_BAJA')", (libro_id,)).fetchall()
    disp = sum(1 for e in ejs if e["estado"] == "DISPONIBLE")
    circs = {e["circulacion"] for e in ejs}
    if disp:
        est = ("Solo sala", "amber") if circs == {"SOLO_SALA"} else ("Disponible", "green")
    elif any(e["estado"] == "RESERVADO" for e in ejs):
        est = ("Reservado", "amber")
    else:
        est = ("Prestado", "red")
    return dict(total=len(ejs), disponibles=disp, estado=est, ejemplares=ejs)


@app.route("/catalogo")
def catalogo():
    if not g.user:
        return redirect(url_for("login"))
    q = request.args.get("q", "").strip()
    cat = request.args.get("cat", "")
    solo = request.args.get("disp", "")
    sql = """SELECT l.*, c.nombre AS categoria FROM libros l JOIN categorias c ON c.id=l.categoria_id WHERE l.activo=1"""
    args = []
    if q:
        sql += """ AND (l.titulo LIKE ? OR l.isbn LIKE ? OR l.palabras LIKE ? OR l.id IN
                 (SELECT la.libro_id FROM libro_autor la JOIN autores a ON a.id=la.autor_id WHERE a.nombre LIKE ?))"""
        args += ["%" + q + "%"] * 4
    if cat:
        sql += " AND c.id=?"; args.append(cat)
    libros = []
    for l in g.con.execute(sql + " ORDER BY l.titulo", args).fetchall():
        d = disponibilidad(l["id"])
        if solo and not d["disponibles"]:
            continue
        cola = g.con.execute("SELECT COUNT(*) FROM reservas WHERE libro_id=? AND estado='PENDIENTE'", (l["id"],)).fetchone()[0]
        libros.append(dict(l=l, autores=autores_de(l["id"]), d=d, cola=cola))
    cats = g.con.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    return render_template("catalogo.html", libros=libros, q=q, cats=cats, cat=cat, solo=solo)


@app.route("/libro/<int:lid>", methods=["GET", "POST"])
def libro(lid):
    if not g.user:
        return redirect(url_for("login"))
    l = g.con.execute("SELECT l.*, c.nombre AS categoria FROM libros l JOIN categorias c ON c.id=l.categoria_id WHERE l.id=?", (lid,)).fetchone()
    if not l:
        abort(404)
    if request.method == "POST" and g.user["tipo"] in LECTORES:
        try:
            pos = sv.reservar(g.con, g.user, lid)
            flash("Reserva registrada. Su posición en la cola es %d; le avisaremos por correo cuando el ejemplar esté disponible." % pos, "ok")
        except ReglaNegocio as e:
            flash(str(e), "error")
        return redirect(url_for("libro", lid=lid))
    d = disponibilidad(lid)
    filas = []
    for e in g.con.execute("SELECT * FROM ejemplares WHERE libro_id=? ORDER BY codigo", (lid,)).fetchall():
        pr = g.con.execute("SELECT * FROM prestamos WHERE ejemplar_id=? AND estado IN ('ACTIVO','VENCIDO')", (e["id"],)).fetchone()
        filas.append(dict(e=e, vence=pr["fecha_vencimiento"] if pr else None))
    cola = g.con.execute("SELECT COUNT(*) FROM reservas WHERE libro_id=? AND estado='PENDIENTE'", (lid,)).fetchone()[0]
    mia = None
    if g.user["tipo"] in LECTORES:
        mia = g.con.execute("SELECT * FROM reservas WHERE libro_id=? AND lector_id=? AND estado IN ('PENDIENTE','DISPONIBLE')", (lid, g.user["id"])).fetchone()
    puede_reservar = d["disponibles"] == 0 and any(x["e"]["circulacion"] != "SOLO_SALA" for x in filas)
    return render_template("libro.html", l=l, autores=autores_de(lid), d=d, filas=filas, cola=cola, mia=mia, puede_reservar=puede_reservar)


# ------------------------------------------------------------------ RF14 mi cuenta, RF08 renovar, RF10 cancelar
@app.route("/cuenta")
@rol("LECTOR")
def cuenta():
    u = g.user
    st = sv.estado_lector(g.con, u)
    prestamos = g.con.execute("""SELECT pr.*, e.codigo, e.circulacion, l.titulo, l.id AS libro_id FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id
                                 JOIN libros l ON l.id=e.libro_id WHERE pr.lector_id=? AND pr.estado IN ('ACTIVO','VENCIDO') ORDER BY pr.fecha_vencimiento""", (u["id"],)).fetchall()
    reservas = []
    for r in g.con.execute("SELECT r.*, l.titulo FROM reservas r JOIN libros l ON l.id=r.libro_id WHERE r.lector_id=? AND r.estado IN ('PENDIENTE','DISPONIBLE') ORDER BY r.fecha", (u["id"],)).fetchall():
        reservas.append(dict(r=r, pos=sv.posicion_reserva(g.con, r)))
    sanciones = g.con.execute("SELECT * FROM sanciones WHERE lector_id=? ORDER BY fecha_inicio DESC", (u["id"],)).fetchall()
    historial = g.con.execute("""SELECT pr.*, e.codigo, l.titulo FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id JOIN libros l ON l.id=e.libro_id
                                 WHERE pr.lector_id=? AND pr.estado='DEVUELTO' ORDER BY pr.fecha_devolucion DESC LIMIT 10""", (u["id"],)).fetchall()
    now = ahora()
    por_vencer = {pr["id"]: (p(pr["fecha_vencimiento"]) - now).days < 3 for pr in prestamos}
    return render_template("cuenta.html", st=st, prestamos=prestamos, reservas=reservas, sanciones=sanciones, historial=historial, por_vencer=por_vencer)


@app.route("/renovar/<int:pid>", methods=["POST"])
@rol("LECTOR", "BIBLIOTECARIO", "ADMINISTRADOR")
def renovar(pid):
    pr = g.con.execute("SELECT * FROM prestamos WHERE id=?", (pid,)).fetchone()
    if not pr or (g.user["tipo"] in LECTORES and pr["lector_id"] != g.user["id"]):
        abort(403)
    try:
        venc = sv.renovar(g.con, pid, g.user["id"])
        flash("Préstamo renovado. Nueva fecha de vencimiento: %s." % venc.strftime("%d/%m/%Y %H:%M"), "ok")
    except ReglaNegocio as e:
        flash("No se pudo renovar: " + str(e), "error")
    return redirect(request.form.get("volver") or url_for("cuenta"))


@app.route("/reserva/<int:rid>/cancelar", methods=["POST"])
@rol("LECTOR")
def cancelar_reserva(rid):
    r = g.con.execute("SELECT * FROM reservas WHERE id=?", (rid,)).fetchone()
    if not r or r["lector_id"] != g.user["id"]:
        abort(403)
    try:
        sv.cancelar_reserva(g.con, rid, g.user["id"])
        flash("Reserva cancelada; la cola se recalculó automáticamente.", "ok")
    except ReglaNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("cuenta"))


@app.route("/notificaciones")
@rol("LECTOR", "BIBLIOTECARIO", "ADMINISTRADOR")
def notificaciones():
    if g.user["tipo"] in LECTORES:
        rows = g.con.execute("SELECT n.*, u.correo FROM notificaciones n JOIN usuarios u ON u.id=n.lector_id WHERE lector_id=? ORDER BY n.fecha DESC, n.id DESC", (g.user["id"],)).fetchall()
    else:
        rows = g.con.execute("SELECT n.*, u.correo FROM notificaciones n JOIN usuarios u ON u.id=n.lector_id ORDER BY n.fecha DESC, n.id DESC LIMIT 150").fetchall()
    return render_template("notificaciones.html", rows=rows)


# ------------------------------------------------------------------ panel del personal
@app.route("/panel")
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def panel():
    c = g.con
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    kpi = dict(
        libros=q("SELECT COUNT(*) FROM libros WHERE activo=1"),
        ejemplares=q("SELECT COUNT(*) FROM ejemplares WHERE estado NOT IN ('PERDIDO','DADO_DE_BAJA')"),
        prestados=q("SELECT COUNT(*) FROM prestamos WHERE estado IN ('ACTIVO','VENCIDO')"),
        vencidos=q("SELECT COUNT(*) FROM prestamos WHERE estado='VENCIDO'"),
        reservas=q("SELECT COUNT(*) FROM reservas WHERE estado IN ('PENDIENTE','DISPONIBLE')"),
        sanciones=q("SELECT COUNT(*) FROM sanciones WHERE estado='ACTIVA'"),
        lectores=q("SELECT COUNT(*) FROM usuarios WHERE tipo IN ('ESTUDIANTE','DOCENTE','ADMINISTRATIVO')"),
        hoy_prest=q("SELECT COUNT(*) FROM prestamos WHERE substr(fecha_prestamo,1,10)=?", ahora().strftime("%Y-%m-%d")),
    )
    estados = c.execute("SELECT estado, COUNT(*) n FROM ejemplares GROUP BY estado ORDER BY n DESC").fetchall()
    semanas = []
    base = ahora().replace(hour=0, minute=0)
    for k in range(7, -1, -1):
        a = base - timedelta(days=base.weekday() + 7 * k)
        b = a + timedelta(days=7)
        semanas.append((a.strftime("%d/%m"), q("SELECT COUNT(*) FROM prestamos WHERE fecha_prestamo>=? AND fecha_prestamo<?", f(a), f(b))))
    vencen = c.execute("""SELECT pr.*, e.codigo, l.titulo, u.nombres||' '||u.apellidos AS lector FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id
                          JOIN libros l ON l.id=e.libro_id JOIN usuarios u ON u.id=pr.lector_id WHERE pr.estado IN ('ACTIVO','VENCIDO')
                          ORDER BY pr.fecha_vencimiento LIMIT 7""").fetchall()
    actividad = c.execute("SELECT a.*, u.nombres||' '||u.apellidos AS quien FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id ORDER BY a.id DESC LIMIT 7").fetchall()
    return render_template("panel.html", kpi=kpi, estados=estados, semanas=semanas, vencen=vencen, actividad=actividad)


# ------------------------------------------------------------------ RF06/07/08 mostrador
def buscar_lector(txt):
    txt = (txt or "").strip()
    return g.con.execute("SELECT * FROM usuarios WHERE (codigo=? OR documento=? OR lower(correo)=lower(?)) AND tipo IN ('ESTUDIANTE','DOCENTE','ADMINISTRATIVO')", (txt, txt, txt)).fetchone()


@app.route("/mostrador", methods=["GET", "POST"])
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def mostrador():
    tab = request.args.get("tab", "prestamo")
    carro = session.get("carro", {"lector": None, "items": []})
    ctx = dict(tab=tab)
    accion = request.form.get("accion")
    if request.method == "POST":
        try:
            if accion == "lector":
                lec = buscar_lector(request.form.get("carne"))
                if not lec:
                    raise ReglaNegocio("No se encontró un lector con ese carné, documento o correo.")
                carro = {"lector": lec["id"], "items": []}
            elif accion == "agregar":
                lec = g.con.execute("SELECT * FROM usuarios WHERE id=?", (carro["lector"],)).fetchone()
                cod = request.form.get("codigo", "").strip().upper()
                ej = g.con.execute("SELECT * FROM ejemplares WHERE codigo=?", (cod,)).fetchone()
                if not ej:
                    raise ReglaNegocio("No existe el ejemplar %s." % cod)
                if cod in carro["items"]:
                    raise ReglaNegocio("El ejemplar ya está en la lista.")
                st = sv.verificar_habilitacion(g.con, lec)
                if st["activos"] + len(carro["items"]) + 1 > st["politica"]["max_ejemplares"]:
                    raise ReglaNegocio("Cupo agotado: máximo %d ejemplares para %s." % (st["politica"]["max_ejemplares"], lec["tipo"].lower()))
                sv.validar_ejemplar(g.con, ej, lec)
                carro["items"].append(cod)
            elif accion == "quitar":
                carro["items"] = [c for c in carro["items"] if c != request.form.get("codigo")]
            elif accion == "confirmar":
                lec = g.con.execute("SELECT * FROM usuarios WHERE id=?", (carro["lector"],)).fetchone()
                res = sv.registrar_prestamo(g.con, lec, carro["items"], g.user["id"])
                session["comprobante"] = dict(lector=lec["nombres"] + " " + lec["apellidos"], correo=lec["correo"],
                                              items=[dict(codigo=r["codigo"], titulo=r["titulo"], vence=r["vence"].strftime("%d/%m/%Y %H:%M"), id=r["id"]) for r in res])
                carro = {"lector": None, "items": []}
            elif accion == "nuevo":
                carro = {"lector": None, "items": []}
                session.pop("comprobante", None)
            elif accion == "ver_devolucion":
                return redirect(url_for("mostrador", tab="devolucion", codigo=request.form.get("codigo", "").strip().upper()))
            elif accion == "devolver":
                r = sv.registrar_devolucion(g.con, request.form["codigo"], g.user["id"], request.form.get("fisico") == "deteriorado", request.form.get("obs", ""))
                msg = "Devolución registrada: el ejemplar quedó %s." % r["estado_ejemplar"]
                if r["sancion"]:
                    msg += " Se generó una sanción de %d día(s) hasta el %s." % (r["sancion"]["dias"], r["sancion"]["fin"].strftime("%d/%m/%Y"))
                if r["reserva"]:
                    msg += " Reservado para %s (notificado por correo)." % r["reserva"]
                flash(msg, "ok")
                return redirect(url_for("mostrador", tab="devolucion"))
            elif accion == "buscar_renovar":
                return redirect(url_for("mostrador", tab="renovacion", carne=request.form.get("carne", "")))
        except ReglaNegocio as e:
            flash(str(e), "error")
            if tab == "devolucion":
                return redirect(url_for("mostrador", tab="devolucion"))
        session["carro"] = carro
        return redirect(url_for("mostrador", tab=tab))

    if tab == "prestamo":
        lec = g.con.execute("SELECT * FROM usuarios WHERE id=?", (carro["lector"],)).fetchone() if carro.get("lector") else None
        items = []
        if lec:
            for cod in carro["items"]:
                e = g.con.execute("SELECT e.*, l.titulo FROM ejemplares e JOIN libros l ON l.id=e.libro_id WHERE codigo=?", (cod,)).fetchone()
                items.append(dict(e=e, vence=sv.calcular_vencimiento(g.con, e, lec)))
        ctx.update(lector=lec, st=sv.estado_lector(g.con, lec) if lec else None, items=items, comprobante=session.pop("comprobante", None))
    elif tab == "devolucion":
        cod = request.args.get("codigo", "").strip().upper()
        prev = None
        if cod:
            ej = g.con.execute("SELECT e.*, l.titulo, l.id AS lid FROM ejemplares e JOIN libros l ON l.id=e.libro_id WHERE codigo=?", (cod,)).fetchone()
            pr = g.con.execute("SELECT * FROM prestamos WHERE ejemplar_id=? AND estado IN ('ACTIVO','VENCIDO')", (ej["id"],)).fetchone() if ej else None
            if not ej or not pr:
                flash("El ejemplar %s no existe o no tiene un préstamo activo." % cod, "error")
            else:
                lec = g.con.execute("SELECT * FROM usuarios WHERE id=?", (pr["lector_id"],)).fetchone()
                venc = p(pr["fecha_vencimiento"]); now = ahora()
                retraso = None
                if now > venc:
                    import math
                    if ej["circulacion"] == "RESTRINGIDO":
                        retraso = ("%d hora(s)" % math.ceil((now - venc).total_seconds() / 3600), math.ceil((now - venc).total_seconds() / 3600))
                    else:
                        dd = math.ceil((now - venc).total_seconds() / 86400)
                        retraso = ("%d día(s)" % dd, dd * sv.politica(g.con, lec["tipo"])["dias_sancion_por_dia"])
                cola = g.con.execute("SELECT u.nombres||' '||u.apellidos AS n FROM reservas r JOIN usuarios u ON u.id=r.lector_id WHERE r.libro_id=? AND r.estado='PENDIENTE' ORDER BY r.fecha LIMIT 1", (ej["lid"],)).fetchone()
                prev = dict(ej=ej, pr=pr, lec=lec, retraso=retraso, cola=cola["n"] if cola else None)
        recientes = g.con.execute("""SELECT pr.*, e.codigo, l.titulo, u.nombres||' '||u.apellidos AS lector FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id
                                     JOIN libros l ON l.id=e.libro_id JOIN usuarios u ON u.id=pr.lector_id WHERE pr.estado IN ('ACTIVO','VENCIDO') ORDER BY pr.fecha_vencimiento LIMIT 8""").fetchall()
        ctx.update(prev=prev, recientes=recientes)
    else:
        lec = buscar_lector(request.args.get("carne")) if request.args.get("carne") else None
        if request.args.get("carne") and not lec:
            flash("No se encontró el lector.", "error")
        prs = g.con.execute("""SELECT pr.*, e.codigo, e.circulacion, l.titulo FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id JOIN libros l ON l.id=e.libro_id
                               WHERE pr.lector_id=? AND pr.estado IN ('ACTIVO','VENCIDO')""", (lec["id"],)).fetchall() if lec else []
        ctx.update(lector=lec, prs=prs, carne=request.args.get("carne", ""))
    return render_template("mostrador.html", **ctx)


# ------------------------------------------------------------------ RF02 usuarios
@app.route("/usuarios", methods=["GET", "POST"])
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def usuarios():
    if request.method == "POST":
        fm = request.form
        try:
            if fm.get("accion") == "estado":
                u = g.con.execute("SELECT * FROM usuarios WHERE id=?", (fm["id"],)).fetchone()
                nuevo = "INACTIVO" if u["estado"] == "ACTIVO" else "ACTIVO"
                if nuevo == "INACTIVO" and g.con.execute("SELECT 1 FROM prestamos WHERE lector_id=? AND estado IN ('ACTIVO','VENCIDO')", (u["id"],)).fetchone():
                    raise ReglaNegocio("No se puede inactivar: el usuario tiene préstamos activos.")
                g.con.execute("UPDATE usuarios SET estado=? WHERE id=?", (nuevo, u["id"]))
                sv.auditar(g.con, g.user["id"], "MODIFICAR", "Usuario", "%s → %s" % (u["correo"], nuevo), ip())
                g.con.commit()
                flash("Usuario %s quedó %s." % (u["correo"], nuevo), "ok")
            else:
                correo = fm["correo"].strip().lower()
                if not correo.endswith("uniajc.edu.co"):
                    raise ReglaNegocio("El correo debe pertenecer al dominio institucional (uniajc.edu.co).")
                if g.con.execute("SELECT 1 FROM usuarios WHERE documento=? OR lower(correo)=?", (fm["documento"].strip(), correo)).fetchone():
                    raise ReglaNegocio("Ya existe un usuario con ese documento o correo.")
                if fm["tipo"] == "ADMINISTRADOR" and g.user["tipo"] != "ADMINISTRADOR":
                    raise ReglaNegocio("Solo el administrador puede crear administradores.")
                g.con.execute("INSERT INTO usuarios(documento,nombres,apellidos,correo,telefono,codigo,tipo,programa,pass_hash,creado) VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (fm["documento"].strip(), fm["nombres"].strip(), fm["apellidos"].strip(), correo, fm.get("telefono"), fm.get("codigo"),
                               fm["tipo"], fm.get("programa"), generate_password_hash("Lector123", method="pbkdf2:sha256", salt_length=8), f(ahora())))
                sv.auditar(g.con, g.user["id"], "CREAR", "Usuario", correo, ip())
                g.con.commit()
                flash("Usuario registrado. Contraseña inicial: Lector123.", "ok")
        except ReglaNegocio as e:
            flash(str(e), "error")
        return redirect(url_for("usuarios", q=request.args.get("q", "")))
    q = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "")
    sql = "SELECT * FROM usuarios WHERE 1=1"
    args = []
    if q:
        sql += " AND (nombres||' '||apellidos LIKE ? OR correo LIKE ? OR documento LIKE ? OR codigo LIKE ?)"; args += ["%" + q + "%"] * 4
    if tipo:
        sql += " AND tipo=?"; args.append(tipo)
    rows = []
    for u in g.con.execute(sql + " ORDER BY tipo, apellidos", args).fetchall():
        st = sv.estado_lector(g.con, u) if u["tipo"] in LECTORES else None
        rows.append(dict(u=u, st=st))
    return render_template("usuarios.html", rows=rows, q=q, tipo=tipo)


# ------------------------------------------------------------------ RF03/RF04 libros y ejemplares
@app.route("/libros", methods=["GET", "POST"])
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def libros():
    if request.method == "POST":
        fm = request.form
        try:
            if fm.get("accion") == "ejemplar":
                lid = int(fm["libro_id"])
                n = g.con.execute("SELECT COUNT(*) FROM ejemplares WHERE libro_id=?", (lid,)).fetchone()[0] + 1
                cod = "BUGP-%03d-%02d" % (lid, n)
                g.con.execute("INSERT INTO ejemplares(codigo,libro_id,ubicacion,estado,circulacion,fecha_ingreso) VALUES(?,?,?,?,?,?)",
                              (cod, lid, fm.get("ubicacion") or "Estante", "DISPONIBLE", fm["circulacion"], f(ahora())))
                sv.auditar(g.con, g.user["id"], "CREAR", "Ejemplar", cod, ip())
                g.con.commit()
                flash("Ejemplar %s registrado (%s)." % (cod, fm["circulacion"]), "ok")
                return redirect(url_for("libro", lid=lid))
            if fm.get("accion") == "estado_ejemplar":
                e = g.con.execute("SELECT * FROM ejemplares WHERE id=?", (fm["id"],)).fetchone()
                if e["estado"] in ("PRESTADO", "RESERVADO"):
                    raise ReglaNegocio("No se puede cambiar el estado de un ejemplar prestado o reservado.")
                g.con.execute("UPDATE ejemplares SET estado=? WHERE id=?", (fm["estado"], e["id"]))
                sv.auditar(g.con, g.user["id"], "CAMBIO_ESTADO", "Ejemplar", "%s: %s → %s" % (e["codigo"], e["estado"], fm["estado"]), ip())
                g.con.commit()
                flash("Estado del ejemplar %s actualizado a %s." % (e["codigo"], fm["estado"]), "ok")
                return redirect(url_for("libro", lid=e["libro_id"]))
            isbn = fm["isbn"].replace("-", "").replace(" ", "")
            if not (isbn.isdigit() and len(isbn) in (10, 13)):
                raise ReglaNegocio("El ISBN debe tener 10 o 13 dígitos.")
            if g.con.execute("SELECT 1 FROM libros WHERE replace(isbn,'-','')=?", (isbn,)).fetchone():
                raise ReglaNegocio("Ya existe un libro con ese ISBN.")
            lid = g.con.execute("INSERT INTO libros(isbn,titulo,editorial,anio,edicion,idioma,categoria_id,palabras) VALUES(?,?,?,?,?,?,?,?)",
                                (fm["isbn"], fm["titulo"], fm["editorial"], fm.get("anio") or None, fm.get("edicion"), fm.get("idioma") or "Español", fm["categoria"], fm.get("palabras", ""))).lastrowid
            for a in [x.strip() for x in fm["autores"].split(",") if x.strip()]:
                r = g.con.execute("SELECT id FROM autores WHERE nombre=?", (a,)).fetchone()
                aid = r["id"] if r else g.con.execute("INSERT INTO autores(nombre) VALUES(?)", (a,)).lastrowid
                g.con.execute("INSERT INTO libro_autor VALUES(?,?)", (lid, aid))
            sv.auditar(g.con, g.user["id"], "CREAR", "Libro", fm["titulo"], ip())
            g.con.commit()
            flash("Libro registrado. Ahora agregue sus ejemplares.", "ok")
            return redirect(url_for("libro", lid=lid))
        except ReglaNegocio as e:
            flash(str(e), "error")
        return redirect(url_for("libros"))
    cats = g.con.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    rows = []
    for l in g.con.execute("SELECT l.*, c.nombre AS categoria FROM libros l JOIN categorias c ON c.id=l.categoria_id ORDER BY l.titulo").fetchall():
        rows.append(dict(l=l, autores=autores_de(l["id"]), d=disponibilidad(l["id"])))
    return render_template("libros.html", rows=rows, cats=cats)


# ------------------------------------------------------------------ RF11/RF12 sanciones
@app.route("/sanciones", methods=["GET", "POST"])
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def sanciones():
    if request.method == "POST":
        if g.user["tipo"] != "ADMINISTRADOR":
            abort(403)
        try:
            sv.anular_sancion(g.con, int(request.form["id"]), request.form.get("justificacion"), g.user["id"])
            flash("Sanción anulada y registrada en la bitácora.", "ok")
        except ReglaNegocio as e:
            flash(str(e), "error")
        return redirect(url_for("sanciones"))
    est = request.args.get("estado", "ACTIVA")
    rows = g.con.execute("""SELECT s.*, u.nombres||' '||u.apellidos AS lector, u.tipo, u.correo FROM sanciones s JOIN usuarios u ON u.id=s.lector_id
                            WHERE (?='' OR s.estado=?) ORDER BY s.fecha_inicio DESC""", (est, est)).fetchall()
    return render_template("sanciones.html", rows=rows, est=est)


# ------------------------------------------------------------------ RF15 trazabilidad
@app.route("/trazabilidad")
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def trazabilidad():
    q = request.args.get("q", "").strip()
    ej = lec = None
    movs = []
    if q:
        ej = g.con.execute("SELECT e.*, l.titulo FROM ejemplares e JOIN libros l ON l.id=e.libro_id WHERE e.codigo=?", (q.upper(),)).fetchone()
        if ej:
            movs = g.con.execute("""SELECT pr.*, u.nombres||' '||u.apellidos AS lector, u.codigo AS carne, b.nombres AS bib, r.nombres AS rec
                                    FROM prestamos pr JOIN usuarios u ON u.id=pr.lector_id LEFT JOIN usuarios b ON b.id=pr.bibliotecario_id
                                    LEFT JOIN usuarios r ON r.id=pr.recibido_por WHERE pr.ejemplar_id=? ORDER BY pr.fecha_prestamo DESC""", (ej["id"],)).fetchall()
        else:
            lec = buscar_lector(q)
            if lec:
                movs = g.con.execute("""SELECT pr.*, e.codigo, l.titulo, b.nombres AS bib, r.nombres AS rec FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id
                                        JOIN libros l ON l.id=e.libro_id LEFT JOIN usuarios b ON b.id=pr.bibliotecario_id LEFT JOIN usuarios r ON r.id=pr.recibido_por
                                        WHERE pr.lector_id=? ORDER BY pr.fecha_prestamo DESC""", (lec["id"],)).fetchall()
            else:
                flash("No se encontró un ejemplar ni un lector con «%s»." % q, "error")
    actual = None
    if ej:
        actual = next((m for m in movs if m["estado"] in ("ACTIVO", "VENCIDO")), None)
    return render_template("trazabilidad.html", q=q, ej=ej, lec=lec, movs=movs, actual=actual)


# ------------------------------------------------------------------ RF16-18 reportes
def datos_reporte(tipo, desde, hasta):
    c = g.con
    if tipo == "vencidos":
        rows = c.execute("""SELECT u.nombres||' '||u.apellidos AS lector, u.tipo, u.correo, u.telefono, e.codigo, l.titulo, pr.fecha_vencimiento
                            FROM prestamos pr JOIN usuarios u ON u.id=pr.lector_id JOIN ejemplares e ON e.id=pr.ejemplar_id JOIN libros l ON l.id=e.libro_id
                            WHERE pr.estado='VENCIDO' ORDER BY pr.fecha_vencimiento""").fetchall()
        now = ahora()
        return [dict(r, dias=(now - p(r["fecha_vencimiento"])).days) for r in rows]
    if tipo == "adquisicion":
        out = []
        for l in c.execute("SELECT l.id, l.titulo, l.isbn FROM libros l WHERE activo=1").fetchall():
            ejs = c.execute("SELECT estado FROM ejemplares WHERE libro_id=?", (l["id"],)).fetchall()
            utiles = [e for e in ejs if e["estado"] not in ("PERDIDO", "DADO_DE_BAJA")]
            perdidos = len(ejs) - len(utiles)
            cola = c.execute("SELECT COUNT(*) FROM reservas WHERE libro_id=? AND estado='PENDIENTE'", (l["id"],)).fetchone()[0]
            prest = c.execute("SELECT COUNT(*) FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id WHERE e.libro_id=? AND pr.fecha_prestamo BETWEEN ? AND ?", (l["id"], desde, hasta + " 23:59")).fetchone()[0]
            rot = round(prest / max(1, len(utiles)), 1)
            motivos = []
            if cola >= 3: motivos.append("Cola de %d reservas" % cola)
            if rot > 3: motivos.append("Rotación %.1f préstamos/ejemplar" % rot)
            if perdidos: motivos.append("%d ejemplar(es) perdido(s) o de baja" % perdidos)
            if motivos:
                out.append(dict(titulo=l["titulo"], isbn=l["isbn"], ejemplares=len(utiles), cola=cola, rotacion=rot, motivos="; ".join(motivos), sugeridos=max(1, cola - 1) + perdidos))
        return sorted(out, key=lambda r: -(r["cola"] * 2 + r["rotacion"]))
    rows = c.execute("""SELECT l.titulo, l.isbn, c.nombre AS categoria,
                          (SELECT COUNT(*) FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id WHERE e.libro_id=l.id AND pr.fecha_prestamo BETWEEN ? AND ?) AS prestamos,
                          (SELECT COUNT(*) FROM reservas r WHERE r.libro_id=l.id AND r.fecha BETWEEN ? AND ?) AS reservas
                        FROM libros l JOIN categorias c ON c.id=l.categoria_id ORDER BY prestamos DESC, reservas DESC LIMIT 12""",
                     (desde, hasta + " 23:59", desde, hasta + " 23:59")).fetchall()
    return [dict(r) for r in rows if r["prestamos"] or r["reservas"]]


@app.route("/reportes")
@rol("BIBLIOTECARIO", "ADMINISTRADOR")
def reportes():
    tipo = request.args.get("tipo", "solicitados")
    hasta = request.args.get("hasta") or ahora().strftime("%Y-%m-%d")
    desde = request.args.get("desde") or (ahora() - timedelta(days=120)).strftime("%Y-%m-%d")
    rows = datos_reporte(tipo, desde, hasta)
    if request.args.get("csv"):
        out = io.StringIO()
        if rows:
            w = csv.DictWriter(out, fieldnames=list(rows[0].keys()), delimiter=";")
            w.writeheader(); w.writerows(rows)
        sv.auditar(g.con, g.user["id"], "EXPORTAR", "Reporte", tipo, ip()); g.con.commit()
        return Response("﻿" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=reporte_%s_%s.csv" % (tipo, hasta)})
    maxv = max([r.get("prestamos", 0) for r in rows] + [1])
    return render_template("reportes.html", tipo=tipo, rows=rows, desde=desde, hasta=hasta, maxv=maxv)


# ------------------------------------------------------------------ RF19-21 administración
@app.route("/politicas", methods=["GET", "POST"])
@rol("ADMINISTRADOR")
def politicas():
    campos = ["max_ejemplares", "dias_prestamo", "max_renovaciones", "max_reservas", "dias_sancion_por_dia", "dias_aviso"]
    if request.method == "POST":
        try:
            for t in sv.TIPOS_LECTOR:
                vals = [int(request.form["%s_%s" % (t, c)]) for c in campos]
                if any(v < 0 or v > 60 for v in vals):
                    raise ReglaNegocio("Los valores deben estar entre 0 y 60.")
                g.con.execute("UPDATE politicas SET %s WHERE tipo_lector=?" % ",".join(c + "=?" for c in campos), vals + [t])
            sv.auditar(g.con, g.user["id"], "CONFIGURAR", "PoliticaPrestamo", "Actualización de parámetros por tipo de lector", ip())
            g.con.commit()
            flash("Políticas guardadas. Se aplican a los préstamos nuevos.", "ok")
        except (ReglaNegocio, ValueError) as e:
            flash(str(e) if isinstance(e, ReglaNegocio) else "Valores inválidos.", "error")
        return redirect(url_for("politicas"))
    pols = {r["tipo_lector"]: r for r in g.con.execute("SELECT * FROM politicas")}
    fest = g.con.execute("SELECT * FROM festivos ORDER BY fecha").fetchall()
    return render_template("politicas.html", pols=pols, campos=campos, fest=fest)


@app.route("/auditoria")
@rol("ADMINISTRADOR")
def auditoria():
    q = request.args.get("q", "")
    acc = request.args.get("accion", "")
    rows = g.con.execute("""SELECT a.*, u.correo FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                            WHERE (?='' OR a.accion=?) AND (?='' OR a.detalle LIKE ? OR u.correo LIKE ?) ORDER BY a.id DESC LIMIT 300""",
                         (acc, acc, q, "%" + q + "%", "%" + q + "%")).fetchall()
    acciones = [r[0] for r in g.con.execute("SELECT DISTINCT accion FROM auditoria ORDER BY 1")]
    return render_template("auditoria.html", rows=rows, q=q, acc=acc, acciones=acciones)


@app.route("/importar", methods=["GET", "POST"])
@rol("ADMINISTRADOR")
def importar():
    preview = None
    if request.method == "POST":
        if request.form.get("accion") == "confirmar":
            filas = session.pop("import_ok", [])
            n = 0
            for r in filas:
                cat = g.con.execute("SELECT id FROM categorias WHERE nombre=?", (r["categoria"],)).fetchone()
                cid = cat["id"] if cat else g.con.execute("INSERT INTO categorias(nombre) VALUES(?)", (r["categoria"],)).lastrowid
                lid = g.con.execute("INSERT INTO libros(isbn,titulo,editorial,anio,idioma,categoria_id,palabras) VALUES(?,?,?,?,?,?,?)",
                                    (r["isbn"], r["titulo"], r["editorial"], r["anio"], "Español", cid, "")).lastrowid
                aid = g.con.execute("INSERT INTO autores(nombre) VALUES(?)", (r["autor"],)).lastrowid
                g.con.execute("INSERT INTO libro_autor VALUES(?,?)", (lid, aid))
                for k in range(int(r.get("ejemplares") or 1)):
                    g.con.execute("INSERT INTO ejemplares(codigo,libro_id,ubicacion,estado,circulacion,fecha_ingreso) VALUES(?,?,?,?,?,?)",
                                  ("BUGP-%03d-%02d" % (lid, k + 1), lid, "Por ubicar", "DISPONIBLE", "GENERAL", f(ahora())))
                n += 1
            sv.auditar(g.con, g.user["id"], "IMPORTAR", "Libro", "%d libros importados desde CSV" % n, ip())
            g.con.commit()
            flash("Importación terminada: %d libros importados." % n, "ok")
            return redirect(url_for("libros"))
        archivo = request.files.get("archivo")
        texto = archivo.read().decode("utf-8-sig") if archivo and archivo.filename else request.form.get("texto", "")
        lector = csv.DictReader(io.StringIO(texto), delimiter=";" if texto.count(";") > texto.count(",") else ",")
        ok, errores = [], []
        for i, r in enumerate(lector, start=2):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            faltan = [c for c in ("isbn", "titulo", "autor", "categoria") if not r.get(c)]
            isbn = r.get("isbn", "").replace("-", "")
            if faltan:
                errores.append((i, "Campos obligatorios vacíos: " + ", ".join(faltan)))
            elif not (isbn.isdigit() and len(isbn) in (10, 13)):
                errores.append((i, "ISBN inválido: " + r["isbn"]))
            elif g.con.execute("SELECT 1 FROM libros WHERE replace(isbn,'-','')=?", (isbn,)).fetchone() or any(x["isbn"].replace("-", "") == isbn for x in ok):
                errores.append((i, "ISBN duplicado: " + r["isbn"]))
            else:
                ok.append(r)
        session["import_ok"] = ok
        preview = dict(ok=ok, errores=errores)
    ejemplo = "isbn;titulo;autor;editorial;anio;categoria;ejemplares\n978-958-42-8547-3;Fundamentos de programación;Luis Joyanes Aguilar;McGraw-Hill;2020;Programación;2\n978-607-15-1234-0;Gestión de proyectos;Harold Kerzner;Wiley;2017;Administración;1\n123;Libro con ISBN malo;Autor X;Editorial;2019;Literatura;1\n978-958-00-0000-1;;Sin título;Editorial;2020;Literatura;1"
    return render_template("importar.html", preview=preview, ejemplo=ejemplo)


@app.route("/proceso-diario", methods=["POST"])
@rol("ADMINISTRADOR", "BIBLIOTECARIO")
def proceso_diario():
    n = sv.proceso_diario(g.con, g.user["id"])
    flash("Proceso diario (CU14) ejecutado: %d notificaciones enviadas por correo." % n, "ok")
    return redirect(url_for("notificaciones"))


@app.route("/reiniciar-demo", methods=["POST"])
@rol("ADMINISTRADOR")
def reiniciar_demo():
    g.con.close(); g.con = None
    db.crear_y_sembrar(forzar=True)
    session.clear()
    flash("Datos de demostración restablecidos.", "ok")
    return redirect(url_for("login"))


@app.route("/salud")
def salud():
    return {"estado": "ok", "hora": ahora().strftime("%Y-%m-%d %H:%M")}


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
