"""Ejecuta las consultas según su frecuencia y guarda una copia local en worker/data/.

- mensual:   se consulta en la primera carga de cada mes (el 01) y se reutiliza el resto del mes.
- empleados: se consulta en la primera carga a partir de cada día de `dias_empleados` (1, 13 y 25).
- diaria:    se consulta en cada carga.
Si una consulta falla y hay copia guardada, se usa la copia y se avisa en el log.
"""
import json
import logging
import time as reloj
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .conexion import RAIZ, consultar

DATA = RAIZ / "worker" / "data"
ESTADO = DATA / "estado.json"


def _estado() -> dict:
    return json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}


def _guardar_estado(e: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")


def inicio_vigencia(frecuencia: str, hoy: date, dias_empleados: list[int]) -> date:
    """Desde qué fecha debe ser la copia para seguir vigente."""
    if frecuencia == "mensual":
        return hoy.replace(day=1)
    if frecuencia == "empleados":
        return hoy.replace(day=max(d for d in sorted(dias_empleados) if d <= hoy.day))
    return hoy  # diaria


def toca(nombre: str, frecuencia: str, hoy: date, dias_empleados: list[int], forzar: set[str]) -> bool:
    if frecuencia == "diaria" or nombre in forzar or "todo" in forzar:
        return True
    cargado = _estado().get(nombre, {}).get("fecha")
    if not cargado or not (DATA / f"{nombre}.pkl").exists():
        return True
    return date.fromisoformat(cargado[:10]) < inicio_vigencia(frecuencia, hoy, dias_empleados)


def obtener(cfg: dict, forzar: set[str] | None = None, hoy: date | None = None) -> tuple[dict[str, pd.DataFrame], dict]:
    """Devuelve {fuente: DataFrame} y {fuente: {fecha, filas, origen}}."""
    hoy, forzar = hoy or date.today(), forzar or set()
    dias = cfg.get("dias_empleados", [1, 13, 25])
    intentos, espera = int(cfg.get("intentos", 3)), float(cfg.get("espera_minutos", 10)) * 60
    est = _estado()
    datos, info = {}, {}
    for nombre, f in cfg["fuentes"].items():
        pkl = DATA / f"{nombre}.pkl"
        if toca(nombre, f["frecuencia"], hoy, dias, forzar):
            sql = (RAIZ / f["sql"]).read_text(encoding="utf-8-sig")
            for i in range(1, intentos + 1):
                try:
                    t0 = reloj.time()
                    df = consultar(cfg["servidor"], sql)
                    if df.empty:
                        raise RuntimeError("la consulta no devolvió filas")
                    logging.info("%s: %s filas (%.0f s)", nombre, f"{len(df):,}", reloj.time() - t0)
                    DATA.mkdir(parents=True, exist_ok=True)
                    df.to_pickle(pkl)
                    est[nombre] = {"fecha": datetime.now().isoformat(timespec="seconds"), "filas": len(df)}
                    _guardar_estado(est)
                    datos[nombre] = df
                    break
                except Exception as e:  # noqa: BLE001
                    logging.warning("%s: intento %s de %s falló: %s", nombre, i, intentos, e)
                    if i < intentos:
                        reloj.sleep(espera)
            if nombre not in datos:
                if not pkl.exists():
                    raise RuntimeError(f"No se pudo consultar {nombre} y no hay copia guardada")
                logging.warning("%s: se usa la copia guardada del %s", nombre, est.get(nombre, {}).get("fecha"))
        if nombre not in datos:
            datos[nombre] = pd.read_pickle(pkl)
        info[nombre] = {"fecha": est.get(nombre, {}).get("fecha"), "filas": len(datos[nombre]),
                        "frecuencia": f["frecuencia"]}
    return datos, info


def desde_pickles(carpeta: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    """Modo de prueba: lee las fuentes exportadas del Excel de referencia (una por hoja)."""
    datos = {p.stem: pd.read_pickle(p) for p in carpeta.glob("*.pkl")}
    # Nombres de columnas del Excel que difieren de los queries
    if "primera_renov" in datos:
        datos["primera_renov"] = datos["primera_renov"].rename(columns={"Primer_Credito": "primer_credito"})
    info = {n: {"fecha": datetime.fromtimestamp((carpeta / f"{n}.pkl").stat().st_mtime).isoformat(timespec="seconds"),
                "filas": len(d), "frecuencia": "prueba"} for n, d in datos.items()}
    return datos, info
