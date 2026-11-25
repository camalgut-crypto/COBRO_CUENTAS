"""Salidas del módulo a partir de la base:
- Un archivo por pestaña (columnar, dimensiones codificadas) para que la app arme gráficos y filtros.
  Cada pestaña es un archivo aparte para que Supabase entregue a cada perfil solo lo que puede ver.
- Resumen para la herramienta de preguntas (IA), por sección.
- Excel con la base completa para el botón de descarga.
"""
import gzip
import io
import json
from datetime import date, datetime

import numpy as np
import pandas as pd

DIMS = ["mes_desembolso", "sucursal", "canal", "sucursal_promotor", "promotor", "producto_comercial", "producto_motor",
        "clasificacion", "categorizacion", "tipo_credito", "medio_captacion", "rango_score", "rango_desembolso",
        "rango_salario", "rango_edad", "rango_multiplicador", "rango_antig_cliente", "rango_antig_credito",
        "rango_antig_laboral", "rango_capacidad", "rango_ingreso", "rango_estabilidad", "rango_edad_motor", "perfil_motor",
        "politica_hit", "genero", "plazo", "empleo_inss", "mora", "rodamiento", "tipo_cartera", "tipo_pago", "pago_mes",
        "estado_promesa", "ult_resultado", "gestor", "estado_primer_pago", "tipo_credito_legal",
        # filtros definidos por Riesgo el 17-nov-2026 (campos verdes y azules del reporte)
        "producto_madre", "resultado_motor", "status_promesa_pago", "dealer_genesis", "suc_dealer", "con_excepcion",
        "con_prima", "dia_pago", "tipo_salario"]
MEDIDAS = ["monto_des", "saldopagare", "saldo_doc", "dias_mora", "cuotas_vencidas", "valor_vencido", "cuotas_pagas",
           # para "Arme su gráfico o tabla" (suma y promedio)
           "valor_cuota", "salario", "score", "tasainteres", "monto_ult_pago", "capacidad_pago", "ingreso_bruto", "edad",
           "multiplicador", "salario_inss", "porcentaje_financiar", "razon_cuota_ingreso", "monto_aprobado_motor",
           "intentos", "gestionada", "contacto", "rpc", "promesa", "monto_promesa", "monto_pagado"]
PP_DETALLE = ["credito", "nombre_deudor", "telefono", "cargo", "f_desembolso", "f_promesa"]
REGLAS_FPD = ["fpd_estado", "rg_predictivo", "rg_fila", "rg_gestor", "rg_referencias", "rg_visita"]
PESTANAS = ("cosecha", "cartera_activa", "primeros_pagos", "cono")
MORA30 = ["B2", "B3", "B4", "B5", "B6", "B7"]
MORA90 = ["B4", "B5", "B6", "B7"]


def _columnar(df: pd.DataFrame, dims: list[str], medidas: list[str], extra: dict | None = None) -> dict:
    """{n, dic: {dim: [valores]}, datos: {col: [códigos o números]}}: compacto y rápido de filtrar en el navegador."""
    out = {"n": len(df), "dic": {}, "datos": {}}
    for c in dims:
        s = df[c].astype("object").where(df[c].notna(), None)
        cat = pd.Categorical(s)
        out["dic"][c] = [str(v) for v in cat.categories]
        out["datos"][c] = [None if k < 0 else int(k) for k in cat.codes]
    for c in medidas:
        v = pd.to_numeric(df[c], errors="coerce").round(2)
        out["datos"][c] = [None if pd.isna(x) else (int(x) if float(x).is_integer() else float(x)) for x in v]
    if extra:
        out.update(extra)
    return out


def _agrupar(df: pd.DataFrame, por: list[str], sumas: list[str]) -> dict:
    g = df.groupby(por, dropna=False)
    t = g.size().rename("n").to_frame().join(g[sumas].sum()).reset_index()
    return _columnar(t, por, ["n"] + sumas)


def _med(df: pd.DataFrame) -> list[str]:
    return [c for c in MEDIDAS if c in df]


INTENSIDAD = ["int_estado", "int_prioridad", "int_gestor", "int_motivo", "int_prom_vig", "int_fprom"]
INTENSIDAD_MED = ["int_dias", "int_gest", "int_gdv", "int_con", "int_rpc", "int_ritmo", "int_dsg"]


