"""Actualiza el Módulo Cosechas vs Cobro: consulta las fuentes (según su frecuencia), arma la base y sube a Supabase
un archivo por pestaña, el resumen para la herramienta de preguntas y el Excel de descarga.

Uso:
  actualizar.py --una-vez                   una actualización
  actualizar.py --escuchar                  queda atendiendo el botón "Actualizar" y carga sola cada día a la hora_diaria
  actualizar.py --local                     genera public/local/ para revisar la app sin Supabase (abrir con ?local)
  actualizar.py --prueba-excel CARPETA      como --local, pero con las hojas del Excel exportadas a .pkl
  --forzar loan,genesis,...|todo            vuelve a consultar fuentes mensuales / Empleados aunque no les toque
"""
import argparse
import json
import logging
import sys
import time as reloj
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cvc import base, fuentes, salidas  # noqa: E402
from cvc.conexion import RAIZ, leer_config  # noqa: E402

LOG = RAIZ / "worker" / "logs" / "actualizar.log"
LOCAL = RAIZ / "public" / "local"


def procesar(datos: dict, info: dict, hoy: date, cfg: dict | None = None) -> dict:
    t0 = reloj.time()
    b, g, avisos = base.construir(datos, hoy)
    for a in avisos:
        logging.info(a)
    meta = {
        "ultima_actualizacion": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fecha_corte": hoy.isoformat(),
        "fuentes": info,
        "avisos": avisos,
        "conteos": {"cosecha": len(b), "cartera_activa": int(b["en_cartera"].sum()),
                    "primeros_pagos": int(b["primer_pago_mes"].sum()), "gestiones": len(g)},
    }
    res = {"meta": meta, "pestanas": salidas.pestañas(b, g, hoy), "ia": salidas.resumen_ia(b, g, hoy), "base": b}
    if cfg:   # Primeros Pagos – Seguimiento (historial de 13 meses desde SQL); si falla, la carga sigue sin esa pestaña
        try:
            from cvc import pp_seguimiento
            res["pestanas"]["primeros_pagos"]["seguimiento"] = salidas.seguimiento(pp_seguimiento.generar(cfg["servidor"], b, hoy))
        except Exception:
            logging.exception("Seguimiento de Primeros Pagos: no se pudo generar; la carga sigue sin él")
    logging.info("Base: %s créditos, %s gestiones (%.0f s)", f"{len(b):,}", f"{len(g):,}", reloj.time() - t0)
    return res


def guardar_local(res: dict):
    LOCAL.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in res["pestanas"].items():
        (LOCAL / f"{nombre}.json").write_bytes(salidas.a_json(contenido))
    (LOCAL / "meta.json").write_bytes(salidas.a_json(res["meta"]))
    (LOCAL / "resumen_ia.json").write_bytes(salidas.a_json(res["ia"]))
    (LOCAL / "Base Cosechas vs Cobro.xlsx").write_bytes(salidas.excel(res["base"]))
    (LOCAL / "base.json").write_bytes(salidas.a_json(salidas.base_json(res["base"])))
    logging.info("Escrito %s", LOCAL)


