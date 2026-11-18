"""Lógica de negocio del SGBU (paquete «servicios» del diagrama de paquetes).

Cada función corresponde a un requisito funcional del SRS (RFxx) y deja
registro en la bitácora de auditoría (RF20).
"""
import math
from datetime import datetime, timedelta
from db import ahora, FMT

TIPOS_LECTOR = ("ESTUDIANTE", "DOCENTE", "ADMINISTRATIVO")


class ReglaNegocio(Exception):
    """Error de validación de una regla del negocio (se muestra al usuario)."""


def p(s):
    return datetime.strptime(s, FMT) if s and len(s) > 10 else (datetime.strptime(s, "%Y-%m-%d") if s else None)


def f(dt):
    return dt.strftime(FMT)


# ------------------------------------------------------------------ utilidades
def auditar(con, usuario_id, accion, entidad, detalle, ip="127.0.0.1"):
    con.execute("INSERT INTO auditoria(fecha,usuario_id,accion,entidad,detalle,ip) VALUES(?,?,?,?,?,?)",
                (f(ahora()), usuario_id, accion, entidad, detalle, ip))


def notificar(con, lector_id, tipo, asunto, mensaje):
    """Simula el envío por el servidor SMTP institucional (Adaptador de correo)."""
    con.execute("INSERT INTO notificaciones(lector_id,tipo,asunto,mensaje,fecha,estado_envio) VALUES(?,?,?,?,?,?)",
                (lector_id, tipo, asunto, mensaje, f(ahora()), "ENVIADA"))


def es_habil(con, d):
    if d.weekday() == 6:  # domingo
        return False
    return con.execute("SELECT 1 FROM festivos WHERE fecha=?", (d.strftime("%Y-%m-%d"),)).fetchone() is None


def siguiente_habil(con, d):
    while not es_habil(con, d):
        d += timedelta(days=1)
    return d


def politica(con, tipo):
    return con.execute("SELECT * FROM politicas WHERE tipo_lector=?", (tipo,)).fetchone()


# ------------------------------------------------------------------ mantenimiento de estados
def refrescar_estados(con):
    now = ahora()
    con.execute("UPDATE prestamos SET estado='VENCIDO' WHERE estado='ACTIVO' AND fecha_vencimiento < ?", (f(now),))
    con.execute("UPDATE sanciones SET estado='CUMPLIDA' WHERE estado='ACTIVA' AND fecha_fin < ?", (now.strftime("%Y-%m-%d"),))
    for r in con.execute("SELECT * FROM reservas WHERE estado='DISPONIBLE' AND fecha_expiracion < ?", (f(now),)).fetchall():
        con.execute("UPDATE reservas SET estado='EXPIRADA' WHERE id=?", (r["id"],))
        asignar_siguiente_reserva(con, r["ejemplar_id"], r["libro_id"])
    con.commit()


def asignar_siguiente_reserva(con, ejemplar_id, libro_id):
    """RF09/RF10: el ejemplar pasa al primero de la cola o queda DISPONIBLE."""
    sig = con.execute("SELECT * FROM reservas WHERE libro_id=? AND estado='PENDIENTE' ORDER BY fecha LIMIT 1", (libro_id,)).fetchone()
    if sig:
        now = ahora()
        exp = siguiente_habil(con, (now + timedelta(days=2)).replace(hour=18, minute=0))
        con.execute("UPDATE reservas SET estado='DISPONIBLE', ejemplar_id=?, fecha_disponible=?, fecha_expiracion=? WHERE id=?",
                    (ejemplar_id, f(now), f(exp), sig["id"]))
        con.execute("UPDATE ejemplares SET estado='RESERVADO' WHERE id=?", (ejemplar_id,))
        libro = con.execute("SELECT titulo FROM libros WHERE id=?", (libro_id,)).fetchone()
        cod = con.execute("SELECT codigo FROM ejemplares WHERE id=?", (ejemplar_id,)).fetchone()
        notificar(con, sig["lector_id"], "RESERVA_DISPONIBLE", "Su reserva está disponible",
                  "El libro «%s» está disponible para retirar (ejemplar %s) hasta el %s." % (libro["titulo"], cod["codigo"], exp.strftime("%d/%m/%Y %H:%M")))
        return sig
    con.execute("UPDATE ejemplares SET estado='DISPONIBLE' WHERE id=?", (ejemplar_id,))
    return None


