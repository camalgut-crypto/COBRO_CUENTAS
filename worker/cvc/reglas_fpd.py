"""Cumplimiento de las reglas de cobro FPD (documento "REGLAS DE COBRO FPD.docx") contra las gestiones del cono.

Por cada crédito con primera cuota en el mes (FPD) se marca si cumplió cada regla medible con MCCollect:
- Predictivo Wolkvox: marcación predictiva del día del vencimiento al día 2 de mora.
- Fila MCC: llamada de un gestor al número del cliente en los días 1-2 de mora.
- Gestión de gestor: alguna llamada o WhatsApp de un gestor desde el día 1 de mora.
- Referencias: llamada a referencias desde el día 5 de mora (si llegó a 5 días).
- Visita: enviada a visita o visitada al llegar a los días de mora del producto, con saldo >= C$12,000
  (Personales 10 días si vence en la 1ª quincena y 5 en la 2ª; PYME 3 y 2; Prendarios/Motos 5).
Los SMS y el Blaster no se pueden medir: MCCollect no los registra día a día.

"Entró en mora" = no pagó hasta su fecha de pago (según la fecha del último pago de MCCollect). Si pagó después,
los días en mora se cuentan hasta ese pago.
"""
import numpy as np
import pandas as pd

CUMPLE, NO_CUMPLE = "Cumple", "No cumple"
REGLAS = {  # columna → nombre en la app
    "rg_predictivo": "Predictivo (día 0 a 2)",
    "rg_fila": "Llamada de gestor (día 1 a 2)",
    "rg_gestor": "Alguna gestión de gestor",
    "rg_referencias": "Referencias (desde día 5)",
    "rg_visita": "Visita de campo",
}
SALDO_VISITA = 12000


def _canal(g: pd.DataFrame) -> pd.Series:
    acc, res = g["codigo_accion"].fillna("").str.strip(), g["codigo_resultado"].fillna("").str.strip()
    return pd.Series(np.select(
        [(acc == "OTR") & (res == "SMS"), acc == "MPD", (acc == "OTR") & (res == "CEV"), acc == "VCD",
         acc.isin(["TMC", "TCC", "TTC", "LLC"]), acc.isin(["TRE", "TOT", "LLT"]), acc == "WAP"],
        ["SMS", "PREDICTIVO", "ENVIO_VISITA", "VISITA", "LLAMADA_CLIENTE", "LLAMADA_REFERENCIA", "WHATSAPP"], "OTRO"),
        index=g.index)


def evaluar(b: pd.DataFrame, g: pd.DataFrame, hoy: pd.Timestamp) -> pd.DataFrame:
    """Agrega a la base las columnas fpd_estado, dias_mora_fpd y rg_* (solo con valor en los créditos FPD)."""
    hoy = pd.Timestamp(hoy).normalize()
    b = b.copy()
    for c in ["fpd_estado", *REGLAS]:
        b[c] = None
    b["dias_mora_fpd"] = np.nan
    m = b["primer_pago_mes"].fillna(False).astype(bool)
    if not m.any():
        return b
    pp = b.loc[m, ["credito", "primera_cuota", "fecha_ult_pago", "monto_ult_pago", "fecha_renov", "estado_primer_pago",
                   "saldo_doc", "producto_madre"]].copy()
    D = pp["primera_cuota"].dt.normalize()
    fup = pp["fecha_ult_pago"].dt.normalize()
    pagado = (pp["fecha_ult_pago"] >= pp["fecha_renov"]) & (pp["monto_ult_pago"] > 0)
    a_tiempo = pagado & (fup <= D)
    vencida = D < hoy
    cancelado = pp["estado_primer_pago"] == "Cancelado"
    mora = ~a_tiempo & vencida & ~cancelado
    fin = pd.Series(np.where(pagado & (fup > D), fup, hoy), index=pp.index).astype("datetime64[ns]")
    dias = (fin - D).dt.days.where(mora, 0)
    pp["fpd_estado"] = np.select([cancelado, ~vencida & ~a_tiempo, a_tiempo, mora],
                                 ["Cancelado", "Por vencer", "Pagó a tiempo", "Entró en mora"], "Por vencer")
    pp["dias_mora_fpd"] = dias.where(mora)

    # Gestiones de los créditos FPD con el día relativo al vencimiento (0 = día de pago, 1 = 1 día de mora)
    gx = g[g["credito"].isin(set(pp["credito"]))][["credito", "codigo_accion", "codigo_resultado", "fecha_actividad"]].copy()
    gx["canal"] = _canal(gx)
    gx = gx.merge(pd.DataFrame({"credito": pp["credito"], "D": D}), on="credito")
    gx["rel"] = (gx["fecha_actividad"].dt.normalize() - gx["D"]).dt.days

    def hubo(canales, desde, hasta=None, desde_por_credito=None):
        x = gx[gx["canal"].isin(canales) & (gx["rel"] <= hasta if hasta is not None else True)]
        if desde_por_credito is not None:
            x = x[x["rel"] >= x["credito"].map(desde_por_credito)]
        else:
            x = x[x["rel"] >= desde]
        return pp["credito"].isin(set(x["credito"]))

    marca = lambda ok, aplica: pd.Series(np.where(ok, CUMPLE, NO_CUMPLE), index=pp.index).where(aplica, None)
    dia1 = mora & (D + pd.Timedelta(days=1) <= hoy)
    pp["rg_predictivo"] = marca(hubo(["PREDICTIVO"], 0, 2), dia1)
    pp["rg_fila"] = marca(hubo(["LLAMADA_CLIENTE"], 1, 2), dia1)
    pp["rg_gestor"] = marca(hubo(["LLAMADA_CLIENTE", "LLAMADA_REFERENCIA", "WHATSAPP"], 1), dia1)
    pp["rg_referencias"] = marca(hubo(["LLAMADA_REFERENCIA"], 5), mora & (dias >= 5))
    q1 = D.dt.day <= 15
    prod = pp["producto_madre"]
    umbral = pd.Series(np.select(
        [prod == "MOTO", (prod == "PYME") & q1, prod == "PYME", prod.isin(["PERS", "PENS"]) & q1, prod.isin(["PERS", "PENS"])],
        [5, 3, 2, 10, 5], default=np.nan), index=pp.index)
    aplica_vis = mora & (pp["saldo_doc"].fillna(0) >= SALDO_VISITA) & umbral.notna() & (dias >= umbral)
    pp["rg_visita"] = marca(hubo(["ENVIO_VISITA", "VISITA"], None, None, dict(zip(pp["credito"], umbral))), aplica_vis)

    for c in ["fpd_estado", "dias_mora_fpd", *REGLAS]:
        b.loc[m, c] = pp[c].values
    return b
