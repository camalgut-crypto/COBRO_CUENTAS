---Genesis Cosecha
-- Estándar: llave "credito" = comprobante + espacio + número (ej. 'HBS 38083'), una sola fila por crédito.
-- Cédulas sin guiones, sin espacios y en mayúscula, igual que Loan Tape y Empleados.
-- La vista puede repetir el mismo crédito: se deja la fila más reciente (rn = 1).
-- Consecutivo > 0: solo solicitudes con crédito formalizado (con 0 no hay crédito con qué cruzar).
-- Período: igual que Loan Tape, últimos 24 meses sin incluir el mes en curso.
SET NOCOUNT ON;

DECLARE @FechaInicio DATE = DATEADD(MONTH, -24, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1));
DECLARE @FechaFin    DATE = DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1);

WITH Colocacion AS (
    SELECT [Num_Solicitud]
          ,UPPER(REPLACE(REPLACE(RTRIM(LTRIM([Cedula])), '-', ''), ' ', '')) AS cedula
          ,[Fecha_Nacimiento]
          ,CONCAT(RTRIM([Comprobante]), ' ', [Consecutivo]) AS credito
          ,[Tipo_Credito]
          ,[Analista]
          ,[Promotor]
          ,UPPER(REPLACE(REPLACE(RTRIM(LTRIM([Cedula_Promotor])), '-', ''), ' ', '')) AS cedula_promotor
          ,[Tipo_Promotor]
          ,[Fecha_creacion]
          ,[Fecha_Aprobado]
          ,[Suc_Origen]
          ,[Categorizacion]
          ,[Score]
          ,[Medio_Captacion]
          ,[Telefono_Cliente]
          ,[Correo_Cliente]
          ,ROW_NUMBER() OVER (
               PARTITION BY RTRIM([Comprobante]), [Consecutivo]
               ORDER BY [Fecha_Aprobado] DESC, [Num_Solicitud] DESC
           ) AS rn
    FROM [SRV-TORTUGUERO\DATAWAREHOUSE].[GENESIS_REGIONAL].[dwh].[V_BIT_REGIONAL_COLOCACION_new]
    WHERE idpais = 2
      AND Consecutivo > 0
      AND Fecha_Aprobado >= @FechaInicio
      AND Fecha_Aprobado <  @FechaFin
)
SELECT [Num_Solicitud], cedula, [Fecha_Nacimiento], credito, [Tipo_Credito], [Analista], [Promotor],
       cedula_promotor, [Tipo_Promotor], [Fecha_creacion], [Fecha_Aprobado], [Suc_Origen], [Categorizacion],
       [Score], [Medio_Captacion], [Telefono_Cliente], [Correo_Cliente]
FROM Colocacion
WHERE rn = 1;