# ------------------------------------------------------------------ habilitación (include del CU)
def sancion_vigente(con, lector_id):
    return con.execute("SELECT * FROM sanciones WHERE lector_id=? AND estado='ACTIVA' ORDER BY fecha_fin DESC LIMIT 1", (lector_id,)).fetchone()


def estado_lector(con, lector):
    pol = politica(con, lector["tipo"])
    activos = con.execute("SELECT COUNT(*) FROM prestamos WHERE lector_id=? AND estado IN ('ACTIVO','VENCIDO')", (lector["id"],)).fetchone()[0]
    vencidos = con.execute("SELECT COUNT(*) FROM prestamos WHERE lector_id=? AND estado='VENCIDO'", (lector["id"],)).fetchone()[0]
    reservas = con.execute("SELECT COUNT(*) FROM reservas WHERE lector_id=? AND estado IN ('PENDIENTE','DISPONIBLE')", (lector["id"],)).fetchone()[0]
    san = sancion_vigente(con, lector["id"])
    motivos = []
    if lector["estado"] != "ACTIVO":
        motivos.append("El usuario está INACTIVO.")
    if san:
        motivos.append("Tiene una sanción vigente hasta el %s." % p(san["fecha_fin"]).strftime("%d/%m/%Y"))
    if vencidos:
        motivos.append("Tiene %d préstamo(s) vencido(s) sin devolver." % vencidos)
    return dict(politica=pol, activos=activos, vencidos=vencidos, reservas=reservas, sancion=san, motivos=motivos,
                habilitado=not motivos)


def verificar_habilitacion(con, lector, para="prestamo"):
    st = estado_lector(con, lector)
    if lector["tipo"] not in TIPOS_LECTOR:
        raise ReglaNegocio("El usuario no es un lector.")
    if st["motivos"]:
        raise ReglaNegocio(" ".join(st["motivos"]))
    if para == "prestamo" and st["activos"] >= st["politica"]["max_ejemplares"]:
        raise ReglaNegocio("Cupo agotado: tiene %d de %d ejemplares permitidos." % (st["activos"], st["politica"]["max_ejemplares"]))
    if para == "reserva" and st["reservas"] >= st["politica"]["max_reservas"]:
        raise ReglaNegocio("Alcanzó el máximo de %d reservas activas." % st["politica"]["max_reservas"])
    return st


def periodo_restringido_ok(now):
    """Ejemplares RESTRINGIDOS: préstamo de lunes a sábado desde las 4:00 p. m."""
    return now.weekday() < 6 and now.hour >= 16


def validar_ejemplar(con, ejemplar, lector):
    """include «Validar política de circulación»."""
    if ejemplar["circulacion"] == "SOLO_SALA":
        raise ReglaNegocio("El ejemplar %s es SOLO_SALA: no puede salir de la biblioteca." % ejemplar["codigo"])
    if ejemplar["estado"] == "RESERVADO":
        r = con.execute("SELECT r.*, u.nombres||' '||u.apellidos AS nombre FROM reservas r JOIN usuarios u ON u.id=r.lector_id WHERE r.ejemplar_id=? AND r.estado='DISPONIBLE'", (ejemplar["id"],)).fetchone()
        if not r or r["lector_id"] != lector["id"]:
            raise ReglaNegocio("El ejemplar %s está reservado para %s." % (ejemplar["codigo"], r["nombre"] if r else "otro lector"))
        return r
    if ejemplar["estado"] != "DISPONIBLE":
        raise ReglaNegocio("El ejemplar %s no está disponible (estado %s)." % (ejemplar["codigo"], ejemplar["estado"]))
    if ejemplar["circulacion"] == "RESTRINGIDO" and not periodo_restringido_ok(ahora()):
        raise ReglaNegocio("El ejemplar %s es RESTRINGIDO: solo se presta de lunes a sábado desde las 4:00 p. m." % ejemplar["codigo"])
    return None


def calcular_vencimiento(con, ejemplar, lector):
    now = ahora()
    if ejemplar["circulacion"] == "RESTRINGIDO":
        return siguiente_habil(con, (now + timedelta(days=1)).replace(hour=10, minute=0))
    pol = politica(con, lector["tipo"])
    return siguiente_habil(con, (now + timedelta(days=pol["dias_prestamo"])).replace(hour=18, minute=0))