def actualizar_nube(cfg: dict, sb, pedido: int | None = None, forzar: set[str] | None = None):
    ahora = lambda: datetime.now().astimezone().isoformat()
    if pedido:
        sb.actualizar("cvc_actualizaciones", f"id=eq.{pedido}", {"estado": "procesando", "iniciado_en": ahora()})
    else:
        # La carga automática también queda registrada como "procesando" para que la app sepa que el proceso está ocupado
        try:
            pedido = sb.insertar("cvc_actualizaciones", {"solicitado_nombre": "Carga automática",
                                                         "estado": "procesando", "iniciado_en": ahora()})["id"]
        except Exception as e:
            logging.warning("No se pudo registrar la carga automática en cvc_actualizaciones: %s", e)
    try:
        hoy = date.today()
        datos, info = fuentes.obtener(cfg, forzar, hoy)
        res = procesar(datos, info, hoy, cfg)
        # Token nuevo antes de cada subida: con la red lenta o la PC en reposo, una sesión de Supabase (1 h) no alcanza
        def subir(ruta, contenido, tipo):
            t = reloj.time()
            type(sb)(cfg["supabase"]).subir(ruta, contenido, tipo)
            logging.info("Subido %s (%.0f KB, %.0f s)", ruta, len(contenido) / 1024, reloj.time() - t)
        for nombre, contenido in res["pestanas"].items():
            subir(f"pestanas/{nombre}.json.gz", salidas.comprimir(salidas.a_json(contenido)), "application/gzip")
        subir("ia/resumen.json.gz", salidas.comprimir(salidas.a_json(res["ia"])), "application/gzip")
        # base completa para la descarga filtrada desde la app (mismas columnas del Excel)
        subir("descargas/base.json.gz", salidas.comprimir(salidas.a_json(salidas.base_json(res["base"]))), "application/gzip")
        subir("descargas/base.xlsx", salidas.excel(res["base"]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        sb = type(sb)(cfg["supabase"])
        sb.rpc("cvc_registrar_carga", {"p_meta": json.loads(salidas.a_json(res["meta"]))})
        msg = f"{res['meta']['conteos']['cosecha']:,} créditos cargados"
        logging.info(msg)
        if pedido:
            sb.actualizar("cvc_actualizaciones", f"id=eq.{pedido}", {"estado": "ok", "terminado_en": ahora(), "mensaje": msg})
        # Los clics hechos mientras esta carga corría ya quedan atendidos con ella: no se repite la carga
        sb.actualizar("cvc_actualizaciones", f"estado=eq.pendiente&solicitado_en=lt.{quote(ahora())}",
                      {"estado": "ok", "terminado_en": ahora(), "mensaje": "Atendida con la actualización que estaba en curso"})
    except Exception as e:
        logging.exception("Error en la actualización")
        if pedido:
            sb = type(sb)(cfg["supabase"])
            sb.actualizar("cvc_actualizaciones", f"id=eq.{pedido}",
                          {"estado": "error", "terminado_en": ahora(), "mensaje": str(e)[:500]})
        raise


def escuchar(cfg: dict):
    from cvc.nube import Supabase
    hh, mm = (int(x) for x in cfg.get("hora_diaria", "07:30").split(":"))
    ultima_auto = None
    try:  # si la PC se apagó a media carga, esa solicitud quedó "procesando" para siempre
        Supabase(cfg["supabase"]).actualizar(
            "cvc_actualizaciones", "estado=eq.procesando",
            {"estado": "error", "terminado_en": datetime.now().astimezone().isoformat(),
             "mensaje": "Interrumpida: el proceso se detuvo antes de terminar"})
    except Exception:
        logging.exception("No se pudieron cerrar las actualizaciones interrumpidas")
    while True:
        try:
            sb = Supabase(cfg["supabase"])  # token nuevo en cada vuelta: no caduca aunque quede días encendido
            pend = sb.leer("cvc_actualizaciones", "&estado=eq.pendiente&order=id")
            if pend:
                for p in pend[1:]:  # varios clics seguidos se atienden con una sola actualización
                    sb.actualizar("cvc_actualizaciones", f"id=eq.{p['id']}",
                                  {"estado": "ok", "mensaje": "Atendida junto con la solicitud anterior"})
                actualizar_nube(cfg, sb, pend[0]["id"])
                ultima_auto = date.today() if datetime.now().time() >= datetime.now().replace(hour=hh, minute=mm).time() else ultima_auto
            elif ultima_auto != date.today() and (datetime.now().hour, datetime.now().minute) >= (hh, mm):
                ultima_auto = date.today()
                actualizar_nube(cfg, sb)
        except Exception:
            logging.exception("Vuelta con error; se reintenta")
        reloj.sleep(20)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--una-vez", action="store_true")
    g.add_argument("--escuchar", action="store_true")
    g.add_argument("--local", action="store_true")
    g.add_argument("--prueba-excel", metavar="CARPETA")
    ap.add_argument("--forzar", default="", help="fuentes a reconsultar aunque no les toque (coma) o 'todo'")
    ap.add_argument("--hoy", help="fecha de corte para pruebas (AAAA-MM-DD)")
    a = ap.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
    cfg = leer_config()
    forzar = {x.strip() for x in a.forzar.split(",") if x.strip()}
    hoy = date.fromisoformat(a.hoy) if a.hoy else date.today()
    if a.prueba_excel:
        datos, info = fuentes.desde_pickles(Path(a.prueba_excel))
        guardar_local(procesar(datos, info, hoy))
    elif a.local:
        datos, info = fuentes.obtener(cfg, forzar, hoy)
        guardar_local(procesar(datos, info, hoy))
    elif a.una_vez:
        from cvc.nube import Supabase
        actualizar_nube(cfg, Supabase(cfg["supabase"]), forzar=forzar)
    else:
        escuchar(cfg)


if __name__ == "__main__":
    main()
