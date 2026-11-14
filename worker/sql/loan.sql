---Loan Tape - Cosecha de cuentas origen y primer reporte
-- Estándar: llave "credito" = comprobante + espacio + número, sin espacios al final (ej. 'JAR 50131').
-- Cédula sin guiones, sin espacios y en mayúscula, igual que Genesis y Empleados.
SET NOCOUNT ON;

DECLARE @FechaInicio DATE =
    DATEADD(MONTH, -24, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1));

DECLARE @FechaFin DATE =
    DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1);

WITH CuentasOrigen AS (
    SELECT
        credito,
        MIN(fecha_renov) AS fecha_origen
    FROM [LOAN_TAPE].[dbo].[loantape_his_ni]
    WHERE fecha_renov >= @FechaInicio
      AND fecha_renov < @FechaFin
      AND credito IS NOT NULL
    GROUP BY credito
),
PrimerReporte AS (
    SELECT
        C.credito,
        C.fecha_origen,
        MIN(L.f_reporte) AS primer_f_reporte
    FROM CuentasOrigen C
    INNER JOIN [LOAN_TAPE].[dbo].[loantape_his_ni] L
        ON L.credito = C.credito
       AND L.f_reporte >= C.fecha_origen
    GROUP BY
        C.credito,
        C.fecha_origen
),
Cosecha AS (
    SELECT
        L.*,
        ROW_NUMBER() OVER (
            PARTITION BY L.credito
            ORDER BY L.f_reporte ASC
        ) AS RN
    FROM PrimerReporte P
    INNER JOIN [LOAN_TAPE].[dbo].[loantape_his_ni] L
        ON L.credito = P.credito
       AND L.f_reporte = P.primer_f_reporte
)
SELECT
    RTRIM(credito) AS credito,
    comprobante,
    numero,
    ciudad,
    valor_cuota,
    numero_cuotas,
    fecha_vence,
    tasainteres,
    monto_des,
    nombre_mod,
    nombre_centro,
    fecha_renov,
    ncredxcliente,
    saldopagare,
    dlo,
    nit,
    dias_pago,
    primera_cuota,
    producto,
    nombre_deudor,
    edad,
    genero,
    salario,
    ubicacion,
    profesion,
    tiempo_trabajo,
    est_civil,
    sucursal,
    UPPER(REPLACE(REPLACE(RTRIM(LTRIM(cedula)), '-', ''), ' ', '')) AS cedula
FROM Cosecha
WHERE RN = 1
  AND monto_des > 2;