# ------------------------------------------------------------------ RF06 préstamo
def registrar_prestamo(con, lector, codigos, bibliotecario_id):
    st = verificar_habilitacion(con, lector)
    if st["activos"] + len(codigos) > st["politica"]["max_ejemplares"]:
        raise ReglaNegocio("Supera el cupo: puede llevar %d ejemplar(es) más." % (st["politica"]["max_ejemplares"] - st["activos"]))
    res = []
    for cod in codigos:
        ej = con.execute("SELECT * FROM ejemplares WHERE codigo=?", (cod,)).fetchone()
        if not ej:
            raise ReglaNegocio("No existe el ejemplar %s." % cod)
        reserva = validar_ejemplar(con, ej, lector)
        venc = calcular_vencimiento(con, ej, lector)
        pid = con.execute("INSERT INTO prestamos(ejemplar_id,lector_id,bibliotecario_id,fecha_prestamo,fecha_vencimiento,estado) VALUES(?,?,?,?,?,?)",
                          (ej["id"], lector["id"], bibliotecario_id, f(ahora()), f(venc), "ACTIVO")).lastrowid
        con.execute("UPDATE ejemplares SET estado='PRESTADO' WHERE id=?", (ej["id"],))
        if reserva:
            con.execute("UPDATE reservas SET estado='ATENDIDA' WHERE id=?", (reserva["id"],))
        auditar(con, bibliotecario_id, "PRESTAMO", "Prestamo", "P-%d: %s a %s" % (pid, cod, lector["correo"]))
        titulo = con.execute("SELECT titulo FROM libros WHERE id=?", (ej["libro_id"],)).fetchone()["titulo"]
        res.append(dict(id=pid, codigo=cod, titulo=titulo, vence=venc))
    detalle = "; ".join("%s – %s (vence %s)" % (r["codigo"], r["titulo"], r["vence"].strftime("%d/%m/%Y %H:%M")) for r in res)
    notificar(con, lector["id"], "COMPROBANTE_PRESTAMO", "Comprobante de préstamo", "Se registró el préstamo de: " + detalle + ".")
    con.commit()
    return res


# ------------------------------------------------------------------ RF07 / RF11 devolución y sanción
def registrar_devolucion(con, codigo, bibliotecario_id, deteriorado=False, observacion=""):
    ej = con.execute("SELECT * FROM ejemplares WHERE codigo=?", (codigo,)).fetchone()
    if not ej:
        raise ReglaNegocio("No existe el ejemplar %s." % codigo)
    pr = con.execute("SELECT * FROM prestamos WHERE ejemplar_id=? AND estado IN ('ACTIVO','VENCIDO')", (ej["id"],)).fetchone()
    if not pr:
        raise ReglaNegocio("El ejemplar %s no tiene un préstamo activo." % codigo)
    now = ahora()
    con.execute("UPDATE prestamos SET fecha_devolucion=?, estado='DEVUELTO', recibido_por=? WHERE id=?", (f(now), bibliotecario_id, pr["id"]))
    lector = con.execute("SELECT * FROM usuarios WHERE id=?", (pr["lector_id"],)).fetchone()
    resultado = dict(prestamo=pr["id"], sancion=None, reserva=None, estado_ejemplar=None)
    venc = p(pr["fecha_vencimiento"])
    if now > venc:  # «extend» Aplicar sanción por retraso
        pol = politica(con, lector["tipo"])
        if ej["circulacion"] == "RESTRINGIDO":
            dias = math.ceil((now - venc).total_seconds() / 3600)
        else:
            dias = math.ceil((now - venc).total_seconds() / 86400) * pol["dias_sancion_por_dia"]
        vig = sancion_vigente(con, lector["id"])
        inicio = (p(vig["fecha_fin"]) + timedelta(days=1)) if vig else now.replace(hour=0, minute=0)
        fin = inicio + timedelta(days=dias - 1)
        sid = con.execute("INSERT INTO sanciones(lector_id,prestamo_id,fecha_inicio,fecha_fin,dias,motivo,estado) VALUES(?,?,?,?,?,?,?)",
                          (lector["id"], pr["id"], inicio.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"), dias,
                           "Devolución tardía del préstamo P-%d" % pr["id"], "ACTIVA")).lastrowid
        notificar(con, lector["id"], "SANCION_GENERADA", "Sanción por devolución tardía",
                  "Se generó una sanción de %d día(s), del %s al %s, por la devolución tardía del ejemplar %s." % (
                      dias, inicio.strftime("%d/%m/%Y"), fin.strftime("%d/%m/%Y"), codigo))
        auditar(con, bibliotecario_id, "SANCION", "Sancion", "S-%d: %d día(s) a %s" % (sid, dias, lector["correo"]))
        resultado["sancion"] = dict(dias=dias, inicio=inicio, fin=fin)
    if deteriorado:
        con.execute("UPDATE ejemplares SET estado='EN_REPARACION', observacion=? WHERE id=?", (observacion or "Devuelto deteriorado", ej["id"]))
        resultado["estado_ejemplar"] = "EN_REPARACION"
    else:  # «extend» Notificar reserva disponible
        sig = asignar_siguiente_reserva(con, ej["id"], ej["libro_id"])
        if sig:
            u = con.execute("SELECT nombres||' '||apellidos AS n FROM usuarios WHERE id=?", (sig["lector_id"],)).fetchone()
            resultado["reserva"] = u["n"]
            resultado["estado_ejemplar"] = "RESERVADO"
        else:
            resultado["estado_ejemplar"] = "DISPONIBLE"
    auditar(con, bibliotecario_id, "DEVOLUCION", "Prestamo", "P-%d: %s devuelto por %s" % (pr["id"], codigo, lector["correo"]))
    con.commit()
    resultado["lector"] = lector
    return resultado


