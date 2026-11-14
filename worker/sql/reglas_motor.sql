---Reglas detalladas del Motor (copia del worker; el original está en la carpeta del proyecto)
-- Perfil y valores de las reglas del motor por solicitud, últimos 24 meses (llave: Solicitud = Num_Solicitud de Genesis).
-- Si una solicitud tiene varios resultados, el proceso se queda con el más reciente.
SET NOCOUNT ON;

WITH ReglasDetalladas AS (
    SELECT
        b.id_m_solicitud AS Solicitud,
        b.resultado AS Resultado_Final,
        Perfil.descPerfil AS Nombre_ID_Perfil,
        Reglas.idRegla AS ID_Regla,
        Reglas.valorAnalizar AS Valor_Analizado,
        b.fechaCreacion AS Fecha_Resultado
    FROM [RESULTADO_MOTOR].[dbo].[th_resultado_motor_regional] b WITH (NOLOCK)
    CROSS APPLY OPENJSON(CAST(jsonresultadomotorko AS nvarchar(max)), '$.Detalle')
    WITH (
        idPerfil NVARCHAR(100) '$.idPerfil',
        descPerfil NVARCHAR(100) '$.descPerfil'
    ) AS Perfil
    CROSS APPLY OPENJSON(CAST(jsonresultadomotorko AS nvarchar(max)), '$.Detalle.reglas')
    WITH (
        idRegla NVARCHAR(100) '$.idRegla',
        valorAnalizar NVARCHAR(100) '$.valorAnalizar'
    ) AS Reglas
    WHERE b.PAIS = 'Nicaragua'
      AND LEN(TRIM(CAST(b.jsonresultadomotorko AS nvarchar(max)))) > 0
      AND ISJSON(CAST(b.jsonresultadomotorko AS nvarchar(max))) = 1
      AND TRY_CONVERT(date, b.fechaCreacion) BETWEEN DATEADD(MONTH, -25, CAST(GETDATE() AS date)) AND CAST(GETDATE() AS date)
)
SELECT
    Solicitud,
    Resultado_Final,
    Nombre_ID_Perfil,
    Fecha_Resultado,
    MAX(CASE WHEN ID_Regla = '429' THEN Valor_Analizado END) AS Valor_POLITICA_HIT_O_NO_HIT,
    MAX(CASE WHEN ID_Regla = '386' THEN Valor_Analizado END) AS Valor_INGRESO_BRUTO,
    MAX(CASE WHEN ID_Regla = '387' THEN Valor_Analizado END) AS Valor_CAPACIDAD_DE_PAGO,
    MAX(CASE WHEN ID_Regla = '388' THEN Valor_Analizado END) AS Valor_SCORE_TUN,
    MAX(CASE WHEN ID_Regla = '389' THEN Valor_Analizado END) AS Valor_ESTABILIDAD_LABORAL_INSS,
    MAX(CASE WHEN ID_Regla = '390' THEN Valor_Analizado END) AS Valor_EDAD_CALCULADA
FROM ReglasDetalladas
GROUP BY Solicitud, Resultado_Final, Nombre_ID_Perfil, Fecha_Resultado;