def pestañas(b: pd.DataFrame, g: pd.DataFrame, hoy: date, inten: pd.DataFrame | None = None,
             param: dict | None = None) -> dict[str, dict]:
    b = b.copy()
    b["plazo"] = b["numero_cuotas"].map(lambda v: None if pd.isna(v) else f"{int(v)} cuotas")
    b["dia_pago"] = b["dias_pago"].map(lambda v: None if pd.isna(v) else str(int(v)))
    for c in ["resultado_motor", "status_promesa_pago", "dealer_genesis", "suc_dealer", "tipo_salario"]:
        b[c] = b[c].fillna("SIN DATO") if c in b else "SIN DATO"
    activa = b[b["en_cartera"]]
    pp = b[b["primer_pago_mes"]].copy()
    pp["primera_cuota"] = pp["primera_cuota"].dt.strftime("%Y-%m-%d")
    # detalle de cuentas en mora (cuadro de Primeros Pagos)
    pp["f_desembolso"] = pp["fecha_renov"].dt.strftime("%Y-%m-%d")
    pp["f_promesa"] = pd.to_datetime(pp["fecha_promesa"], errors="coerce").dt.strftime("%Y-%m-%d")
    for c in ["credito", "nombre_deudor", "telefono", "cargo"]:
        pp[c] = pp[c] if c in pp else None
    if "recaudo_total" not in pp:
        pp["recaudo_total"] = np.nan
    # Intensidad de gestión de las cuentas en 1PD (la calcula el seguimiento con el cono histórico)
    if inten is not None and len(inten):
        pp = pp.merge(inten, on="credito", how="left").set_axis(pp.index)
    for c in INTENSIDAD + INTENSIDAD_MED:
        if c not in pp:
            pp[c] = np.nan
    pp["int_estado"] = np.where(pp["producto_madre"].eq("CONV") & pp["int_estado"].isna() & pp["estado_primer_pago"].eq("En mora"),
                                "No aplica (Convenio)", pp["int_estado"])

    # Cono: gestiones del mes (todas, aunque el crédito no sea de la cosecha) y promesas
    g = g.copy()
    g["dia"] = g["fecha_actividad"].dt.strftime("%Y-%m-%d")
    g["de_la_cosecha"] = np.where(g["credito"].isin(set(b["credito"])), "Sí", "No")
    for c in ["usuario", "descripcion_accion", "descripcion_resultado", "tipo_cartera", "estado_promesa", "status_promesa_pago"]:
        g[c] = g[c].fillna("SIN DATO")
    prom = g[g["promesa"] > 0].copy()
    prom["fecha_promesa"] = prom["fecha_promesa"].dt.strftime("%Y-%m-%d").fillna("SIN FECHA")

    return {
        # "fila" = número de fila en la base completa: la descarga filtrada toma esas filas de descargas/base.json.gz
        "cosecha": _columnar(b, DIMS, _med(b), {"fila": [int(i) for i in b.index]}),
        "cartera_activa": _columnar(activa, DIMS, _med(activa), {"fila": [int(i) for i in activa.index]}),
        "primeros_pagos": _columnar(pp, DIMS + ["primera_cuota"] + REGLAS_FPD + PP_DETALLE + INTENSIDAD,
                                    _med(pp) + ["dias_mora_fpd", "recaudo_total"] + INTENSIDAD_MED,
                                    {"fila": [int(i) for i in pp.index], "intensidad_param": param or {}}),
        "cono": {
            "gestiones": _agrupar(g, ["dia", "usuario", "descripcion_accion", "descripcion_resultado", "tipo_cartera",
                                      "de_la_cosecha"], ["gestionada", "contacto", "rpc", "promesa"]),
            "promesas": _agrupar(prom, ["fecha_promesa", "estado_promesa", "status_promesa_pago", "tipo_cartera",
                                        "usuario"], ["monto_promesa", "monto_pagado"]),
        },
    }