# ------------------------------------------------------------------ RF08 renovación
def renovar(con, prestamo_id, usuario_id):
    pr = con.execute("SELECT pr.*, e.circulacion, e.libro_id, e.codigo FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id WHERE pr.id=?", (prestamo_id,)).fetchone()
    if not pr or pr["estado"] != "ACTIVO":
        raise ReglaNegocio("Solo se pueden renovar préstamos activos que no estén vencidos.")
    lector = con.execute("SELECT * FROM usuarios WHERE id=?", (pr["lector_id"],)).fetchone()
    pol = politica(con, lector["tipo"])
    if pr["circulacion"] == "RESTRINGIDO":
        raise ReglaNegocio("Los ejemplares RESTRINGIDOS no son renovables.")
    if pr["renovaciones"] >= pol["max_renovaciones"]:
        raise ReglaNegocio("Ya usó las %d renovación(es) permitidas." % pol["max_renovaciones"])
    if sancion_vigente(con, lector["id"]):
        raise ReglaNegocio("No puede renovar con una sanción vigente.")
    if con.execute("SELECT 1 FROM reservas WHERE libro_id=? AND estado='PENDIENTE'", (pr["libro_id"],)).fetchone():
        raise ReglaNegocio("El libro tiene reservas pendientes de otros lectores.")
    venc = siguiente_habil(con, (ahora() + timedelta(days=pol["dias_prestamo"])).replace(hour=18, minute=0))
    con.execute("UPDATE prestamos SET fecha_vencimiento=?, renovaciones=renovaciones+1 WHERE id=?", (f(venc), prestamo_id))
    auditar(con, usuario_id, "RENOVACION", "Prestamo", "P-%d renovado hasta %s" % (prestamo_id, venc.strftime("%d/%m/%Y")))
    con.commit()
    return venc


