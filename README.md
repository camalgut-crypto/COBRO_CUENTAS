# Cosechas vs Cobro

Módulo web que cruza la **originación** (Loan Tape, Genesis, Reglas del Motor) con la **cobranza** (Cartera MCCOLLECT,
Cendoc, Gestiones) de Nicaragua. Solo muestra resúmenes y gráficos con filtros dinámicos; la base completa se baja con
el botón **Descargar data**. Tiene una herramienta para hacerle preguntas a los datos con IA.

- App: https://camalgut-crypto.github.io/COBRO_CUENTAS/
- Datos: Supabase de Tiempos DAC (`lzgteejsjxrbadsqlpnd`), prefijo `cvc_`, bucket privado `cvc`.
- Referencia funcional: `Seguimiento Cobro.xlsx` (hojas Cosecha, Cartera Activa, Primeros Pagos y Cono Cobranza).

## Pestañas y perfiles

| Pestaña | Qué muestra | Admin | Gerencia | Cobro | Comercial |
|---|---|---|---|---|---|
| Cosecha | Créditos desembolsados en 24 meses y su mora actual por mes de desembolso | ✔ | ✔ (solo gráficos) | | |
| Cartera Activa | Créditos en la cartera de cobro: saldo por tramo, rodamiento, pagos del mes | ✔ | ✔ (solo gráficos) | ✔ | |
| Primeros Pagos | Créditos cuya primera cuota vence este mes: pagaron, en mora, por vencer | ✔ | ✔ (solo gráficos) | ✔ | ✔ |
| Cono de cobranza | Embudo gestiones → contacto → RPC → promesa → cumplida, por gestor y día | ✔ | ✔ (solo gráficos) | | |

Descargar data: Admin y Gerencia. Administración de usuarios: Admin. Preguntas a la IA: todos, solo sobre sus pestañas.
Cada pestaña es un archivo aparte en el bucket y Supabase solo lo entrega a los perfiles que pueden verla.

## Reglas de cálculo

- **Base**: una fila por crédito del Loan Tape con primer desembolso en los últimos 24 meses (sin el mes en curso).
- **Llaves**: `credito` = `JAR 50131` (espacio, sin espacios al final) en todas las fuentes; `cedula` sin guiones y en
  mayúscula. Promotores (CIT) se cruza por los dígitos de la cédula del promotor.
- **Mora**: tramo por días de mora hoy (B0 al día … B7 más de 180); `CANCELADO` si el crédito ya no está en MCCOLLECT.
  Mora 30+ = B2 a B7; 90+ = B4 a B7, sobre el total de créditos del grupo.
- **Primeros Pagos**: primera cuota con vencimiento en el mes en curso. Pagó = último pago posterior al desembolso.
- **Pago antes**: el último pago del mes fue en o antes del día de pago del crédito.
- **Gestiones**: el catálogo de códigos repite cada gestión como Admin y Legal; se deja una por gestión, la del tipo de
  cartera del crédito (Legal si en MCCOLLECT tiene tipo de crédito legal distinto de 0). La última gestión y la última
  promesa de cada crédito son las más recientes del mes.
- Los rangos (score, desembolso, salario, edad, multiplicador, antigüedades, motor) son los del Excel, con dos
  correcciones: SALARIO_NET de MOTO/PREN (tramo 12,000-14,999.99) y "Pago antes" (en el Excel siempre daba 1).

## Actualización

El proceso corre en una PC de la red (los servidores SQL no se alcanzan desde internet):

| Consulta | Frecuencia | Archivo |
|---|---|---|
| Loan Tape, Genesis, Primera renovación, Reglas Motor, Promotores | día 01 de cada mes (primera carga del mes) | `worker/sql/*.sql` |
| Empleados (INSS) | días 1, 13 y 25 | `worker/sql/empleados.sql` |
| Cartera de Cobro, Cendoc, Gestiones | diaria (`hora_diaria`) y con el botón Actualizar | `worker/sql/*.sql` |

Las consultas mensuales y Empleados quedan guardadas en `worker/data/` y se reutilizan hasta que les toque de nuevo; si
una falla y hay copia, se usa la copia y queda el aviso en `worker/logs/actualizar.log`.

- `worker/actualizar.py --escuchar` — atiende el botón y la carga diaria (tarea programada).
- `worker/actualizar.py --una-vez [--forzar todo]` — una carga (con `--forzar` vuelve a consultar las mensuales).
- `worker/actualizar.py --local` — genera `public/local/` para revisar la app sin Supabase: abrir
  `public/index.html?local` con un servidor local (`?local&rol=gerencia|cobro|comercial` para ver cada perfil).
- Credenciales: SQL en keyring `modulo_garantias_sql` (las de Loan Tape / PYME); Supabase con el usuario `sistema`
  de Tiempos DAC (keyring `tiempos_dac_supabase`).

## Puesta en marcha

1. **Supabase – esquema**: ejecutar `supabase/schema.sql` en el SQL Editor del proyecto de Tiempos DAC
   (crea perfiles, botón Actualizar, bitácora de preguntas, bucket `cvc` y permisos; deja al administrador inicial).
2. **Supabase – función de preguntas**: en Edge Functions crear `cvc-preguntar` con el código de
   `supabase/functions/cvc-preguntar/index.ts` y guardar el secret `ANTHROPIC_API_KEY`
   (o con la CLI: `supabase functions deploy cvc-preguntar` y `supabase secrets set ANTHROPIC_API_KEY=...`).
   Usa Claude Opus 5.5 con respaldo automático del servidor si el modelo declina una pregunta; límite 40 preguntas
   por usuario y día (`LIMITE_DIARIO`).
3. **Entorno en la PC**: `py -3.12 -m venv .venv` y `.venv\Scripts\python.exe -m pip install pandas pyodbc keyring requests openpyxl`.
4. **Primera carga**: `.venv\Scripts\python.exe worker\actualizar.py --una-vez --forzar todo`.
5. **Tarea programada**: `powershell -ExecutionPolicy Bypass -File ".\Instalar tarea.ps1"`.
6. **GitHub Pages**: en el repositorio, Settings → Pages → Source: *GitHub Actions* (publica la carpeta `public/`).
