---Promotor sucursal (copia del worker; el original está en la carpeta del proyecto)
-- Canal y centro de cada promotor. El cruce con Genesis (cedula_promotor) se hace en el proceso,
-- comparando solo los dígitos sin ceros a la izquierda (Genesis trae la letra final y el CIT no).
SET NOCOUNT ON;

SELECT DISTINCT
    RTRIM(p.centro)          AS centro,
    RTRIM(p.nit_promotor)    AS nit_promotor,
    RTRIM(p.nombre_promotor) AS nombre_promotor,
    RTRIM(m.nombre_canal)    AS nombre_canal
FROM [INSUMOS_OPERACIONES].[dbo].[v_promotores_cit_regional] p
INNER JOIN [INSUMOS_OPERACIONES].[dbo].[th_cit_metas_regional] m
    ON p.centro = m.nombre_campana
WHERE p.pais = 'Nicaragua'
  AND m.pais = 'Nicaragua';