# ------------------------------------------------------------------ RF09 / RF10 reservas
def reservar(con, lector, libro_id):
    verificar_habilitacion(con, lector, para="reserva")
    ejs = con.execute("SELECT * FROM ejemplares WHERE libro_id=? AND estado NOT IN ('PERDIDO','DADO_DE_BAJA')", (libro_id,)).fetchall()
    prestables = [e for e in ejs if e["circulacion"] != "SOLO_SALA"]
    if not prestables:
        raise ReglaNegocio("Este libro es de consulta en sala: no se puede reservar.")
    if any(e["estado"] == "DISPONIBLE" for e in prestables):
        raise ReglaNegocio("Hay ejemplares disponibles: acérquese al mostrador para el préstamo.")
    if con.execute("SELECT 1 FROM reservas WHERE libro_id=? AND lector_id=? AND estado IN ('PENDIENTE','DISPONIBLE')", (libro_id, lector["id"])).fetchone():
        raise ReglaNegocio("Ya tiene una reserva de este libro.")
    if con.execute("SELECT 1 FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id WHERE e.libro_id=? AND pr.lector_id=? AND pr.estado IN ('ACTIVO','VENCIDO')", (libro_id, lector["id"])).fetchone():
        raise ReglaNegocio("Ya tiene en préstamo un ejemplar de este libro.")
    rid = con.execute("INSERT INTO reservas(libro_id,lector_id,fecha,estado) VALUES(?,?,?,?)", (libro_id, lector["id"], f(ahora()), "PENDIENTE")).lastrowid
    pos = con.execute("SELECT COUNT(*) FROM reservas WHERE libro_id=? AND estado='PENDIENTE' AND id<=?", (libro_id, rid)).fetchone()[0]
    auditar(con, lector["id"], "RESERVA", "Reserva", "R-%d sobre libro %d, posición %d" % (rid, libro_id, pos))
    con.commit()
    return pos


def cancelar_reserva(con, reserva_id, usuario_id):
    r = con.execute("SELECT * FROM reservas WHERE id=?", (reserva_id,)).fetchone()
    if not r or r["estado"] not in ("PENDIENTE", "DISPONIBLE"):
        raise ReglaNegocio("La reserva no se puede cancelar.")
    con.execute("UPDATE reservas SET estado='CANCELADA' WHERE id=?", (reserva_id,))
    if r["estado"] == "DISPONIBLE" and r["ejemplar_id"]:
        asignar_siguiente_reserva(con, r["ejemplar_id"], r["libro_id"])
    auditar(con, usuario_id, "CANCELAR_RESERVA", "Reserva", "R-%d cancelada" % reserva_id)
    con.commit()


def posicion_reserva(con, r):
    if r["estado"] != "PENDIENTE":
        return None
    return con.execute("SELECT COUNT(*) FROM reservas WHERE libro_id=? AND estado='PENDIENTE' AND fecha<=?", (r["libro_id"], r["fecha"])).fetchone()[0]


# ------------------------------------------------------------------ RF13 proceso diario (temporizador)
def proceso_diario(con, usuario_id):
    refrescar_estados(con)
    now = ahora()
    n = 0
    for pr in con.execute("""SELECT pr.*, e.codigo, l.titulo, u.tipo FROM prestamos pr JOIN ejemplares e ON e.id=pr.ejemplar_id
                             JOIN libros l ON l.id=e.libro_id JOIN usuarios u ON u.id=pr.lector_id WHERE pr.estado IN ('ACTIVO','VENCIDO')""").fetchall():
        venc = p(pr["fecha_vencimiento"])
        aviso = politica(con, pr["tipo"])["dias_aviso"]
        dias = (venc.date() - now.date()).days
        if pr["estado"] == "VENCIDO":
            notificar(con, pr["lector_id"], "PRESTAMO_VENCIDO", "Préstamo vencido: " + pr["titulo"],
                      "Su préstamo del ejemplar %s venció el %s. Devuélvalo para evitar más días de sanción." % (pr["codigo"], venc.strftime("%d/%m/%Y %H:%M")))
            n += 1
        elif dias in (aviso, 0):
            notificar(con, pr["lector_id"], "RECORDATORIO_VENCIMIENTO", "Recordatorio: su préstamo vence " + ("hoy" if dias == 0 else "en %d días" % dias),
                      "El ejemplar %s («%s») vence el %s." % (pr["codigo"], pr["titulo"], venc.strftime("%d/%m/%Y %H:%M")))
            n += 1
    auditar(con, usuario_id, "PROCESO_DIARIO", "Notificacion", "%d notificaciones enviadas" % n)
    con.commit()
    return n


# ------------------------------------------------------------------ RF12 sanciones
def anular_sancion(con, sancion_id, justificacion, usuario_id):
    if not justificacion or len(justificacion.strip()) < 10:
        raise ReglaNegocio("Debe escribir una justificación (mínimo 10 caracteres).")
    con.execute("UPDATE sanciones SET estado='ANULADA', justificacion=? WHERE id=? AND estado='ACTIVA'", (justificacion.strip(), sancion_id))
    auditar(con, usuario_id, "ANULAR_SANCION", "Sancion", "S-%d anulada: %s" % (sancion_id, justificacion.strip()))
    con.commit()
