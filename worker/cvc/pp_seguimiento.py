"""Primeros Pagos – Seguimiento: indicadores de cobranza de las cuotas 1 a 6 (1PD a 6PD), mes a mes, como el informe
"Informe_1PD_Nicaragua" (carpeta Seguimiento Cobro), pero con datos de SQL y con dos formas de medir cada mes:

- "dia":    a la misma fecha (el día del mes de hoy; si el mes es más corto, su último día).
- "cierre": al fin de mes (indicador oficial 1PD). El mes en curso se mide a hoy en las dos.

Universo de la cuota n: créditos del Loan Tape (Convenio incluido desde el 23-nov-2026; se separa con el filtro Producto
Madre) cuya cuota n (primera cuota + n-1 meses) cae en los últimos 13 meses. La intensidad de gestión sigue sin Convenio
(se cobra por planilla).
- nPD (indicador oficial): la foto de MCCollect del corte trae n o más cuotas vencidas, es decir, no pagó ninguna de
  sus primeras n cuotas (validado 100% contra la marca 1PD-4PD de th_pds_mensual del Power BI, 19-nov-2026).
- Mora por cuota n: la cuota n quedó sin pagar (1 o más cuotas vencidas), aunque haya pagado las anteriores.
Días hábiles de lunes a sábado sin feriados, igual que el informe.

Fuentes históricas (fotos diarias):
- MCCollect cartera  th_mccollect_cartera_diaria_regional   (cuotas vencidas, días mora, saldo, último pago)
- MCCollect gestiones th_mccollect_gestiones_diarias_regional (el cono)
- Cendoc              th_cendoc_diario_regional               (rodamiento a la fecha de corte)
Lo ya consultado queda en worker/data/ppseg/ y cada día solo se agrega lo nuevo.
"""
import logging
import os
import warnings
import shutil
import time as reloj
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd

from .conexion import RAIZ, conectar

# Caché fuera de OneDrive (son cientos de MB que cambian cada día); la primera vez se copia la caché anterior
CACHE_ANTERIOR = RAIZ / "worker" / "data" / "ppseg"
CACHE = Path(os.environ.get("LOCALAPPDATA") or (RAIZ / "worker" / "data")) / "CosechasVsCobro" / "ppseg"
MESES_HIST = 13
PDS = range(1, 7)                               # 1PD a 6PD
USUARIOS_EXCLUIDOS = {"jjreyesu"}
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)   # columnas agregadas una a una por corte               # gestiones del área comercial, no de cobro (19-nov-2026)
INICIO_FOTOS = pd.Timestamp("2025-10-01")      # primera foto diaria disponible en MCCollect y Cendoc
ANTES, DESPUES = 12, 31                         # ventana por crédito alrededor de su primera cuota (días)
VENT = 15                                       # días hábiles de mora observados por cuota (como el informe)
FERIADOS = pd.to_datetime(['2025-12-08', '2025-12-25',
                           '2026-01-01', '2026-04-02', '2026-04-03', '2026-05-01', '2026-05-30', '2026-07-19',
                           '2026-09-14', '2026-09-15', '2026-12-08', '2026-12-25',
                           '2027-01-01', '2027-03-25', '2027-03-26', '2027-05-01', '2027-05-30', '2027-07-19',
                           '2027-09-14', '2027-09-15', '2027-12-08', '2027-12-25'])
BDAYS = pd.bdate_range('2025-08-01', '2027-12-31', freq='C', weekmask='Mon Tue Wed Thu Fri Sat', holidays=FERIADOS)
SALDO_VISITA = 12000
CANALES = {"sms": ["SMS"], "wap": ["WHATSAPP"], "llam": ["LLAMADA_CLIENTE", "LLAMADA_REFERENCIA"], "pred": ["PREDICTIVO"],
           "vis": ["VISITA", "ENVIO_VISITA"]}
DIMS = ["producto_madre", "clasificacion", "producto_comercial", "mes_desembolso", "canal", "sucursal_promotor", "sucursal",
        "politica_hit", "tipo_credito_legal", "tipo_salario", "rango_antig_cliente", "rango_antig_laboral", "rango_capacidad",
        "rango_desembolso", "rango_edad", "rango_estabilidad", "rango_ingreso", "rango_multiplicador", "rango_salario",
        "rango_score", "resultado_motor", "dealer_genesis", "suc_dealer", "con_excepcion", "con_prima", "dia_pago",
        "empleo_inss", "medio_captacion", "promotor"]


def bpos(fechas) -> np.ndarray:
    """Posición del primer día hábil >= fecha."""
    return BDAYS.searchsorted(pd.DatetimeIndex(fechas).normalize())


# ---------------------------------------------------------------- universo
def universo(b: pd.DataFrame, hoy: pd.Timestamp, n: int = 1) -> tuple[pd.DataFrame, list[str]]:
    """Cuotas n (1 = primera cuota) que vencen en los últimos 13 meses; la cuota n vence n-1 meses después de la primera."""
    mes_hoy = hoy.to_period("M")
    meses = [str(p) for p in pd.period_range(mes_hoy - (MESES_HIST - 1), mes_hoy, freq="M")]
    ini, fin = pd.Period(meses[0]).start_time, mes_hoy.end_time.normalize()
    r = b[b["primera_cuota"].notna()].copy()
    if n > 1:
        r = r[pd.to_numeric(r["numero_cuotas"], errors="coerce").fillna(99) >= n]
    base = pd.DatetimeIndex(r["primera_cuota"]).normalize()
    r["D"] = base + pd.DateOffset(months=n - 1) if n > 1 else base
    u = r[r["D"].between(ini, fin)].copy()
    u["mes_cobro"] = u["D"].dt.strftime("%Y-%m")
    u["w"] = pd.to_numeric(u["saldopagare"], errors="coerce").fillna(0)
    u["desde"] = (u["D"] - pd.Timedelta(days=ANTES)).clip(lower=INICIO_FOTOS)
    u["hasta"] = np.minimum(u["D"] + pd.Timedelta(days=DESPUES), hoy)
    return u, meses


