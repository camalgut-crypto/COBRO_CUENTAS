---Gestiones - Cosecha de gestiones del mes en curso
-- Estándar: llave "credito" = comprobante + espacio + número (ej. 'HBS 33943').
-- En esta tabla viene con guion bajo ('HBS_33943'): se cambia a espacio.
SET NOCOUNT ON;

DECLARE @FechaInicio DATE = DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1);
DECLARE @FechaFin    DATE = DATEADD(MONTH, 1, @FechaInicio);

SELECT
    REPLACE(RTRIM(G.credito), '_', ' ') AS credito,
    G.codigo_accion,
    G.codigo_resultado,
    G.status_promesa_pago,
    G.fecha_actividad,
    G.pais,
    G.fecha_promesa,
    G.usuario,
    G.monto_promesa,
    G.estado_promesa,
    G.monto_pagado,

    C.descripcion_accion,
    C.descripcion_resultado,
    C.gestionada,
    C.contacto,
    C.rpc,
    C.promesa,
    C.tipo_cartera

FROM [MCCOLLECT].[dbo].[th_mccollect_gestiones_diarias_regional] G

LEFT JOIN [MCCOLLECT].[dbo].[t_mccollect_codigos_gestiones] C
    ON CONCAT(G.codigo_accion, G.codigo_resultado) = C.id_concatenado

WHERE
    G.pais = 'Nicaragua'
    AND G.fecha_actividad >= @FechaInicio
    AND G.fecha_actividad <  @FechaFin;