# ---------- resumen para la IA ----------
def _indicadores(df: pd.DataFrame, por: str | None, top: int | None = None) -> list[dict]:
    def calc(x: pd.DataFrame) -> dict:
        n, act = len(x), x["en_cartera"].sum()
        return {"creditos": int(n), "monto_desembolsado": round(float(x["monto_des"].sum()), 0),
                "cancelados": int(n - act), "activos": int(act),
                "saldo_activo": round(float(x["saldo_doc"].sum()), 0),
                "pct_al_dia": round(100 * x["mora"].eq("B0").sum() / n, 1) if n else None,
                "pct_mora_30": round(100 * x["mora"].isin(MORA30).sum() / n, 1) if n else None,
                "pct_mora_90": round(100 * x["mora"].isin(MORA90).sum() / n, 1) if n else None,
                "saldo_mora_30": round(float(x.loc[x["mora"].isin(MORA30), "saldo_doc"].sum()), 0)}
    if por is None:
        return [calc(df)]
    filas = [{por: k, **calc(x)} for k, x in df.groupby(por)]
    filas.sort(key=lambda r: -r["creditos"])
    return filas[:top] if top else filas


def resumen_ia(b: pd.DataFrame, g: pd.DataFrame, hoy: date) -> dict:
    activa = b[b["en_cartera"]]
    pp = b[b["primer_pago_mes"]]
    venc = pp[pp["primera_cuota_vencida"]]
    dims_cosecha = ["mes_desembolso", "producto_comercial", "sucursal", "canal", "rango_score", "clasificacion",
                    "categorizacion", "rango_desembolso", "rango_capacidad", "medio_captacion", "plazo"]
    b = b.assign(plazo=b["numero_cuotas"].map(lambda v: None if pd.isna(v) else f"{int(v)} cuotas"))

    def pp_por(por, top=None):
        filas = []
        for k, x in pp.groupby(por):
            v = x[x["primera_cuota_vencida"]]
            filas.append({por: k, "creditos": len(x), "vencidos": len(v),
                          "pagaron": int(x["estado_primer_pago"].eq("Pagó").sum()),
                          "en_mora": int(x["estado_primer_pago"].eq("En mora").sum()),
                          "pct_mora_sobre_vencidos": round(100 * v["estado_primer_pago"].eq("En mora").sum() / len(v), 1) if len(v) else None})
        filas.sort(key=lambda r: -r["creditos"])
        return filas[:top] if top else filas

    cono_tot = g[["gestionada", "contacto", "rpc", "promesa"]].sum()
    por_gestor = g.groupby("usuario").agg(gestiones=("credito", "size"), creditos=("credito", "nunique"),
                                          contactos=("contacto", "sum"), rpc=("rpc", "sum"), promesas=("promesa", "sum"))
    prom = g[g["promesa"] > 0]
    return {
        "fecha_corte": hoy.isoformat(),
        "definiciones": {
            "cosecha": "Créditos desembolsados en los últimos 24 meses (Loan Tape), una fila por crédito.",
            "mora": "Tramo por días de mora hoy (MCCOLLECT): B0 al día, B1 1-30, B2 31-60, B3 61-90, B4 91-120, B5 121-150, "
                    "B6 151-180, B7 más de 180; CANCELADO si el crédito ya no está en la cartera de cobro.",
            "pct_mora_30": "Créditos en B2 a B7 sobre el total de créditos del grupo (incluye cancelados).",
            "pct_mora_90": "Créditos en B4 a B7 sobre el total de créditos del grupo.",
            "primeros_pagos": "Créditos cuya primera cuota vence en el mes en curso; 'vencidos' = la fecha de la primera cuota ya pasó.",
            "cono": "Gestiones de cobro del mes en curso, una por gestión (sin la duplicación Admin/Legal del catálogo).",
        },
        "cosecha": {"total": _indicadores(b, None)[0],
                    **{f"por_{d}": _indicadores(b, d) for d in dims_cosecha},
                    "por_promotor_top40": _indicadores(b, "promotor", 40)},
        "cartera_activa": {
            "total": {"creditos": len(activa), "saldo": round(float(activa["saldo_doc"].sum()), 0)},
            "por_mora": activa.groupby("mora").agg(creditos=("credito", "size"), saldo=("saldo_doc", "sum")).round(0).reset_index().to_dict("records"),
            "por_rodamiento": activa["rodamiento"].value_counts().to_dict(),
            "por_tipo_pago": activa["tipo_pago"].value_counts().to_dict(),
            "por_pago_mes": activa["pago_mes"].value_counts().to_dict(),
            "por_sucursal": _indicadores(activa, "sucursal"),
            "por_producto": _indicadores(activa, "producto_comercial"),
            "por_mes_desembolso": _indicadores(activa, "mes_desembolso"),
        },
        "primeros_pagos": {
            "total": {"creditos": len(pp), "vencidos": len(venc), **pp["estado_primer_pago"].value_counts().to_dict()},
            "por_sucursal": pp_por("sucursal"), "por_canal": pp_por("canal"), "por_producto": pp_por("producto_comercial"),
            "por_promotor_top40": pp_por("promotor", 40), "por_clasificacion": pp_por("clasificacion"),
        },
        "cono": {
            "total": {"gestiones": len(g), "creditos_gestionados": int(g["credito"].nunique()),
                      **{k: int(v) for k, v in cono_tot.items()}},
            "por_gestor_top40": por_gestor.sort_values("gestiones", ascending=False).head(40).reset_index().to_dict("records"),
            "por_resultado_top25": g["descripcion_resultado"].value_counts().head(25).to_dict(),
            "por_tipo_cartera": g.groupby("tipo_cartera").agg(gestiones=("credito", "size"), contactos=("contacto", "sum"),
                                                              promesas=("promesa", "sum")).reset_index().to_dict("records"),
            "promesas_por_estado": prom.groupby("estado_promesa", dropna=False).agg(
                promesas=("credito", "size"), monto_prometido=("monto_promesa", "sum"),
                monto_pagado=("monto_pagado", "sum")).round(0).reset_index().fillna("SIN DATO").to_dict("records"),
        },
    }


