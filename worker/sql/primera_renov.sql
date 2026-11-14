---Primera renovación - Antigüedad del cliente (copia del worker; el original está en la carpeta del proyecto)
-- Primer desembolso de cada cliente (nit) en todo el histórico del Loan Tape.
-- Estándar: nit sin espacios al final.
SET NOCOUNT ON;

SELECT
    RTRIM(nit)        AS nit,
    MIN(fecha_renov)  AS primer_credito
FROM [LOAN_TAPE].[dbo].[loantape_his_ni]
WHERE fecha_renov IS NOT NULL
  AND nit IS NOT NULL
GROUP BY RTRIM(nit);
