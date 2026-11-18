"""Arma la base del módulo: una fila por crédito de la cosecha (Loan Tape, últimos 24 meses) con los cruces y
rangos de la hoja "Cosecha" del Excel de referencia (Seguimiento Cobro.xlsx).

Diferencias con el Excel (a propósito):
- Gestiones: el catálogo de códigos repite cada gestión como Admin y Legal; se deja una sola por gestión,
  la del tipo de cartera del crédito (Legal si en Cartera tiene tipo legal distinto de 0).
- La gestión y la promesa de cada crédito son las MÁS RECIENTES del mes (el BUSCARV tomaba la primera fila).
- "Pago antes": compara el día del último pago del mes con el día de pago del crédito (en el Excel siempre daba 1).
- SALARIO_NET de MOTO/PREN: el tramo 12,000 - 14,999.99 termina en 15,000 (el Excel decía 150,000).
"""
from datetime import date

import numpy as np
import pandas as pd

from . import reglas_fpd

NULOS = {"NULL", "", "nan", "None", "#N/A"}


# ---------- utilidades ----------
def txt(s: pd.Series) -> pd.Series:
    """Texto sin espacios a los lados; vacío o NULL → None."""
    s = s.astype("object").where(s.notna(), None)
    s = s.map(lambda v: None if v is None else str(v).strip())
    return s.where(~s.isin(NULOS), None)


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.map(lambda v: None if v is None or str(v).strip() in NULOS else v), errors="coerce").astype(float)


def fecha(s: pd.Series) -> pd.Series:
    f = pd.to_datetime(s, errors="coerce")
    return f.where(f.dt.year > 1900)  # 1900-01-01 = sin dato


def solo_digitos(s: pd.Series) -> pd.Series:
    """Cédula/NIT para cruzar fuentes que la escriben distinto: solo dígitos, sin ceros a la izquierda."""
    d = txt(s).str.replace(r"\D", "", regex=True).str.lstrip("0")
    return d.where(d.str.len() > 0, None)


def cedula(s: pd.Series) -> pd.Series:
    c = txt(s).str.upper().str.replace(r"[\s-]", "", regex=True)
    return c.where(c.str.len() > 0, None)


def meses_entre(desde: pd.Series, hasta) -> pd.Series:
    """Meses completos entre dos fechas (como DATEDIF(...,"M")); negativo → NaN."""
    hasta = pd.Series(pd.Timestamp(hasta), index=desde.index) if not isinstance(hasta, pd.Series) else hasta
    m = (hasta.dt.year - desde.dt.year) * 12 + (hasta.dt.month - desde.dt.month) - (hasta.dt.day < desde.dt.day)
    return m.where(m >= 0)


def tramos(x: pd.Series, cortes: list[float], etiquetas: list[str], nulo: str | None = None) -> pd.Series:
    """Asigna etiquetas por tramos [c_i, c_{i+1}); x < primer corte → None."""
    r = pd.cut(x, bins=cortes + [np.inf], labels=etiquetas, right=False).astype("object")
    r = r.where(r.notna(), None)
    if nulo is not None:
        r = r.where(x.notna(), nulo)
    return r


def elegir(condiciones: list, valores: list, defecto=None) -> pd.Series:
    return pd.Series(np.select([c.fillna(False).to_numpy(bool) for c in condiciones], valores, default=None),
                     index=condiciones[0].index).where(lambda s: s.notna(), defecto)


# ---------- rangos (hoja Cosecha) ----------
R_MESES = (["1. 0 Meses", "2. 1-3 Meses", "3. 4-6 Meses", "4. 7-12 Meses", "5. 1-2 Años", "6. 2-3 Años",
            "7. 3-5 Años", "8. 5 Años a más"], [0, 1, 4, 7, 13, 25, 37, 61])