# ---------- descarga ----------
COLUMNAS_EXCEL = {  # orden y nombre de las columnas del Excel de descarga (definidos por Riesgo el 17-nov-2026)
    # 'filtro' = campo que se usará como filtro en la app
    "credito": "Crédito",
    "cedula_cliente": "Cédula",
    "nombre_deudor": "Cliente",
    "genero": "Género",
    "edad": "Edad",
    "est_civil": "Estado civil",
    "profesion": "Profesión",
    "sucursal": "Sucursal",
    "nombre_centro": "Centro",
    "producto_madre": "Producto Madre",  # nuevo
    "nombre_mod": "Modalidad",
    "producto_comercial": "Producto comercial",  # filtro
    "fecha_renov": "Fecha desembolso",
    "mes_desembolso": "Mes desembolso",  # filtro
    "primera_cuota": "Primera cuota",
    "fecha_vence": "Fecha vence",
    "numero_cuotas": "Plazo",
    "valor_cuota": "Valor cuota",
    "tasainteres": "Tasa",
    "monto_des": "Monto desembolsado",
    "saldopagare": "Saldo pagaré inicial",
    "ncredxcliente": "Créditos del cliente",
    "dias_pago": "Día de pago",  # filtro
    "salario": "Salario Loan",
    "tiempo_trabajo": "Tiempo trabajo (meses) Loan",
    "dlo": "DLO",
    "num_solicitud": "Solicitud",
    "tipo_credito": "Tipo crédito",
    "promotor": "Promotor",
    "canal": "Canal",  # filtro
    "sucursal_promotor": "Sucursal promotor",  # filtro
    "medio_captacion": "Medio captación",  # filtro
    "score": "Score",
    "dealer_genesis": "Dealer",  # nuevo
    "suc_dealer": "Sucursal dealer",  # filtro
    "con_excepcion": "Con Excepcion",  # nuevo
    "excepcion": "Excepción",
    "motivo_rechazo": "Motivo rechazo",
    "lugar_trabajo": "Lugar de trabajo Genesis",
    "actividad_economica": "Actividad económica",
    "tipo_salario": "Tipo salario",  # filtro
    "capacidad_pago_bitacora": "Capacidad de pago (bitácora)",
    "razon_cuota_ingreso": "Razón cuota ingreso (bitácora)",
    "porcentaje_financiar": "% a financiar",
    "con_prima": "Con Prima",  # nuevo
    "resultado_motor": "Resultado motor",  # filtro
    "perfil_motor": "Perfil motor",
    "politica_hit": "Política HIT",  # filtro
    "ingreso_bruto": "Ingreso bruto",
    "capacidad_pago": "Capacidad de pago",
    "score_tun": "Score TUN",
    "estabilidad_inss": "Estabilidad INSS",
    "edad_motor": "Edad motor",
    "empleo_inss": "En base INSS",  # filtro
    "empresa_inss": "Empresa INSS",
    "salario_inss": "Salario INSS",
    "empleador_inss": "Código empleador",
    "primer_credito": "Primer crédito del cliente",
    "dias_mora": "Días mora actual",
    "mora": "Mora Actual",  # filtro
    "saldo_doc": "Saldo",
    "cuotas_vencidas": "Cuotas vencidas",
    "tipo_credito_legal": "Tipo Cartera",  # filtro
    "fecha_ult_pago": "Fecha último pago",
    "monto_ult_pago": "Monto último pago",
    "fecha_proximo_pago": "Próximo pago",
    "tipo_pago": "Tipo de pago",
    "pago_mes": "Pago en el mes",
    "pago_antes": "Pago antes",
    "centro_cendoc": "Centro de Riesgo Actual",
    "cuotas_pagas": "Cuotas pagadas",
    "valor_vencido": "Valor vencido",
    "rodamiento": "Rodamiento",  # filtro
    "intentos": "Intentos",
    "gestionada": "Gestionadas",
    "contacto": "Contactos",
    "rpc": "RPC",
    "promesa": "Promesas",
    "ult_fecha_gestion": "Última gestión",
    "gestor": "Gestor",
    "ult_accion": "Última acción",
    "ult_resultado": "Último resultado",
    "tipo_cartera": "Tipo cartera del cono",
    "status_promesa_pago": "Status promesa",  # filtro
    "fecha_promesa": "Fecha promesa",
    "monto_promesa": "Monto promesa",
    "estado_promesa": "Estado promesa",
    "monto_pagado": "Monto pagado",
    "antig_cliente": "Antigüedad cliente (meses)",
    "rango_antig_cliente": "Rango antigüedad cliente",  # filtro
    "antig_credito": "Antigüedad crédito (meses)",
    "rango_antig_credito": "Rango antigüedad crédito",  # filtro
    "clasificacion": "Clasificación",  # filtro
    "rango_antig_laboral": "Rango antigüedad laboral",  # filtro
    "rango_desembolso": "Rango desembolso",  # filtro
    "rango_edad": "Rango edad",  # filtro
    "rango_salario": "Rango salario",  # filtro
    "multiplicador": "Multiplicador",
    "rango_multiplicador": "Rango multiplicador",  # filtro
    "rango_ingreso": "Rango ingreso bruto",  # filtro
    "rango_capacidad": "Rango capacidad de pago",  # filtro
    "rango_estabilidad": "Rango estabilidad INSS",  # filtro
    "rango_edad_motor": "Rango edad motor",  # filtro
    "rango_score": "Rango score",  # filtro
    "primer_pago_mes": "Primera cuota este mes",
    "estado_primer_pago": "Estado primer pago",
}


