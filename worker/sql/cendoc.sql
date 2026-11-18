---Cendoc - Cosecha Datos
-- Estándar: llave "credito" = comprobante + espacio + número, sin espacios al final (ej. 'LEO 16985').
-- dco_credito viene con muchos espacios al final ('LEO 16985           '): se limpia con RTRIM.
SET NOCOUNT ON;

DECLARE @FReporte DATE = (
    SELECT MAX(f_reporte)
    FROM [CENDOC].[dbo].[th_cendoc_diario_regional]
    WHERE pais = 'Nicaragua'          -- último corte de Nicaragua (no de toda la tabla regional)
);

SELECT RTRIM([dco_credito]) AS credito
      ,[dco_empresa]
      ,[dco_dealer]
      ,[dco_nom_centro]
      ,[dco_cuotas_pagas]
      ,[dco_valor_vencido]
      ,[dco_rodamiento]
      ,[dco_cargo]
      ,[dco_recaudo_total]
FROM [CENDOC].[dbo].[th_cendoc_diario_regional]
WHERE pais = 'Nicaragua'
  AND f_reporte = @FReporte;