EDADES = ["18 - 21 AÑOS", "22 - 25 AÑOS", "26 - 29 AÑOS", "30 - 33 AÑOS", "34 - 37 AÑOS", "38 - 41 AÑOS", "42 - 45 AÑOS",
          "46 - 49 AÑOS", "50 - 53 AÑOS", "54 - 57 AÑOS", "58 - 61 AÑOS", "62 - 65 AÑOS", "66 AÑOS A MAS"]
C_EDADES = [18, 22, 26, 30, 34, 38, 42, 46, 50, 54, 58, 62, 66]


def rango_meses(x):
    return tramos(x, R_MESES[1], R_MESES[0])


def rango_mora(dias: pd.Series, en_cartera: pd.Series) -> pd.Series:
    r = elegir([dias <= 0, dias <= 30, dias <= 60, dias <= 90, dias <= 120, dias <= 150, dias <= 180, dias > 180],
               ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7"])
    return r.where(en_cartera, "CANCELADO")


def rango_desembolso(m: pd.Series, prod: pd.Series) -> pd.Series:
    cortes = [0] + list(range(20000, 340001, 20000))
    etiquetas = ["01. Menor a 19,999.99"] + [f"{i + 2:02d}. {c:,} - {c + 19999.99:,.2f}" for i, c in enumerate(cortes[1:-1])] \
        + ["18. Mayor a 340,000"]
    general = tramos(m, [-np.inf] + cortes[1:], etiquetas)
    pyme = elegir([m < 20000, m < 40000, m <= 66600, m < 100000, m < 150000, m <= 220000, m <= 250000, m <= 300000, m > 300000],
                  ["01. Menor a 20,000", "02. 20,000 - 39,999.99", "03. 40,000 - 66,600", "04. 66,600.01 - 99,999.99",
                   "05. 100,000 - 149,999.99", "06. 150,000 - 220,000", "07. 220,000.01 - 249,999.99",
                   "08. 250,000 - 299,999.99", "09. Mayor a 300,000"])
    return pyme.where(prod == "PYME", general)


def rango_salario(v: pd.Series, prod: pd.Series) -> pd.Series:
    moto = tramos(v, [-np.inf, 5000, 7000, 10000, 12000, 15000, 17000, 20000, 35000, 50000, 100000, 150000, 200000, 250000, 300000],
                  ["01. Menor a 4,999.99", "02. 5,000 - 6,999.99", "03. 7,000 - 9,999.99", "04. 10,000 - 11,999.99",
                   "05. 12,000 - 14,999.99", "06. 15,000 - 16,999.99", "07. 17,000 - 19,999.99", "08. 20,000 - 34,999.99",
                   "09. 35,000 - 49,999.99", "10. 50,000 - 99,999.99", "11. 100,000 - 149,999.99", "12. 150,000 - 199,999.99",
                   "13. 200,000 - 249,999.99", "14. 250,000 - 299,999.99", "15. Mayor a 300,000"])
    pers = tramos(v, [-np.inf, 5000, 7000, 10000, 12000, 15000, 20000, 35000, 50000, 100000, 150000, 200000, 250000, 300000],
                  ["01. Menor a 4,999.99", "02. 5,000 - 6,999.99", "03. 7,000 - 9,999.99", "04. 10,000 - 11,999.99",
                   "05. 12,000 - 14,999.99", "06. 15,000 - 19,999.99", "07. 20,000 - 34,999.99", "08. 35,000 - 49,999.99",
                   "09. 50,000 - 99,999.99", "10. 100,000 - 149,999.99", "11. 150,000 - 199,999.99",
                   "12. 200,000 - 249,999.99", "13. 250,000 - 299,999.99", "14. Mayor a 300,000"])
    return moto.where(prod.isin(["MOTO", "PREN"]), pers.where(prod.isin(["PERS", "PYME"]), "SIN RANGO"))


def producto_comercial(mod: pd.Series, prod: pd.Series, salario: pd.Series, saldo: pd.Series) -> pd.Series:
    m = mod.fillna("").str.upper()
    v, s = salario.fillna(0), saldo.fillna(0)
    moto = prod.isin(["MOTO", "PREN"])
    return elegir(
        [m.str.contains("MOTO 4", regex=False), m.str.contains("REMESA", regex=False), m.str.contains("CONV", regex=False),
         m.str.contains("PENSIONADO", regex=False),
         (prod == "PERS") & (v < 20000), (prod == "PERS") & (v < 50000), prod == "PERS",
         (prod == "PYME") & (s < 66600), (prod == "PYME") & (s < 220000), prod == "PYME",
         moto & (v < 12000), moto & (v < 17000), moto],
        ["PRENDARIO MOTO 4", "REMESANTE", "CONVENIO", "PENSIONADO",
         "ASAL FULL", "ASAL FULL PLUS", "ASAL ESPECIAL",
         "PYME MATRIZ", "PYME NUEVO", "PYME PREMIUM",
         "PRENDARIO MOTO 1 Y 2", "PRENDARIO MOTO 3", "PRENDARIO MOTO ESPECIAL"], "OTRO")


# ---------- gestiones ----------
CLAVE_GESTION = ["credito", "fecha_actividad", "codigo_accion", "codigo_resultado", "usuario"]


def depurar_gestiones(g: pd.DataFrame, tipo_cartera_credito: pd.Series) -> pd.DataFrame:
    """Una fila por gestión: el catálogo de códigos la repite como Admin y Legal; queda la del tipo del crédito."""
    g = g.copy()
    for c in ["credito", "codigo_accion", "codigo_resultado", "usuario", "status_promesa_pago", "estado_promesa",
              "descripcion_accion", "descripcion_resultado", "tipo_cartera"]:
        if c in g:
            g[c] = txt(g[c])
    for c in ["gestionada", "contacto", "rpc", "promesa", "monto_promesa", "monto_pagado"]:
        g[c] = num(g[c]).fillna(0)
    g["fecha_actividad"] = pd.to_datetime(g["fecha_actividad"], errors="coerce")
    g["fecha_promesa"] = fecha(g["fecha_promesa"])
    g["_tipo_credito"] = g["credito"].map(tipo_cartera_credito).fillna("Admin")
    g["_pref"] = (g["tipo_cartera"] == g["_tipo_credito"]).astype(int)
    g = g.sort_values(CLAVE_GESTION + ["_pref"], ascending=[True] * len(CLAVE_GESTION) + [False])
    return g.drop_duplicates(CLAVE_GESTION, keep="first").drop(columns=["_pref", "_tipo_credito"])


def resumen_gestiones(g: pd.DataFrame) -> pd.DataFrame:
    """Por crédito: cono (intentos, gestionadas, contactos, RPC, promesas), última gestión y última promesa del mes."""
    cono = g.groupby("credito").agg(intentos=("credito", "size"), gestionada=("gestionada", "sum"),
                                    contacto=("contacto", "sum"), rpc=("rpc", "sum"), promesa=("promesa", "sum"))
    ult = g.sort_values("fecha_actividad").groupby("credito").last()[
        ["codigo_accion", "codigo_resultado", "fecha_actividad", "usuario", "descripcion_accion",
         "descripcion_resultado", "tipo_cartera"]]
    ult.columns = ["ult_codigo_accion", "ult_codigo_resultado", "ult_fecha_gestion", "gestor", "ult_accion",
                   "ult_resultado", "tipo_cartera"]
    p = g[g["promesa"] > 0].sort_values("fecha_actividad").groupby("credito").last()[
        ["status_promesa_pago", "fecha_promesa", "monto_promesa", "estado_promesa", "monto_pagado"]]
    return cono.join(ult, how="left").join(p, how="left")


# ---------- base ----------
def construir(d: dict[str, pd.DataFrame], hoy: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    hoy = pd.Timestamp(hoy or date.today())
    avisos = []

    # Loan Tape (cosecha): una fila por crédito
    b = d["loan"].copy()
    for c in ["credito", "comprobante", "ciudad", "nombre_mod", "nombre_centro", "dlo", "nit", "producto", "nombre_deudor",
              "genero", "ubicacion", "profesion", "est_civil", "sucursal"]:
        b[c] = txt(b[c])
    b["cedula"] = cedula(b["cedula"])
    for c in ["valor_cuota", "numero_cuotas", "tasainteres", "monto_des", "ncredxcliente", "saldopagare", "dias_pago",
              "edad", "salario", "tiempo_trabajo", "numero"]:
        b[c] = num(b[c])
    for c in ["fecha_vence", "fecha_renov", "primera_cuota"]:
        b[c] = fecha(b[c])
    n0 = len(b)
    b = b[b["credito"].notna()].drop_duplicates("credito")
    if len(b) < n0:
        avisos.append(f"Loan Tape: {n0 - len(b)} filas sin crédito o repetidas")

    # Cartera de cobro (MCCOLLECT)
    ca = d["cartera"].copy()
    ca["credito"] = txt(ca["credito"])
    ca = ca.drop_duplicates("credito").set_index("credito")
    cart = pd.DataFrame(index=ca.index)
    cart["dias_mora"] = num(ca["PR_CL_DIA_MORA_HOY"])
    cart["saldo_doc"] = num(ca["PR_CL_SALDO_DOC"])
    cart["tipo_credito_legal"] = txt(ca["PR_CL_TIPO_CREDITO_LEGAL"].astype("object").map(lambda v: None if v is None else str(v)))
    cart["cuotas_vencidas"] = num(ca["PR_CL_NRO_CUOTAS_VENCIDAS"])
    cart["fecha_ult_pago"] = fecha(ca["PR_CL_DATE_ULT_PAGO"])
    cart["monto_ult_pago"] = num(ca["PR_CL_MONTO_ULT_PAGO"])
    cart["due_diario"] = num(ca["PR_CL_DUE_DIARIO"])
    cart["fecha_proximo_pago"] = fecha(ca["DTE_PROXIMO_PAGO"])
    # Cartera Legal = tipo de crédito legal JUR o NIIF; el resto (vacío, CJT, CON, TEN) es Admin
    legal = cart["tipo_credito_legal"].fillna("").str.strip().str.upper().isin(["JUR", "NIIF"])
    tipo_cartera_credito = pd.Series(np.where(legal, "Legal", "Admin"), index=cart.index)

    # Gestiones del mes (depuradas) y su resumen por crédito
    g = depurar_gestiones(d["gestiones"], tipo_cartera_credito)
    avisos.append(f"Gestiones: {len(d['gestiones']):,} filas del query → {len(g):,} gestiones únicas")
    ges = resumen_gestiones(g)

    # Cendoc
    cd = d["cendoc"].copy()
    cd["credito"] = txt(cd["credito"])
    cd = cd.drop_duplicates("credito").set_index("credito")
    cend = pd.DataFrame(index=cd.index)
    cend["empresa_cendoc"] = txt(cd["dco_empresa"].astype("object").map(lambda v: None if v is None else str(v)))
    cend["dealer"] = txt(cd["dco_dealer"])
    cend["centro_cendoc"] = txt(cd["dco_nom_centro"])
    cend["cuotas_pagas"] = num(cd["dco_cuotas_pagas"])
    cend["valor_vencido"] = num(cd["dco_valor_vencido"])
    cend["rodamiento"] = txt(cd["dco_rodamiento"])
    cend["cargo"] = txt(cd["dco_cargo"].astype("object").map(lambda v: None if v is None else str(v)))
    cend["recaudo_total"] = num(cd["dco_recaudo_total"]) if "dco_recaudo_total" in cd else np.nan

    # Genesis: una fila por crédito (la aprobación más reciente)
    ge = d["genesis"].copy()
    ge["credito"] = txt(ge["credito"])
    if "Fecha_Aprobado" in ge:
        ge = ge.sort_values("Fecha_Aprobado", ascending=False, na_position="last")
    ge = ge.drop_duplicates("credito").set_index("credito")
    gen = pd.DataFrame(index=ge.index)
    gen["num_solicitud"] = num(ge["Num_Solicitud"])
    gen["cedula_genesis"] = cedula(ge["cedula"])
    gen["fecha_nacimiento"] = fecha(ge["Fecha_Nacimiento"])
    for dst, src in [("tipo_credito", "Tipo_Credito"), ("analista", "Analista"), ("promotor", "Promotor"),
                     ("tipo_promotor", "Tipo_Promotor"), ("suc_origen", "Suc_Origen"), ("categorizacion", "Categorizacion"),
                     ("medio_captacion", "Medio_Captacion"), ("telefono", "Telefono_Cliente"), ("correo", "Correo_Cliente")]:
        gen[dst] = txt(ge[src].astype("object").map(lambda v: None if v is None else str(v)))
    gen["cedula_promotor"] = cedula(ge["cedula_promotor"])
    gen["fecha_creacion"] = fecha(ge["Fecha_creacion"])
    gen["fecha_aprobado"] = pd.to_datetime(ge.get("Fecha_Aprobado"), errors="coerce")
    gen["score"] = num(ge["Score"])

    b = b.join(ges, on="credito").join(cart, on="credito").join(cend, on="credito").join(gen, on="credito")
    b["en_cartera"] = b["credito"].isin(cart.index)
    b["en_genesis"] = b["credito"].isin(gen.index)

    # Bitácora de Atención (Excel de Genesis): solo los campos que no traen Genesis ni Loan Tape.
    # Lo que ya viene de esas fuentes (solicitud, cédula, fechas de creación y aprobación, tipo de crédito, promotor,
    # sucursal origen, categorización, medio de captación, montos, tasa, modalidad, cliente) no se repite.
    if d.get("bitacora") is not None:
        bt = d["bitacora"].drop_duplicates().copy()
        bt = bt[num(bt["Consecutivo"]) > 0]
        bt["credito"] = txt(bt["Comprobante"]) + " " + num(bt["Consecutivo"]).astype("Int64").astype(str)
        bt = bt.sort_values("Fecha Aprobado", ascending=False).drop_duplicates("credito").set_index("credito")
        bit = pd.DataFrame(index=bt.index)
        bit["fecha_formalizado"] = fecha(bt["Fecha Formalizado"])
        bit["fecha_auditado"] = fecha(bt["Fecha Auditado"])
        # con las dos fechas de la bitácora, en días calendario: la bitácora trae la hora en formato de 12 h sin AM/PM
        bit["dias_aprobado_formalizado"] = (bit["fecha_formalizado"].dt.normalize() - fecha(bt["Fecha Aprobado"]).dt.normalize()).dt.days
        for dst, src in [("estado_expediente", "Estado"), ("nacionalidad", "Nacionalidad"), ("lugar_trabajo", "Lugar de Trabajo"),
                         ("actividad_economica", "Profesion"), ("tipo_salario", "Tipo Salario"), ("area", "Area"),
                         ("suc_dealer", "Suc Dealer"), ("vendedor", "Vendedor"), ("promociones", "Promociones"),
                         ("excepcion", "Excepcion"), ("motivo_rechazo", "Motivo Rechazo"), ("tipo_desembolso", "Tipo Desembolso"),
                         ("usuario_crea", "Usuario Crea"), ("usuario_aprobado", "Usuario Aprobado Informa"),
                         ("usuario_formaliza", "Usuario Formaliza"), ("sucursal_formaliza", "Sucursal Formaliza"),
                         ("usuario_audita", "Usuario Audita")]:
            bit[dst] = txt(bt[src])
        for dst, src in [("monto_aprobado_motor", "Aprobado_Motor"), ("razon_cuota_ingreso", "Razon Cuota Ingreso"),
                         ("capacidad_pago_bitacora", "Capacidad Pago"), ("valor_garantia", "Valor de la Garantia"),
                         ("prima", "Prima"), ("monto_financiar", "Monto a Financiar"), ("porcentaje_financiar", "Porcentaje a Financiar")]:
            bit[dst] = num(bt[src])
        b = b.join(bit, on="credito")
        b["en_bitacora"] = b["credito"].isin(bit.index)
        # Huecos de Genesis / Cendoc que la bitácora sí trae (mismo dato, no columna nueva)
        k = b["credito"]
        b["telefono"] = b["telefono"].fillna(k.map(txt(bt["Tel. Contacto"])))
        b["analista"] = b["analista"].fillna(k.map(txt(bt["Analista"])))  # vacío en Genesis = "FLUJO RAPIDO" en la bitácora
        dealer_bt = txt(bt["Dealer"]).where(lambda s: s.str.upper() != "SIN DEALER")
        b["dealer"] = b["dealer"].fillna(k.map(dealer_bt))
        # Dealer según Genesis (columna "Dealer" de la bitácora por número de solicitud, como el BUSCARV del usuario)
        bs = d["bitacora"].assign(_sol=num(d["bitacora"]["Num Solicitud"])).sort_values("Fecha Aprobado", ascending=False)
        bs = bs[bs["_sol"].notna()].drop_duplicates("_sol").set_index("_sol")
        b["dealer_genesis"] = b["num_solicitud"].map(txt(bs["Dealer"]))
    else:
        b["en_bitacora"] = False
        b["dealer_genesis"] = None

    # Empleados (base INSS) por cédula del cliente; si el Loan no la trae, la de Genesis
    em = d["empleados"].copy()
    em["cedula"] = cedula(em["cedula"])
    em = em.drop_duplicates("cedula").set_index("cedula")
    b["cedula_cliente"] = b["cedula"].fillna(b["cedula_genesis"])
    b["empresa_inss"] = b["cedula_cliente"].map(txt(em["iem_cnomempres"]))
    b["salario_inss"] = b["cedula_cliente"].map(num(em["iem_dsalariofun"]))
    b["empleador_inss"] = b["cedula_cliente"].map(em["iem_codempleador"].astype("object").map(lambda v: None if v is None else str(v).strip()))
    b["empleo_inss"] = np.where(b["cedula_cliente"].isin(em.index), "Sí", "No")

    # Primera renovación (antigüedad del cliente) por NIT
    pr = d["primera_renov"].copy()
    pr["nit"] = txt(pr["nit"].astype("object").map(lambda v: None if v is None else str(v)))
    pr = pr.drop_duplicates("nit").set_index("nit")
    b["primer_credito"] = b["nit"].map(fecha(pr["primer_credito"]))

    # Reglas del motor por solicitud (el resultado más reciente)
    rm = d["reglas_motor"].copy()
    rm["Solicitud"] = num(rm["Solicitud"])
    rm = rm.sort_values("Fecha_Resultado", ascending=False).drop_duplicates("Solicitud").set_index("Solicitud")
    for dst, src in [("resultado_motor", "Resultado_Final"), ("perfil_motor", "Nombre_ID_Perfil"),
                     ("politica_hit", "Valor_POLITICA_HIT_O_NO_HIT")]:
        b[dst] = b["num_solicitud"].map(txt(rm[src]))
    for dst, src in [("ingreso_bruto", "Valor_INGRESO_BRUTO"), ("capacidad_pago", "Valor_CAPACIDAD_DE_PAGO"),
                     ("score_tun", "Valor_SCORE_TUN"), ("estabilidad_inss", "Valor_ESTABILIDAD_LABORAL_INSS"),
                     ("edad_motor", "Valor_EDAD_CALCULADA")]:
        b[dst] = b["num_solicitud"].map(num(rm[src]))
    b["en_motor"] = b["num_solicitud"].isin(rm.index)

    # Promotores (CIT): canal y sucursal del promotor
    pm = d["promotores"].copy()
    pm["_k"] = solo_digitos(pm["nit_promotor"])
    pm = pm[pm["_k"].notna()].drop_duplicates("_k").set_index("_k")
    kp = solo_digitos(b["cedula_promotor"])
    b["canal"] = kp.map(txt(pm["nombre_canal"]))
    b["sucursal_promotor"] = kp.map(txt(pm["centro"]))

    # ---------- campos calculados ----------
    b["mes_desembolso"] = b["fecha_renov"].dt.strftime("%Y-%m")
    b["antig_cliente"] = meses_entre(b["primer_credito"], b["fecha_renov"])
    b["rango_antig_cliente"] = rango_meses(b["antig_cliente"])
    b["antig_credito"] = meses_entre(b["fecha_renov"], hoy)
    b["rango_antig_credito"] = rango_meses(b["antig_credito"])
    b["clasificacion"] = np.where((b["ncredxcliente"] > 1) & (b["antig_cliente"] > 1), "RENOVACION", "NUEVO")
    b["rango_antig_laboral"] = rango_meses(b["tiempo_trabajo"])
    b["mora"] = rango_mora(b["dias_mora"], b["en_cartera"])
    b["rango_desembolso"] = rango_desembolso(b["saldopagare"], b["producto"])
    b["rango_edad"] = tramos(b["edad"], C_EDADES, EDADES)
    b["rango_salario"] = rango_salario(b["salario"], b["producto"])
    b["producto_comercial"] = producto_comercial(b["nombre_mod"], b["producto"], b["salario"], b["saldopagare"])
    # Producto Madre: MOTO y PREN = MOTO; PERS se abre en CONV y PENS según el producto comercial
    pc = b["producto_comercial"]
    b["producto_madre"] = elegir(
        [b["producto"].isin(["MOTO", "PREN"]), b["producto"] == "PYME", (b["producto"] == "PERS") & (pc == "CONVENIO"),
         (b["producto"] == "PERS") & (pc == "PENSIONADO"), b["producto"] == "PERS"],
        ["MOTO", "PYME", "CONV", "PENS", "PERS"], "SIN DATO")
    b["con_excepcion"] = np.where(b["excepcion"].notna(), "SI", "NO") if "excepcion" in b else "NO"
    # Con Prima (solo MOTO): según el % financiado de la garantía (vacío cuenta como 0, igual que en Excel)
    pf = b["porcentaje_financiar"].fillna(0) if "porcentaje_financiar" in b else pd.Series(0.0, index=b.index)
    b["con_prima"] = elegir([pf == 100, pf >= 90, pf >= 80, pf < 80],
                            ["NO", "10% o Menos", "Entre 20% y 10%", "SI"]).where(b["producto_madre"] == "MOTO", "NO APLICA")
    b["multiplicador"] = (b["saldopagare"] / b["salario"]).where(b["salario"] > 0)
    b["rango_multiplicador"] = tramos(b["multiplicador"], [-np.inf, 1, 2, 3, 4, 5, 6, 7],
                                      ["01. Menor a 1", "02. 1 - 1.99", "03. 2 - 2.99", "04. 3 - 3.99", "05. 4 - 4.99",
                                       "06. 5 - 5.99", "07. 6 - 6.99", "08. Mayor a 7"], "SIN SALARIO")
    nohit = (b["politica_hit"].fillna("").str.upper() == "NOHIT") & (b["producto"] == "PERS")
    b["producto_motor"] = b["producto_comercial"].where(~nohit, b["producto_comercial"] + " NOHIT")
    sin_motor = lambda s, txt_nulo: s.where(b["en_motor"], "SIN DATO MOTOR").where(lambda x: x.notna(), txt_nulo)
    b["rango_ingreso"] = sin_motor(tramos(b["ingreso_bruto"], [-np.inf, 10000, 12000, 20000, 35000, 50000],
                                          ["01. Menor a 9,999.99", "02. 10,000 - 11,999.99", "03. 12,000 - 19,999.99",
                                           "04. 20,000 - 34,999.99", "05. 35,000 - 49,999.99", "06. 50,000 a más"]),
                                   "SALARIO NO ENCONTRADO")
    b["rango_capacidad"] = sin_motor(tramos(b["capacidad_pago"], [-np.inf, 21, 40, 50, 60, 70],
                                            ["0-20", "21-39", "40-49", "50-59", "60-69", "70 A MAS"]), "SIN RANGO")
    b["rango_estabilidad"] = sin_motor(tramos(b["estabilidad_inss"], [-np.inf, 3.5, 7, 13, 18, 25, 37, 49],
                                              ["0 - 3.5 meses", "3.5 - 7 meses", "7 - 12 meses", "12 - 17 meses",
                                               "18 - 24 meses", "25 - 36 meses", "37 - 48 meses", "49 meses a más"]),
                                       "ESTABILIDAD NO ENCONTRADA")
    b["rango_edad_motor"] = sin_motor(tramos(b["edad_motor"], C_EDADES, EDADES), "SIN RANGO")
    b["rango_score"] = tramos(b["score"], [-np.inf, 550, 651, 686, 763],
                              ["1. MENOR A 550", "2. 550 - 650", "3. 651-685", "4. 686-762", "5. 763 +"], "SIN SCORE")
    pago, cuota = b["monto_ult_pago"], b["valor_cuota"]
    b["tipo_pago"] = elegir([(pago > 0) & (pago < cuota), pago > cuota, pago == cuota], ["PARCIAL", "EXTRA", "COMPLETO"],
                            "NO PAGO").where(b["en_cartera"])
    # Pago antes: día del último pago (si fue este mes) contra el día de pago del crédito
    este_mes = b["fecha_ult_pago"].dt.to_period("M") == hoy.to_period("M")
    b["pago_mes"] = np.where(~este_mes, "Sin pago este mes",
                             np.where(b["fecha_ult_pago"].dt.day <= b["dias_pago"], "Antes o en su día", "Después de su día"))
    b["pago_antes"] = np.where(este_mes, (b["fecha_ult_pago"].dt.day <= b["dias_pago"]).astype(int), np.nan)
    b.loc[~b["en_cartera"], ["pago_mes"]] = None

    # Primeros pagos: créditos cuya primera cuota vence este mes
    b["primer_pago_mes"] = b["primera_cuota"].dt.to_period("M") == hoy.to_period("M")
    pagado = (b["fecha_ult_pago"] >= b["fecha_renov"]) & (b["monto_ult_pago"] > 0)
    b["estado_primer_pago"] = elegir(
        [~b["en_cartera"], b["dias_mora"] > 0, pagado, b["primera_cuota"] > hoy],
        ["Cancelado", "En mora", "Pagó", "Por vencer"], "Vencida sin pago registrado")
    b["primera_cuota_vencida"] = b["primera_cuota"] <= hoy
    # Cumplimiento de las reglas de cobro FPD (solo créditos con primera cuota en el mes)
    b = reglas_fpd.evaluar(b, g, hoy)

    # Textos vacíos de dimensiones → etiqueta visible
    for c in ["sucursal", "canal", "sucursal_promotor", "promotor", "categorizacion", "tipo_credito", "medio_captacion",
              "perfil_motor", "politica_hit", "rodamiento", "tipo_cartera", "estado_promesa", "ult_resultado", "gestor",
              "genero", "producto", "tipo_credito_legal"]:
        b[c] = b[c].fillna("SIN DATO")

    for fuente, col in [("Cartera", "en_cartera"), ("Genesis", "en_genesis"), ("Bitácora", "en_bitacora"),
                        ("Reglas Motor", "en_motor")]:
        avisos.append(f"{fuente}: {int(b[col].sum()):,} de {len(b):,} créditos encontrados")
    avisos.append(f"Promotores: canal encontrado para {int(b['canal'].ne('SIN DATO').sum()):,} créditos")
    return b.reset_index(drop=True), g, avisos