def excel(b: pd.DataFrame) -> bytes:
    df = b[[c for c in COLUMNAS_EXCEL if c in b]].rename(columns=COLUMNAS_EXCEL)
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.tz_localize(None) if getattr(df[c].dt, "tz", None) else df[c]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Cosecha", index=False, freeze_panes=(1, 1))
    return buf.getvalue()


AUX_SEG = ("d_dpago", "c_dpago", "d_gpp", "c_gpp", "d_cpp", "c_cpp", "d_rpp", "c_rpp")


def seguimientos(seg: dict) -> dict[str, dict]:
    """Archivos de la herramienta de primeros pagos: pp_seg_<n> (nPD), pp_mc_<n> (mora por cuota) y pp_pds (PD's por cosecha)."""
    out = {}
    for (tipo, n), t in seg["tablas"].items():
        meta = {**seg["meta"], "tipo": tipo, "n": n}
        out[f"pp_{'seg' if tipo == 'pd' else 'mc'}_{n}"] = seguimiento({"tabla": t, "meta": meta})
    out["pp_pds"] = pds_por_cosecha(seg)
    return out


def pds_por_cosecha(seg: dict) -> dict:
    """Una fila por crédito con su marca 1PD a 6PD (al cierre y a la misma fecha): la tabla de PD's por cosecha con filtros."""
    from .pp_seguimiento import DIMS as DIMS_SEG
    tablas = {n: t for (tipo, n), t in seg["tablas"].items() if tipo == "pd"}
    dims = ["mes_desembolso"] + [c for c in DIMS_SEG if c in tablas[1] and c != "mes_desembolso"]
    base = pd.concat([t[["index", "credito", "w"] + dims] for t in tablas.values()]).drop_duplicates("index").set_index("index")
    for n, t in tablas.items():
        x = t.set_index("index")
        for k in ("c", "d"):
            base[f"{k}{n}_i"] = x[f"{k}_incl"].reindex(base.index)
            base[f"{k}{n}_p"] = x[f"{k}_pd"].reindex(base.index)
            for ps in ("p", "v", "s", "gp", "gg"):   # términos Paga Solo
                base[f"{k}{n}_{ps}"] = x[f"{k}_ps_{ps}"].reindex(base.index)
        base[f"m{n}"] = x["mes_cobro"].reindex(base.index)
    base = base.reset_index()
    for c in dims:
        base[c] = base[c].astype("object").where(base[c].notna(), "SIN DATO")
    if "dia_pago" in base:
        base["dia_pago"] = base["dia_pago"].map(lambda v: v if v == "SIN DATO" else str(int(float(v))))
    meds = ["w"] + [c for c in base.columns if c[:1] in ("c", "d") and c[1:2].isdigit()]
    return _columnar(base, dims + [f"m{n}" for n in tablas], meds,
                     {"fila": [int(i) for i in base["index"]], "meta": seg["meta"]})


