--- Cartera de Cobro - Cosecha de Cobro
-- Estándar: llave "credito" = comprobante + espacio + número, sin espacios al final (ej. 'LVT 5210').
SET NOCOUNT ON;

DECLARE @FReporte DATE = (
    SELECT MAX(F_REPORTE)
    FROM [MCCOLLECT].[dbo].[th_mccollect_cartera_diaria_regional]
    WHERE pais = 'Nicaragua'          -- último corte de Nicaragua (no de toda la tabla regional)
);

SELECT RTRIM([PR_MC_CREDITO]) AS credito
      ,[PR_CL_DIA_MORA_HOY]
      ,[PR_CL_SALDO_DOC]
      ,[PR_CL_TIPO_CREDITO_LEGAL]
      ,[PR_CL_NRO_CUOTAS_VENCIDAS]
      ,[PR_CL_DATE_ULT_PAGO]
      ,[PR_CL_MONTO_ULT_PAGO]
      ,[PR_CL_DUE_DIARIO]
      ,[DTE_PROXIMO_PAGO]
FROM [MCCOLLECT].[dbo].[th_mccollect_cartera_diaria_regional]
WHERE pais = 'Nicaragua'
  AND F_REPORTE = @FReporte;
