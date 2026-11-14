---Empleados - Cosecha de empleados (último corte disponible)
-- Estándar: llave "cedula" sin guiones, sin espacios y en mayúscula (ej. '0010101900001A'),
-- igual que en Loan Tape y Genesis, para que crucen aunque una fuente traiga guiones y otra no.
SET NOCOUNT ON;

DECLARE @FReporte DATE = (
    SELECT MAX(F_REPORTE)
    FROM [DATA_TEMPLEA_REGIONAL].[dbo].[th_templea_ni]
);

SELECT
    UPPER(REPLACE(REPLACE(RTRIM(LTRIM([iem_cnumcedula])), '-', ''), ' ', '')) AS cedula,
    [iem_cnombrefun],
    [iem_cnomempres],
    [iem_dsalariofun],
    [iem_codempleador]
FROM [DATA_TEMPLEA_REGIONAL].[dbo].[th_templea_ni]
WHERE F_REPORTE = @FReporte;