def seguimiento(seg: dict) -> dict:
    """Una fila por cuota con sus indicadores a la misma fecha (d_) y al cierre (c_)."""
    from .pp_seguimiento import DIMS as DIMS_SEG
    t = seg["tabla"].drop(columns=[c for c in seg["tabla"].columns if c.startswith("i_") or c in AUX_SEG])
    if seg["meta"].get("n", 1) > 1 or seg["meta"].get("tipo") == "mc":   # las reglas FPD son solo de la primera cuota
        t = t.drop(columns=[c for c in t.columns if c[2:4] == "r_"])
    dims = ["mes_cobro", "dia_vence", "credito"] + [c for c in DIMS_SEG if c in t] + ["d_rod", "c_rod"]
    for c in dims:
        if c not in ("d_rod", "c_rod"):
            t[c] = t[c].astype("object").where(t[c].notna(), "SIN DATO")
    t["dia_pago"] = t["dia_pago"].map(lambda v: v if v == "SIN DATO" else str(int(float(v)))) if "dia_pago" in t else None
    medidas = ["w"] + [c for c in t.columns if c[:2] in ("d_", "c_") and c not in ("d_rod", "c_rod")]
    return _columnar(t, dims, medidas, {"fila": [int(i) for i in t["index"]], "meta": seg["meta"]})


def base_json(b: pd.DataFrame) -> dict:
    """Base completa (columnas del Excel) en formato columnar para que la app descargue solo las filas filtradas.
    Textos con diccionario (se repiten mucho), fechas como texto ISO, números tal cual. Mismo orden de filas que la base."""
    df = b[[c for c in COLUMNAS_EXCEL if c in b]]
    cols, datos = [], []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s):
            cols.append({"n": COLUMNAS_EXCEL[c], "t": "b"}); datos.append([None if pd.isna(v) else bool(v) for v in s])
        elif pd.api.types.is_datetime64_any_dtype(s):
            t = s.dt.tz_localize(None) if getattr(s.dt, "tz", None) else s
            con_hora = bool((t.dropna().dt.normalize() != t.dropna()).any())
            fmt = "%Y-%m-%dT%H:%M:%S" if con_hora else "%Y-%m-%d"
            cols.append({"n": COLUMNAS_EXCEL[c], "t": "d"}); datos.append([None if pd.isna(v) else v.strftime(fmt) for v in t])
        elif pd.api.types.is_numeric_dtype(s):
            cols.append({"n": COLUMNAS_EXCEL[c], "t": "n"})
            datos.append([None if pd.isna(v) else (int(v) if float(v).is_integer() else round(float(v), 6)) for v in s])
        else:
            v = s.astype("object").where(s.notna(), None)
            cat = pd.Categorical(v.map(lambda x: None if x is None else str(x)))
            cols.append({"n": COLUMNAS_EXCEL[c], "t": "s", "dic": [str(x) for x in cat.categories]})
            datos.append([None if k < 0 else int(k) for k in cat.codes])
    return {"n": len(df), "cols": cols, "datos": datos}


def a_json(obj) -> bytes:
    def conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (pd.Timestamp, datetime, date)):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=conv).encode("utf-8")


def comprimir(datos: bytes) -> bytes:
    return gzip.compress(datos, compresslevel=9, mtime=0)