def cortes(meses: list[str], hoy: pd.Timestamp) -> dict[str, dict[str, pd.Timestamp]]:
    """Fecha de corte de cada mes: misma fecha (día de hoy) y cierre; el mes en curso, hoy.
    La foto de MCCollect/Cendoc de una fecha trae el estado al cierre del día anterior: el cierre de mes se lee en la
    foto del día 1 siguiente (así cuadra 100% con la bandera 1PD oficial); la misma fecha usa la foto de ese día, igual que hoy."""
    out = {}
    for m in meses:
        p = pd.Period(m)
        if p == hoy.to_period("M"):
            out[m] = {"dia": hoy, "cierre": hoy, "foto_dia": hoy, "foto_cierre": hoy}
        else:
            fin = p.end_time.normalize()
            d = min(pd.Timestamp(p.year, p.month, 1) + pd.Timedelta(days=hoy.day - 1), fin)
            out[m] = {"dia": d, "cierre": fin, "foto_dia": d, "foto_cierre": fin + pd.Timedelta(days=1)}
    return out


# ---------------------------------------------------------------- extracción con caché
def _leer(nombre, columnas):
    p = CACHE / f"{nombre}.pkl"
    if not p.exists() and (CACHE_ANTERIOR / f"{nombre}.pkl").exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CACHE_ANTERIOR / f"{nombre}.pkl", p)
    return pd.read_pickle(p) if p.exists() else pd.DataFrame(columns=columnas)


def _compacto(df):
    """Tipos chicos para la caché de cartera (millones de filas con 6 cuotas por crédito)."""
    df = df.copy()
    for c in ("cv", "dm", "saldo", "mup"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    if "fup" in df:
        df["fup"] = pd.to_datetime(df["fup"], errors="coerce")
    return df


def _guardar(df, nombre):
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_pickle(CACHE / f"{nombre}.pkl")


def _filas(cur):
    return pd.DataFrame.from_records([tuple(x) for x in cur.fetchall()], columns=[c[0] for c in cur.description])


def extraer(cfg: dict, u: pd.DataFrame, meses: list[str], cts: dict, hoy: pd.Timestamp):
    """Cartera diaria, gestiones y Cendoc de los créditos del universo; solo consulta lo que falta en la caché."""
    t0 = reloj.time()
    cn = conectar(cfg); cur = cn.cursor(); cur.fast_executemany = True
    cur.execute("SELECT MAX(F_REPORTE) FROM [MCCOLLECT].[dbo].[th_mccollect_cartera_diaria_regional] WHERE pais = 'Nicaragua'")
    ult_car = pd.Timestamp(cur.fetchone()[0]).normalize()
    cur.execute("SELECT DISTINCT CAST(f_reporte AS DATE) FROM [CENDOC].[dbo].[th_cendoc_diario_regional] "
                f"WHERE pais = 'Nicaragua' AND f_reporte >= '{INICIO_FOTOS:%Y-%m-%d}'")
    fechas_cendoc = pd.DatetimeIndex(sorted(pd.Timestamp(r[0]) for r in cur.fetchall()))

    # 1) Cartera diaria: pares (crédito, fecha) que faltan; una consulta por fecha (usa el índice por fecha)
    nec = u[["credito", "desde", "hasta"]].copy()
    nec["hasta"] = np.minimum(nec["hasta"], ult_car)
    nec = nec[nec["hasta"] >= nec["desde"]]
    nec["f"] = [pd.date_range(a, z) for a, z in zip(nec["desde"], nec["hasta"])]
    nec = nec[["credito", "f"]].explode("f").drop_duplicates()
    hechos = _leer("cartera_pares", ["credito", "f"])
    car = _leer("cartera", ["credito", "f", "cv", "dm", "saldo", "fup", "mup"])
    for df in (nec, hechos, car):   # tipos uniformes para los cruces
        df["credito"] = df["credito"].astype(object); df["f"] = pd.to_datetime(df["f"]).astype("datetime64[ns]")
    # las fotos de los 2 últimos días se vuelven a pedir (pueden haberse recargado)
    recientes = ult_car - pd.Timedelta(days=1)
    hechos = hechos[pd.to_datetime(hechos["f"]) < recientes]
    car = car[pd.to_datetime(car["f"]) < recientes]
    falta = nec.merge(hechos.assign(_h=1), on=["credito", "f"], how="left")
    falta = falta[falta["_h"].isna()][["credito", "f"]]
    if len(falta):
        # se sube solo la ventana de cada crédito (pocos miles de filas) y se pide una fecha a la vez
        cur.execute("CREATE TABLE #m (credito VARCHAR(30) PRIMARY KEY, desde DATE, hasta DATE)")
        k = u.groupby("credito", as_index=False).agg(desde=("desde", "min"), hasta=("hasta", "max"))[["credito", "desde", "hasta"]]
        cur.executemany("INSERT INTO #m VALUES (?, ?, ?)",
                        [(c, a.strftime("%Y-%m-%d"), z.strftime("%Y-%m-%d")) for c, a, z in k.itertuples(index=False)])
        nuevas = []
        fechas = sorted(falta["f"].unique())
        for j, f in enumerate(fechas):
            fs = pd.Timestamp(f).strftime("%Y-%m-%d")
            cur.execute(f"""SELECT RTRIM(c.PR_MC_CREDITO) credito, CAST(c.F_REPORTE AS DATE) f, c.PR_CL_NRO_CUOTAS_VENCIDAS cv,
                   c.PR_CL_DIA_MORA_HOY dm, c.PR_CL_SALDO_DOC saldo, c.PR_CL_DATE_ULT_PAGO fup, c.PR_CL_MONTO_ULT_PAGO mup
                FROM [MCCOLLECT].[dbo].[th_mccollect_cartera_diaria_regional] c
                WHERE c.pais = 'Nicaragua' AND c.F_REPORTE = '{fs}'
                  AND RTRIM(c.PR_MC_CREDITO) IN (SELECT credito FROM #m WHERE '{fs}' BETWEEN desde AND hasta)""")
            nuevas.append(_filas(cur))
            if j % 50 == 49:
                logging.info("Seguimiento PP: cartera %s de %s fechas", j + 1, len(fechas))
        cur.execute("DROP TABLE #m")
        n = pd.concat(nuevas, ignore_index=True) if nuevas else car.iloc[:0]
        n["f"] = pd.to_datetime(n["f"])
        car = pd.concat([car[~pd.to_datetime(car["f"]).isin(pd.DatetimeIndex(fechas))], n], ignore_index=True)
        hechos = pd.concat([hechos[~pd.to_datetime(hechos["f"]).isin(pd.DatetimeIndex(fechas))],
                            nec[nec["f"].isin(pd.DatetimeIndex(fechas))]], ignore_index=True)
        car = _compacto(car); hechos = hechos.drop_duplicates()
        _guardar(car, "cartera"); _guardar(hechos, "cartera_pares")
        logging.info("Seguimiento PP: cartera %s fechas, %s filas nuevas (%.0f s)", len(fechas), f"{len(n):,}", reloj.time() - t0)

    # 2) Gestiones por mes calendario; el mes en curso y el anterior siempre se vuelven a pedir
    t1 = reloj.time()
    ges = _leer("gestiones", ["credito", "fa", "acc", "res", "usuario", "fprom", "monto_promesa", "gestionada", "contacto", "rpc", "promesa", "mes"])
    if "gestionada" not in ges:   # caché anterior sin la marca de intento: se vuelve a pedir todo
        ges = ges.iloc[:0].assign(gestionada=None); ges_hechos_reset = True
    else:
        ges_hechos_reset = False
    ges_hechos = _leer("gestiones_pares", ["credito", "mes"])
    if ges_hechos_reset:
        ges_hechos = ges_hechos.iloc[:0]
    for df in (ges, ges_hechos):
        df["credito"] = df["credito"].astype(object); df["mes"] = df["mes"].astype(object)
    mes_hoy = hoy.to_period("M")
    vivos = {str(mes_hoy), str(mes_hoy - 1)}
    ges = ges[~ges["mes"].isin(vivos)]; ges_hechos = ges_hechos[~ges_hechos["mes"].isin(vivos)]
    pares = []
    for c, a, z in zip(u["credito"], u["D"] - pd.Timedelta(days=ANTES), u["hasta"]):
        for p in pd.period_range(a.to_period("M"), z.to_period("M"), freq="M"):
            pares.append((c, str(p)))
    pares = pd.DataFrame(pares, columns=["credito", "mes"]).drop_duplicates()
    falta = pares.merge(ges_hechos.assign(_h=1), on=["credito", "mes"], how="left")
    falta = falta[falta["_h"].isna()][["credito", "mes"]]
    if len(falta):
        cur.execute("CREATE TABLE #g (credito VARCHAR(30), mes CHAR(7))")
        lista = list(falta.itertuples(index=False, name=None))
        for j in range(0, len(lista), 5000):
            cur.executemany("INSERT INTO #g VALUES (?, ?)", lista[j:j + 5000])
        nuevas = []
        for m in sorted(falta["mes"].unique()):
            p = pd.Period(m)
            cur.execute(f"""SELECT REPLACE(RTRIM(G.credito), '_', ' ') credito, G.fecha_actividad fa, RTRIM(G.codigo_accion) acc,
                   RTRIM(G.codigo_resultado) res, G.usuario, G.fecha_promesa fprom, G.monto_promesa, C.gestionada, C.contacto, C.rpc, C.promesa
                FROM [MCCOLLECT].[dbo].[th_mccollect_gestiones_diarias_regional] G
                OUTER APPLY (SELECT TOP 1 gestionada, contacto, rpc, promesa FROM [MCCOLLECT].[dbo].[t_mccollect_codigos_gestiones] K
                             WHERE K.id_concatenado = CONCAT(G.codigo_accion, G.codigo_resultado)) C
                WHERE G.pais = 'Nicaragua' AND G.fecha_actividad >= '{p.start_time:%Y-%m-%d}' AND G.fecha_actividad < '{(p + 1).start_time:%Y-%m-%d}'
                  AND REPLACE(RTRIM(G.credito), '_', ' ') IN (SELECT credito FROM #g WHERE mes = '{m}')""")
            x = _filas(cur); x["mes"] = m; nuevas.append(x)
        cur.execute("DROP TABLE #g")
        n = pd.concat(nuevas, ignore_index=True)
        ges = pd.concat([ges, n], ignore_index=True)
        ges = ges.drop_duplicates(["credito", "fa", "acc", "res", "usuario"])
        ges_hechos = pd.concat([ges_hechos, falta], ignore_index=True)
        _guardar(ges, "gestiones"); _guardar(ges_hechos, "gestiones_pares")
        logging.info("Seguimiento PP: gestiones %s meses, %s filas (%.0f s)", falta["mes"].nunique(), f"{len(n):,}", reloj.time() - t1)

    # 3) Cendoc en cada fecha de corte (la última foto disponible hasta el corte)
    t2 = reloj.time()
    cen = _leer("cendoc", ["credito", "f", "rodamiento", "corte"])
    cen = cen[~cen["corte"].isin([str(hoy.date()), str((hoy - pd.Timedelta(days=1)).date())])]
    nuevas = []
    pedir = {}
    for m in meses:
        for k in ("foto_dia", "foto_cierre"):
            c = cts[m][k]
            disp = fechas_cendoc[fechas_cendoc <= c]
            if len(disp):
                pedir.setdefault(disp[-1], set()).update(u.loc[u["mes_cobro"] == m, "credito"])
    for f, creds in pedir.items():
        clave = str(f.date())
        ya = set(cen.loc[cen["corte"] == clave, "credito"])
        faltan = sorted(creds - ya)   # los ya pedidos sin dato quedan guardados con rodamiento vacío: no se repiten
        if not faltan:
            continue
        cur.execute("CREATE TABLE #c (credito VARCHAR(30))")
        cur.executemany("INSERT INTO #c VALUES (?)", [(c,) for c in faltan])
        cur.execute(f"""SELECT RTRIM(c.dco_credito) credito, CAST(c.f_reporte AS DATE) f, RTRIM(c.dco_rodamiento) rodamiento
            FROM [CENDOC].[dbo].[th_cendoc_diario_regional] c
            WHERE c.pais = 'Nicaragua' AND c.f_reporte = '{clave}' AND RTRIM(c.dco_credito) IN (SELECT credito FROM #c)""")
        x = _filas(cur); x["corte"] = clave
        sin = sorted(set(faltan) - set(x["credito"]))
        if sin:   # pedidos y no encontrados en Cendoc: se guardan para no volver a pedirlos cada día
            x = pd.concat([x, pd.DataFrame({"credito": sin, "f": f.date(), "rodamiento": None, "corte": clave})], ignore_index=True)
        nuevas.append(x)
        cur.execute("DROP TABLE #c")
    if nuevas:
        cen = pd.concat([cen, *nuevas], ignore_index=True).drop_duplicates(["credito", "corte"], keep="last")
        _guardar(cen, "cendoc")
        logging.info("Seguimiento PP: Cendoc %s fechas (%.0f s)", len(nuevas), reloj.time() - t2)
    cn.close()
    ges = ges[~ges["usuario"].astype(str).str.strip().str.lower().isin(USUARIOS_EXCLUIDOS)]
    return car, ges, cen, ult_car, fechas_cendoc


# ---------------------------------------------------------------- indicadores por crédito
def _canal(acc: pd.Series, res: pd.Series) -> np.ndarray:
    return np.select(
        [(acc == "OTR") & (res == "SMS"), acc == "MPD", (acc == "OTR") & (res == "CEV"), acc == "VCD",
         acc.isin(["TMC", "TCC", "TTC", "LLC"]), acc.isin(["TRE", "TOT", "LLT"]), acc == "WAP"],
        ["SMS", "PREDICTIVO", "ENVIO_VISITA", "VISITA", "LLAMADA_CLIENTE", "LLAMADA_REFERENCIA", "WHATSAPP"], "OTRO")


def calcular(u: pd.DataFrame, car: pd.DataFrame, ges: pd.DataFrame, cen: pd.DataFrame, meses: list[str], cts: dict,
             hoy: pd.Timestamp, ult_car: pd.Timestamp, fechas_cendoc: pd.DatetimeIndex, U: int = 1) -> pd.DataFrame:
    """U = cuotas vencidas para estar "en mora" en esta medición: n para el nPD; 1 para la mora por cuota."""
    u = u.copy().reset_index()   # 'index' = fila de la base (para la descarga)
    # tipos uniformes para los cruces (texto como object, fechas en ns)
    u["credito"] = u["credito"].astype(object); u["D"] = pd.to_datetime(u["D"]).astype("datetime64[ns]")
    car = car.copy(); car["credito"] = car["credito"].astype(object)
    ges = ges.copy(); ges["credito"] = ges["credito"].astype(object)
    cen = cen.copy(); cen["credito"] = cen["credito"].astype(object)
    u["due_b"] = bpos(u["D"])

    # Estado diario: cuotas vencidas por (crédito, fecha). Una foto consultada sin el crédito = ya no está en cobro (0).
    S = car[["credito", "f", "cv"]].copy()
    S["f"] = pd.to_datetime(S["f"]).astype("datetime64[ns]"); S["cv"] = pd.to_numeric(S["cv"], errors="coerce").fillna(0)
    pares = _leer("cartera_pares", ["credito", "f"]); pares["f"] = pd.to_datetime(pares["f"]).astype("datetime64[ns]")
    pares["credito"] = pares["credito"].astype(object)
    S = pares.merge(S, on=["credito", "f"], how="left").fillna({"cv": 0})
    S = S[S["credito"].isin(set(u["credito"]))]
    S["credito"] = S["credito"].astype(object); S["f"] = pd.to_datetime(S["f"]).astype("datetime64[ns]")
    S = S.sort_values("f")

    def cv_en(creditos, fechas, limite=None, tolerancia=3):
        """Cuotas vencidas en la primera foto >= fecha (hasta 'tolerancia' días); NaN si no hay foto o pasa del límite."""
        t = pd.DataFrame({"credito": np.asarray(creditos, dtype=object), "f": pd.DatetimeIndex(fechas).astype("datetime64[ns]"), "_i": np.arange(len(creditos))})
        t["credito"] = t["credito"].astype(S["credito"].dtype)
        m = pd.merge_asof(t.sort_values("f"), S.rename(columns={"f": "fs"}).assign(f=lambda d: d["fs"]), on="f", by="credito",
                          direction="forward", tolerance=pd.Timedelta(days=tolerancia)).sort_values("_i")
        v = np.array(m["cv"], dtype=float)
        if limite is not None:
            v[(m["fs"].to_numpy() > np.asarray(pd.DatetimeIndex(limite))) | m["fs"].isna().to_numpy()] = np.nan
        return v

    def cv_al(creditos, fechas):
        """Cuotas vencidas en la última foto <= fecha (estado al corte)."""
        t = pd.DataFrame({"credito": np.asarray(creditos, dtype=object), "f": pd.DatetimeIndex(fechas).astype("datetime64[ns]"), "_i": np.arange(len(creditos))})
        t["credito"] = t["credito"].astype(S["credito"].dtype)
        m = pd.merge_asof(t.sort_values("f"), S, on="f", by="credito", direction="backward",
                          tolerance=pd.Timedelta(days=4)).sort_values("_i")
        return np.array(m["cv"], dtype=float)

    # Gestiones del universo
    G = ges.copy()
    G["fa"] = pd.to_datetime(G["fa"]); G["d"] = G["fa"].dt.normalize()
    G["canal"] = _canal(G["acc"].fillna("").str.strip(), G["res"].fillna("").str.strip())
    for c in ["gestionada", "contacto", "rpc", "promesa"]:
        G[c] = pd.to_numeric(G[c], errors="coerce").fillna(0)
    G["fprom"] = pd.to_datetime(G["fprom"], errors="coerce").dt.normalize()
    G = G.merge(u[["credito", "D", "due_b"]], on="credito")
    G = G[(G["d"] >= G["D"] - pd.Timedelta(days=ANTES)) & (G["d"] <= G["D"] + pd.Timedelta(days=DESPUES))]
    G["b"] = bpos(G["d"]); G["relb"] = G["b"] - G["due_b"]; G["rel"] = (G["d"] - G["D"]).dt.days
    # gestión de cobro = la de los gestores, como el informe 1PD (sin SMS masivos ni marcación predictiva automática;
    # el predictivo se mide aparte en la regla de cobro FPD); telefónica = gestión que no es visita de campo
    G["gestion"] = ~G["canal"].isin(["SMS", "PREDICTIVO"])
    G["tel"] = G["gestion"] & (G["canal"] != "VISITA")
    G["prom"] = (G["promesa"] == 1) & G["fprom"].notna() & (G["fprom"] >= G["d"])
    G["fpb"] = np.where(G["prom"], bpos(G["fprom"].fillna(pd.Timestamp("2000-01-01"))), -1)

    # Pagos: fechas de último pago vistas en las fotos (eventos de pago)
    P = car[["credito", "fup", "mup"]].copy()
    P["fup"] = pd.to_datetime(P["fup"], errors="coerce").dt.normalize(); P["mup"] = pd.to_numeric(P["mup"], errors="coerce")
    P = P[P["fup"].notna() & (P["mup"] > 0)].drop_duplicates(["credito", "fup"])
    P["pb"] = bpos(P["fup"])

    out = u[["index", "credito", "D", "mes_cobro", "w", "due_b", *[c for c in DIMS if c in u]]].copy()
    out["dia_vence"] = out["D"].dt.strftime("%Y-%m-%d")
    rod_por_corte = {(r.credito, r.corte): r.rodamiento for r in cen.itertuples(index=False)}

    for k in ["dia", "cierre"]:
        C = pd.to_datetime(out["mes_cobro"].map({m: cts[m][k] for m in meses})).astype("datetime64[ns]")
        F = pd.to_datetime(out["mes_cobro"].map({m: cts[m]["foto_" + k] for m in meses})).astype("datetime64[ns]")
        C_car = F.clip(upper=ult_car)                       # foto del corte (o la más reciente que existe)
        CB = bpos(C)
        # al cierre entran todas las cuotas del mes (las que vencen el último día se leen en la foto del día 1);
        # a la misma fecha, las que ya vencieron antes del corte
        en_curso = out["mes_cobro"] == meses[-1]
        incl = (out["D"] <= C) & ~en_curso if k == "cierre" else out["D"] < C
        incl = incl | (en_curso & (out["D"] < C))
        pre = f"{k[0]}_"
        out[pre + "incl"] = incl.astype(int)
        cvC = cv_al(out["credito"], C_car)
        out[pre + "pd"] = np.where(incl, (cvC >= U).astype(float), np.nan)
        out[pre + "cv"] = np.where(incl, cvC, np.nan)

        def obs_cv(desp):
            pos = out["due_b"].to_numpy() + desp
            fechas = BDAYS[np.minimum(pos, len(BDAYS) - 1)]
            v = cv_en(out["credito"], fechas, limite=C_car)
            v[(fechas > C_car) | ~incl.to_numpy()] = np.nan
            return v
        cv1, cv3, cv6 = obs_cv(1), obs_cv(3), obs_cv(6)
        mora1 = cv1 >= U
        out[pre + "m1"] = np.where(np.isnan(cv1), np.nan, mora1.astype(float))
        out[pre + "m5"] = np.where(np.isnan(cv6), np.nan, (cv6 >= U).astype(float))
        out[pre + "pago2"] = np.where(mora1 & ~np.isnan(cv3), (cv3 < U).astype(float), np.nan)

        Gk = G.merge(pd.DataFrame({"credito": out["credito"], "_C": C}), on="credito")
        Gk = Gk[Gk["d"] <= Gk["_C"]]
        gg = Gk[Gk["gestion"]]
        tiene = lambda df: out["credito"].isin(set(df["credito"])).astype(float)
        out[pre + "prev"] = np.where(incl, tiene(gg[gg["relb"].between(-3, -1)]), np.nan)
        out[pre + "gd1"] = np.where(mora1, tiene(gg[gg["relb"] == 1]), np.nan)
        out[pre + "tel12"] = np.where(mora1, tiene(Gk[Gk["tel"] & Gk["relb"].between(1, 2)]), np.nan)

        # Panel de días en mora (hasta 15 días hábiles, antes del corte)
        M = out.loc[mora1, ["credito", "due_b", "w"]]
        filas = []
        for j in range(1, VENT + 1):
            t = M.copy(); t["b"] = t["due_b"] + j; filas.append(t)
        Dm = pd.concat(filas, ignore_index=True) if filas else pd.DataFrame(columns=["credito", "due_b", "w", "b"])
        Dm = Dm.merge(pd.DataFrame({"credito": out["credito"], "_CB": CB, "_C": C_car}), on="credito")
        Dm = Dm[Dm["b"] < Dm["_CB"]]
        Dm["cv"] = cv_en(Dm["credito"], BDAYS[np.minimum(Dm["b"].to_numpy(), len(BDAYS) - 1)], limite=Dm["_C"])
        # primer día hábil de mora en que ya no está en mora (pagó): para el parámetro de intensidad de las que pagan
        Dp = Dm[(Dm["cv"] < U) & (Dm["b"] > Dm["due_b"] + 1)]
        dpago = (Dp.groupby("credito")["b"].min() - Dp.groupby("credito")["due_b"].first()).reindex(out["credito"]).to_numpy(dtype=float)
        Dm = Dm[Dm["cv"] >= U]
        ng = gg.groupby(["credito", "b"]).size()
        Dm["ng"] = ng.reindex(pd.MultiIndex.from_arrays([Dm["credito"], Dm["b"]])).fillna(0).to_numpy()
        act = set()
        for c, b0, b1 in Gk.loc[Gk["prom"], ["credito", "b", "fpb"]].itertuples(index=False):
            for bb in range(int(b0) + 1, int(b1) + 1):
                act.add((c, bb))
        Dm["activa"] = [(c, bb) in act for c, bb in zip(Dm["credito"], Dm["b"])]
        sp, ca = Dm[~Dm["activa"]], Dm[Dm["activa"]]
        cnt = lambda df, col=None: (df.groupby("credito").size() if col is None else df.groupby("credito")[col].sum()).reindex(out["credito"]).fillna(0).to_numpy()
        out[pre + "dmora"] = np.where(mora1, cnt(Dm), np.nan)
        out[pre + "dsp"] = np.where(mora1, cnt(sp), np.nan)
        out[pre + "dsp2"] = np.where(mora1, cnt(sp[sp["ng"] >= 2]), np.nan)
        out[pre + "dsp0"] = np.where(mora1, cnt(sp[sp["ng"] == 0]), np.nan)
        out[pre + "dca"] = np.where(mora1, cnt(ca), np.nan)
        out[pre + "gca"] = np.where(mora1, cnt(ca, "ng"), np.nan)
        # gestiones con la cuenta en mora (días 1 a 15)
        dias_m = set(zip(Dm["credito"], Dm["b"]))
        GM = gg[gg["relb"].between(1, VENT)]
        GM = GM[[(c, bb) in dias_m for c, bb in zip(GM["credito"], GM["b"])]]
        out[pre + "gm"] = np.where(mora1, cnt(GM), np.nan)
        out[pre + "gmc"] = np.where(mora1, cnt(GM, "contacto"), np.nan)   # contactos en mora
        out[pre + "gmr"] = np.where(mora1, cnt(GM, "rpc"), np.nan)        # RPC en mora
        # gestiones de gestor antes de pagar (desde el día 1 de mora hasta el día anterior al pago)
        out[pre + "dpago"] = np.where(mora1, dpago, np.nan)
        lim = pd.Series(np.where(np.isnan(dpago), VENT + 1, dpago), index=out["credito"].to_numpy())
        GP = gg[gg["relb"] >= 1].copy(); GP["_l"] = GP["credito"].map(lim); GP = GP[GP["relb"] < GP["_l"]]
        out[pre + "gpp"] = np.where(mora1, cnt(GP), np.nan)
        out[pre + "cpp"] = np.where(mora1, cnt(GP, "contacto"), np.nan)
        out[pre + "rpp"] = np.where(mora1, cnt(GP, "rpc"), np.nan)
        con_dias = out["credito"].isin(set(Dm["credito"]))
        out[pre + "sing"] = np.where(mora1 & con_dias, (~out["credito"].isin(set(GM["credito"]))).astype(float), np.nan)
        # promesas hechas en mora y su cumplimiento (pago entre la gestión y la fecha prometida + 1 día hábil)
        PM = Gk[Gk["prom"] & Gk["relb"].between(1, VENT) & Gk["credito"].isin(set(out.loc[mora1, "credito"]))].copy()
        PM["plazo"] = (PM["fpb"] - PM["b"]).clip(lower=0)
        PM["vencida"] = BDAYS[np.minimum(PM["fpb"] + 1, len(BDAYS) - 1)] <= PM["_C"]
        x = PM.reset_index()[["index", "credito", "b", "fpb"]].merge(P[["credito", "pb"]], on="credito")
        okp = set(x[(x["pb"] >= x["b"]) & (x["pb"] <= x["fpb"] + 1)]["index"])
        PM["cumple"] = PM.index.isin(okp)
        ev = PM[PM["vencida"]]
        out[pre + "prn"] = np.where(mora1, cnt(PM), np.nan)
        out[pre + "prplazo"] = np.where(mora1, cnt(PM, "plazo"), np.nan)
        out[pre + "prev_n"] = np.where(mora1, cnt(ev), np.nan)
        out[pre + "prok"] = np.where(mora1, cnt(ev[ev["cumple"]]), np.nan)
        # visitas en mora y contacto del titular
        vis = GM[GM["canal"] == "VISITA"]
        out[pre + "visg"] = np.where(mora1, cnt(vis), np.nan)
        out[pre + "visrpc"] = np.where(mora1, cnt(vis, "rpc"), np.nan)
        rpc_tel = set(Gk.loc[Gk["tel"] & (Gk["rpc"] == 1), "credito"])
        pdk = out[pre + "pd"] == 1
        out[pre + "sintel"] = np.where(pdk, (~out["credito"].isin(rpc_tel)).astype(float), np.nan)
        # gestiones del ciclo (desde 3 días hábiles antes) para la lista de cuentas
        ciclo = gg[gg["relb"] >= -3]
        out[pre + "ng"] = cnt(ciclo)
        out[pre + "nprom"] = cnt(ciclo[ciclo["prom"]])
        out[pre + "nvis"] = cnt(ciclo[ciclo["canal"] == "VISITA"])
        out[pre + "rpc"] = out["credito"].isin(set(ciclo.loc[ciclo["rpc"] == 1, "credito"])).astype(int)

        # Reglas de cobro FPD (días calendario, como el documento): solo cuentas en mora al día siguiente del vencimiento
        relc = Gk.groupby("credito")
        def regla(mask_g, desde, hasta=None):
            x = Gk[mask_g & (Gk["rel"] >= desde) & ((Gk["rel"] <= hasta) if hasta is not None else True)]
            return out["credito"].isin(set(x["credito"])).astype(float)
        dia1 = mora1 & (out["D"] + pd.Timedelta(days=1) <= C)
        out[pre + "r_pred"] = np.where(dia1, regla(Gk["canal"] == "PREDICTIVO", 0, 2), np.nan)
        out[pre + "r_fila"] = np.where(dia1, regla(Gk["canal"] == "LLAMADA_CLIENTE", 1, 2), np.nan)
        out[pre + "r_gestor"] = np.where(dia1, regla(Gk["canal"].isin(["LLAMADA_CLIENTE", "LLAMADA_REFERENCIA", "WHATSAPP"]), 1), np.nan)
        cv5 = cv_en(out["credito"], out["D"] + pd.Timedelta(days=5), limite=C_car)
        cv5[(out["D"] + pd.Timedelta(days=5) > C).to_numpy()] = np.nan
        out[pre + "r_ref"] = np.where(mora1 & (cv5 >= U), regla(Gk["canal"] == "LLAMADA_REFERENCIA", 5), np.nan)
        q1 = out["D"].dt.day <= 15
        prod = out["producto_madre"]
        umbral = pd.Series(np.select([prod == "MOTO", (prod == "PYME") & q1, prod == "PYME", prod.isin(["PERS", "PENS"]) & q1,
                                      prod.isin(["PERS", "PENS"])], [5, 3, 2, 10, 5], default=np.nan), index=out.index)
        fu = out["D"] + pd.to_timedelta(umbral.fillna(0), unit="D")
        cvu = cv_en(out["credito"], fu, limite=C_car); cvu[(fu > C).to_numpy() | umbral.isna().to_numpy()] = np.nan
        saldo_c = car.assign(f=pd.to_datetime(car["f"])).sort_values("f").groupby("credito")["saldo"].last()
        aplica = mora1 & (cvu >= U) & (pd.to_numeric(out["credito"].map(saldo_c), errors="coerce").fillna(0) >= SALDO_VISITA)
        v = Gk[Gk["canal"].isin(["ENVIO_VISITA", "VISITA"])].merge(pd.DataFrame({"credito": out["credito"], "_u": umbral}), on="credito")
        out[pre + "r_vis"] = np.where(aplica, out["credito"].isin(set(v.loc[v["rel"] >= v["_u"], "credito"])).astype(float), np.nan)

        # Embudo de cobranza de las cuentas en mora (desde el día 1 de mora hasta el corte) y efectividad por canal.
        # Todas las gestiones cuentan aquí (también SMS y predictivo): se quiere ver qué canal llega a RPC, promesa y pago.
        Ge = Gk[Gk["relb"] >= 1].copy()
        Ge["_cump"] = False
        if Ge["prom"].any():
            x = Ge[Ge["prom"]].reset_index()[["index", "credito", "b", "fpb"]].merge(P[["credito", "pb"]], on="credito")
            Ge.loc[Ge.index.isin(set(x[(x["pb"] >= x["b"]) & (x["pb"] <= x["fpb"] + 1)]["index"])), "_cump"] = True
        en_mora = mora1
        def marca(df):
            return np.where(en_mora, out["credito"].isin(set(df["credito"])).astype(float), np.nan)
        out[pre + "e_gest"] = marca(Ge)
        out[pre + "e_int"] = marca(Ge[Ge["gestionada"] == 1])
        out[pre + "e_con"] = marca(Ge[Ge["contacto"] == 1])
        out[pre + "e_rpc"] = marca(Ge[Ge["rpc"] == 1])
        out[pre + "e_prom"] = marca(Ge[Ge["prom"]])
        out[pre + "e_cump"] = marca(Ge[Ge["_cump"]])
        out[pre + "e_pago"] = np.where(en_mora & incl, (out[pre + "pd"] == 0).astype(float), np.nan)
        for ch, canales in CANALES.items():
            gc = Ge[Ge["canal"].isin(canales)]
            out[f"{pre}k_{ch}_u"] = marca(gc)
            out[f"{pre}k_{ch}_r"] = marca(gc[gc["rpc"] == 1])
            out[f"{pre}k_{ch}_p"] = marca(gc[gc["prom"]])
            out[f"{pre}k_{ch}_c"] = marca(gc[gc["_cump"]])

        if k == "dia":
            # Intensidad al corte de cada cuenta: gestiones de gestor desde el día siguiente al vencimiento
            gi = gg[gg["relb"] >= 1]
            out["i_gest"] = cnt(gi); out["i_con"] = cnt(gi, "contacto"); out["i_rpc"] = cnt(gi, "rpc")
            out["i_gdv"] = cnt(gg[gg["relb"] == 0])
            ug = gg[gg["relb"] >= -3].sort_values("fa").groupby("credito")["usuario"].last()
            out["i_gestor"] = out["credito"].map(ug).fillna("SIN GESTIÓN").astype(str).str.strip().str.lower().to_numpy()
            ultg = gg[gg["relb"] >= -3].groupby("credito")["b"].max().reindex(out["credito"]).to_numpy(dtype=float)
            out["i_dias"] = np.maximum(CB - out["due_b"].to_numpy() - 1, 0)
            out["i_dsg"] = np.where(np.isnan(ultg), out["i_dias"], np.maximum(CB - ultg - 1, 0))
            pr = Gk[(Gk["promesa"] == 1) & Gk["fprom"].notna()].groupby("credito")["fprom"].max()
            out["i_fprom"] = out["credito"].map(pr).to_numpy()
            out["i_corte"] = C.to_numpy()

        # Cendoc: rodamiento a la fecha de corte
        disp = {m: fechas_cendoc[fechas_cendoc <= cts[m]["foto_" + k]] for m in meses}
        corte_cen = out["mes_cobro"].map({m: (str(d[-1].date()) if len(d) else None) for m, d in disp.items()})
        out[pre + "rod"] = [rod_por_corte.get((c, f)) if f else None for c, f in zip(out["credito"], corte_cen)]
        out[pre + "rod"] = np.where(incl, pd.Series(out[pre + "rod"]).fillna("SIN DATO"), None)
    return out


# ---------------------------------------------------------------- intensidad de gestión (cuentas sin gestión efectiva)
def parametro_intensidad(t: pd.DataFrame, actual: str) -> dict:
    """Parámetro con lo que recibieron las cuentas que cayeron en mora y pagaron con gestión (meses cerrados, al cierre).
    Ritmo mínimo = gestiones por día hábil en mora que alcanzaron 3 de cada 4 de esas cuentas (percentil 25).
    Contactos y RPC: con 2 o más contactos y RPC en los primeros 3 días el pago sube de 67% a 76-80% (análisis 19-nov-2026)."""
    h = t[(t["mes_cobro"] < actual) & (t["c_m1"] == 1)]
    pg = h[h["c_dpago"].notna() & (h["c_gpp"] > 0)]
    P = {"ritmo_min": 0.5, "contactos_min": 2, "rpc_min": 1, "dias_min": 3, "n": int(len(pg)), "cuentas_mora": int(len(h))}
    if len(pg) < 50:
        return P
    ritmo = pg["c_gpp"] / (pg["c_dpago"] - 1).clip(lower=1)
    P.update({"ritmo_min": round(float(ritmo.quantile(0.25)), 1), "ritmo_mediana": round(float(ritmo.median()), 1),
              "pagaron_pct": round(100 * float(h["c_dpago"].notna().mean()), 1),
              "med_dia_pago": float(pg["c_dpago"].median()), "med_gest": float(pg["c_gpp"].median()),
              "med_contactos": float(pg["c_cpp"].median()), "med_rpc": float(pg["c_rpp"].median()),
              "p75_gest": float(pg["c_gpp"].quantile(0.75)), "p75_contactos": float(pg["c_cpp"].quantile(0.75)),
              "p75_rpc": float(pg["c_rpp"].quantile(0.75))})
    return P


def intensidad(t: pd.DataFrame, actual: str, P: dict) -> pd.DataFrame:
    """Cuentas del mes en curso en mora al corte: gestión efectiva o insuficiente según el parámetro, con el motivo."""
    x = t[(t["mes_cobro"] == actual) & (t["d_pd"] == 1)].copy()
    vig = (pd.to_datetime(x["i_fprom"]) >= pd.to_datetime(x["i_corte"])).to_numpy()
    dias = x["i_dias"].astype(float).to_numpy()
    ritmo = x["i_gest"].to_numpy() / np.maximum(dias, 1)
    mot = []
    for g, r, rp, co, d, ds, v, fp in zip(x["i_gest"], ritmo, x["i_rpc"], x["i_con"], dias, x["i_dsg"], vig, x["i_fprom"]):
        m = []
        if g == 0 and not v:
            m.append("Sin gestión de gestor desde que cayó en mora" + (" (promesa rota)" if pd.notna(fp) else ""))
        elif g > 0 and d >= 1 and r < P["ritmo_min"] and not v:   # con promesa vigente no se espera insistir
            m.append(f"Ritmo bajo ({r:.1f} gestiones por día; mínimo {P['ritmo_min']:.1f})")
        if d >= P["dias_min"] and rp < P["rpc_min"]:
            m.append("Sin contacto con el titular")
        if d >= P["dias_min"] and co < P["contactos_min"] and not v:
            m.append(f"Menos de {P['contactos_min']} contactos")
        if ds >= 2 and not v:
            m.append(f"{int(ds)} días hábiles sin gestión y sin promesa vigente")
        mot.append("; ".join(m))
    x["int_motivo"] = mot
    x["int_estado"] = np.where(x["int_motivo"] == "", "Gestión efectiva", "Gestión insuficiente")
    x["int_prioridad"] = np.select([(x["i_gest"].to_numpy() == 0) & ~vig, (x["i_rpc"].to_numpy() == 0) & (dias >= P["dias_min"]),
                                    x["int_motivo"].to_numpy() != ""], ["1 Alta", "2 Media", "3 Baja"], "")
    x["int_prom_vig"] = np.where(vig, "Sí", "No")
    x["int_fprom"] = pd.to_datetime(x["i_fprom"]).dt.strftime("%Y-%m-%d")
    x["int_ritmo"] = np.round(ritmo, 2)
    x = x.rename(columns={"i_gestor": "int_gestor", "i_gest": "int_gest", "i_con": "int_con", "i_rpc": "int_rpc", "i_gdv": "int_gdv", "i_dias": "int_dias",
                          "i_dsg": "int_dsg"})
    return x[["credito", "int_estado", "int_prioridad", "int_gestor", "int_motivo", "int_dias", "int_gest", "int_gdv", "int_con", "int_rpc",
              "int_ritmo", "int_dsg", "int_prom_vig", "int_fprom"]]


def generar(cfg: dict, b: pd.DataFrame, hoy) -> dict:
    """Tablas por cuota (1 a 6): "pd" = nPD (debe n cuotas) y "mc" = mora por cuota (no pagó la cuota n; desde la 2);
    una fila por cuota con sus indicadores a la misma fecha y al cierre. Además, la intensidad de gestión de las cuentas
    del mes en curso en 1PD (pestaña Primeros Pagos)."""
    hoy = pd.Timestamp(hoy).normalize()
    t0 = reloj.time()
    us = {}
    for n in PDS:
        us[n], meses = universo(b, hoy, n)
    cts = cortes(meses, hoy)
    car, ges, cen, ult_car, fechas_cendoc = extraer(cfg, pd.concat(us.values()), meses, cts, hoy)
    tablas = {}
    for n, u in us.items():
        for tipo, U in (("pd", n), ("mc", 1)):
            if tipo == "mc" and n == 1:
                continue   # la mora de la cuota 1 es el 1PD
            t1 = reloj.time()
            tablas[(tipo, n)] = calcular(u, car, ges, cen, meses, cts, hoy, ult_car, fechas_cendoc, U=U)
            logging.info("Seguimiento PP: %s cuotas %s%s (%.0f s)", f"{len(tablas[(tipo, n)]):,}", n,
                         "PD" if tipo == "pd" else " mora por cuota", reloj.time() - t1)
    t1pd = tablas[("pd", 1)]
    t1pd = t1pd[t1pd["producto_madre"] != "CONV"]   # Convenio se cobra por planilla: fuera del parámetro de gestión
    P = parametro_intensidad(t1pd, meses[-1])
    inten = intensidad(t1pd, meses[-1], P)
    logging.info("Seguimiento PP: listo en %.0f s; intensidad: %s de %s cuentas en 1PD con gestión insuficiente",
                 reloj.time() - t0, int((inten["int_estado"] == "Gestión insuficiente").sum()), len(inten))
    meta = {"meses": meses, "hoy": str(hoy.date()), "foto_mccollect": str(ult_car.date()),
            "fotos": {m: {k: str(cts[m]["foto_" + k].date()) for k in ("dia", "cierre")} for m in meses},
            "foto_cendoc": str(fechas_cendoc[-1].date()) if len(fechas_cendoc) else None,
            "cortes": {m: {k: str(c[k].date()) for k in ("dia", "cierre")} for m, c in cts.items()},
            "intensidad": P}
    return {"tablas": tablas, "meta": meta, "intensidad": inten, "param": P}
